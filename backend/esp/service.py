import asyncio
import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Awaitable, Callable, Optional

import GPUtil
import psutil

from .connection import ESPConnection
from .gif_codec import build_rgb565_from_gif
from ..core.alive_services import AppContext


DEFAULT_STORED_SETTINGS = {
    "wifi": {"ssid": "", "password": ""},
    "weather": {
        "api_key": "",
        "latitude": "55.7558",
        "longitude": "37.6173",
        "timeout_sec": 1800,
    },
    "display": {
        "brightness": 180,
        "weather_dependent": False,
        "off_time": "23:00",
        "on_time": "07:00",
        "accent_color": "#FFAA00",
    },
    "backlight": {
        "brightness": 180,
        "mode": "5",
        "led_mode": 5,
        "weather_dependent": False,
        "color": "#33CCFF",
    },
    "schedule": {
        "start_time": "07:30",
        "end_time": "19:30",
        "sources": [
            {"url": "", "stop_name": "", "bus_number": ""},
            {"url": "", "stop_name": "", "bus_number": ""},
            {"url": "", "stop_name": "", "bus_number": ""},
            {"url": "", "stop_name": "", "bus_number": ""},
        ],
    },
    "ota": {"url": "", "firmware_path": ""},
    "network": {"ws_port": 8765, "udp_port": 45678},
    "ui_colors": {},
}
HEX_COLOR_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")


class ESPService:
    SETTINGS_PATH = Path("backend/storage/settings.json")

    def __init__(self, bus):
        self.bus = bus
        ws_port, udp_port = self._load_network_ports()
        self.conn = ESPConnection(port=ws_port, udp_port=udp_port)
        self.last_message = None
        self._gif_lock = asyncio.Lock()
        self._gif_assets_dirs = [
            Path("backend/storage/gifs"),
            Path("ui/assets/gifs"),
            Path("ui/assets"),
            Path("assets/gifs"),
            Path("assets"),
        ]

        # Параметры мониторинга нагрузки ПК
        self._pc_load_interval: float = 0.5
        self._pc_load_task: Optional[asyncio.Task] = None
        self._pc_load_running: bool = False

    def _load_network_ports(self) -> tuple[int, int]:
        ws_port = 8765
        udp_port = 45678

        if not self.SETTINGS_PATH.exists():
            return ws_port, udp_port

        try:
            with open(self.SETTINGS_PATH, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            return ws_port, udp_port

        network = settings.get("network", {})
        try:
            ws_port = int(network.get("ws_port", ws_port))
        except (TypeError, ValueError):
            ws_port = 8765
        try:
            udp_port = int(network.get("udp_port", udp_port))
        except (TypeError, ValueError):
            udp_port = 45678

        ws_port = max(1, min(65535, ws_port))
        udp_port = max(1, min(65535, udp_port))
        return ws_port, udp_port

    async def start(self):
        # Передаём обработчик входящих сообщений в соединение
        await self.conn.start(self.on_message, self._on_connect)

        self.bus.subscribe("volume_changed", self.on_volume)
        self.bus.subscribe("track_changed", self.on_track)

    async def _on_connect(self):
        settings = self._load_saved_settings()
        await self.send_all_settings(settings)
        await self.send_saved_interface_colors(settings)

    def _load_saved_settings(self) -> dict:
        settings = deepcopy(DEFAULT_STORED_SETTINGS)
        if not self.SETTINGS_PATH.exists():
            return settings

        try:
            with open(self.SETTINGS_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except Exception:
            return settings

        if not isinstance(loaded, dict):
            return settings

        return self._deep_merge(settings, loaded)

    def _deep_merge(self, base: dict, patch: dict) -> dict:
        for key, value in patch.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                base[key] = self._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    async def on_message(self, raw_msg: str):
        """
        Обработка входящих WS-сообщений от ESP.

        Ожидаем, в том числе:
        {"type": "pc_load", "action": "start"}
        {"type": "pc_load", "action": "stop"}
        {"type": "schedule_date", "date": "2026-02-12"}
        """
        self.last_message = raw_msg

        try:
            data = json.loads(raw_msg)
        except json.JSONDecodeError:
            # Игнорируем не-JSON сообщения
            return

        msg_type = data.get("type")
        action = data.get("action")

        if msg_type == "pc_load":
            if action == "start":
                await self._start_pc_load()
            elif action == "stop":
                await self._stop_pc_load()
        elif msg_type == "schedule_date":
            await self._handle_schedule_date(data)

    async def _handle_schedule_date(self, data: dict):
        """
        Обработка ответа вида:
        {"type": "schedule_date", "date": "YYYY-MM-DD"}

        - если дата сегодняшняя — расписание НЕ отправляем
        - если дата вчерашняя или более старая — отправляем актуальное расписание
        - если дата невалидна/пустая — считаем расписание устаревшим и отправляем
        """
        raw_date = data.get("date")

        need_send = True
        if isinstance(raw_date, str) and raw_date:
            try:
                schedule_dt = datetime.fromisoformat(raw_date).date()
                today = date.today()
                # если дата раньше сегодняшней — нужно отправить новое расписание
                # если дата сегодня или в будущем — НЕ отправляем
                need_send = schedule_dt < today
            except ValueError:
                # не смогли распарсить дату — на всякий случай отправим расписание
                need_send = True

        if not need_send:
            print("Schedule on ESP is up-to-date, skip sending")
            return

        schedule_path = AppContext.bus_service.SCHEDULE_PATH
        if not schedule_path.exists():
            print("Schedule file not found, nothing to send")
            return

        try:
            with open(schedule_path, "r", encoding="utf-8") as f:
                schedule_data = json.load(f)
        except Exception as e:
            print("Failed to read schedule file:", e)
            return

        await self._send_schedule(schedule_data)

    async def _start_pc_load(self):
        if self._pc_load_running:
            return
        self._pc_load_running = True
        self._pc_load_task = asyncio.create_task(self._pc_load_loop())
        print("PC load monitoring started")

    async def _stop_pc_load(self):
        self._pc_load_running = False
        if self._pc_load_task:
            await self._pc_load_task
            self._pc_load_task = None
        print("PC load monitoring stopped")

    async def _pc_load_loop(self):
        while self._pc_load_running:
            await asyncio.sleep(self._pc_load_interval)

            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            gpu = self._get_gpu_load()

            await self._send_pc_load(cpu, gpu, ram)

    def _get_gpu_load(self) -> float:
        try:
            gpus = GPUtil.getGPUs()
            if not gpus:
                return 0.0
            return gpus[0].load * 100
        except Exception:
            return 0.0

    async def _send_pc_load(self, cpu: float, gpu: float, ram: float):
        """
        Отправка текущей нагрузки ПК в формате:
        {
          "type": "pc_load",
          "cpu": ...,
          "gpu": ...,
          "ram": ...
        }
        """
        await self.conn.broadcast({
            "type": "pc_load",
            "cpu": cpu,
            "gpu": gpu,
            "ram": ram,
        })

    async def send_color(self, *, screen: str, element: str, color: str):
        await self.conn.broadcast_json(
            {
                "type": "set_color",
                "screen": screen,
                "element": element,
                "color": color,
            }
        )

    async def send_display_settings(self, payload: dict):
        brightness_raw = self._brightness_byte(payload.get("brightness", 180))
        command = {
            "type": "settings",
            "screen_brightness": brightness_raw,
            "auto_brightness": bool(payload.get("weather_dependent", payload.get("auto_brightness", False))),
        }

        if "weather_brightness" in payload:
            command["screen_weather_brightness"] = self._brightness_byte(payload.get("weather_brightness", brightness_raw))

        await self.conn.broadcast_json(command)

    async def send_backlight_settings(self, payload: dict):
        brightness_raw = self._brightness_byte(payload.get("brightness", payload.get("backlight", 180)))
        led_mode = payload.get("led_mode", payload.get("mode", 5))
        try:
            led_mode = int(led_mode)
        except (TypeError, ValueError):
            led_mode = 5

        command = {
            "type": "settings",
            "led_brightness": brightness_raw,
            "led_mode": max(1, min(7, led_mode)),
            "led_weather_dependent": bool(payload.get("weather_dependent", False)),
        }

        color = payload.get("color")
        if color:
            command["led_color"] = str(color)

        if "weather_brightness" in payload:
            command["led_weather_brightness"] = self._brightness_byte(payload.get("weather_brightness", brightness_raw))

        await self.conn.broadcast_json(command)

    async def send_settings_patch(self, patch: dict):
        if not isinstance(patch, dict):
            return

        compact_patch = {k: v for k, v in patch.items() if v is not None}
        if not compact_patch:
            return

        command = {"type": "settings"}
        command.update(compact_patch)
        print(f"[ESP] send_settings_patch -> {command}")
        await self.conn.broadcast_json(command)

    async def send_all_settings(self, settings: dict):
        """
        Keep backward compatibility with current ESP firmware (`settings_update`)
        and also send display/backlight blocks as dedicated commands.
        """
        await self.conn.broadcast_json({"type": "settings_update", "payload": settings})

        display_payload = settings.get("display")
        if isinstance(display_payload, dict):
            await self.send_display_settings(display_payload)

        backlight_payload = settings.get("backlight")
        if isinstance(backlight_payload, dict):
            await self.send_backlight_settings(backlight_payload)

    async def send_saved_interface_colors(self, settings: dict):
        ui_colors = settings.get("ui_colors", {})
        if not isinstance(ui_colors, dict):
            return

        sent_count = 0
        for screen_name, elements in ui_colors.items():
            screen = str(screen_name or "").strip()
            if not screen or not isinstance(elements, dict):
                continue

            for element_name, color_raw in elements.items():
                element = str(element_name or "").strip()
                color = self._normalize_hex_color(color_raw)
                if not element or not color:
                    continue

                await self.send_color(screen=screen, element=element, color=color)
                sent_count += 1

        if sent_count:
            print(f"[ESP] reapplied saved interface colors: {sent_count}")

    async def send_ota_command(self, firmware_path: str):
        path = Path(firmware_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Firmware file not found: {firmware_path}")

        checksum = hashlib.sha1()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                checksum.update(chunk)

        await self.conn.broadcast_json(
            {
                "type": "ota_update",
                "name": path.name,
                "size": path.stat().st_size,
                "sha1": checksum.hexdigest(),
                "path": str(path),
            }
        )

    async def send_gif(
        self,
        *,
        name: str,
        remove_frames: list[int] | None = None,
        width: int = 80,
        height: int = 80,
        delay_ms: int = 200,
        chunk_size: int = 1024,
        chunk_delay_sec: float = 0.05,
        progress_cb: Optional[Callable[[str, int, str], Awaitable[None]]] = None,
    ):
        async with self._gif_lock:
            if progress_cb:
                await progress_cb("working", 5, "Подготовка GIF")

            gif_path = self._resolve_gif_path(name)
            payload = build_rgb565_from_gif(
                gif_path,
                name=Path(name).name,
                width=int(width),
                height=int(height),
                delay_ms=int(delay_ms),
                remove_frames=remove_frames or [],
            )

            if progress_cb:
                await progress_cb("working", 35, "Отправка метаданных GIF")

            await self.conn.broadcast_json(payload.metadata())
            await asyncio.sleep(0.6)

            total = payload.total_size or 1
            sent = 0

            if progress_cb:
                await progress_cb("working", 45, "Отправка GIF на устройство")

            for i in range(0, len(payload.data), max(1, int(chunk_size))):
                chunk = payload.data[i:i + int(chunk_size)]
                await self.conn.broadcast_bytes(chunk)
                sent += len(chunk)

                # 45..100 reserved for transfer progress.
                progress = 45 + int((sent / total) * 55)
                if progress_cb:
                    await progress_cb("working", min(progress, 99), f"Отправка GIF: {sent}/{total} байт")

                if chunk_delay_sec > 0:
                    await asyncio.sleep(chunk_delay_sec)

            if progress_cb:
                await progress_cb("done", 100, "GIF отправлена")

    def _resolve_gif_path(self, name: str) -> Path:
        raw = Path(name)
        if raw.is_file():
            return raw

        for base in self._gif_assets_dirs:
            candidate = base / name
            if candidate.is_file():
                return candidate

        searched = ", ".join(str(p) for p in self._gif_assets_dirs)
        raise FileNotFoundError(f"GIF '{name}' not found. Searched in: {searched}")

    async def on_volume(self, event):
        """
        Обработка события изменения громкости.
        event: {"type": "volume", "value": int}
        Отправляем: {"type": "volume", "value": int}
        """
        value = event.get("value")
        if value is not None:
            await self.conn.broadcast({
                "type": "volume",
                "value": int(value)
            })

    async def on_track(self, event):
        """
        Обработка события изменения трека.
        event: {"name": str, "author": str}
        Отправляем: {"type": "music", "name": str, "author": str}
        """
        name = event.get("name", "")
        author = event.get("author", "")
        await self.conn.broadcast({
            "type": "music",
            "name": str(name),
            "author": str(author)
        })


    def _brightness_byte(self, value: int | float | str) -> int:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            number = 180

        return max(0, min(255, number))

    def _normalize_hex_color(self, value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if not HEX_COLOR_RE.fullmatch(raw):
            return ""
        prefixed = raw if raw.startswith("#") else f"#{raw}"
        return prefixed.upper()

    def is_connected(self) -> bool:
        return len(self.conn.clients) > 0

    async def _send_schedule(self, schedule_data: dict):
        """
        Отправка расписания в формате:
        {"type": "schedule", "payload": dict}
        """
        await self.conn.broadcast({
            "type": "schedule",
            "payload": schedule_data
        })


