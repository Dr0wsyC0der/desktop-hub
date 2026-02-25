import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from typing import Awaitable, Callable, Optional

import GPUtil
import psutil

from .connection import ESPConnection
from .gif_codec import build_rgb565_from_gif
from ..models.esp.commands import ESPCommand
from ..core.alive_services import AppContext


class ESPService:
    def __init__(self, bus):
        self.bus = bus
        self.conn = ESPConnection()
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

    async def start(self):
        # Передаём обработчик входящих сообщений в соединение
        await self.conn.start(self.on_message)

        self.bus.subscribe("volume_changed", self.on_volume)
        self.bus.subscribe("track_changed", self.on_track)
        self.bus.subscribe("big_system_load", self.on_load)

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
        await self.conn.broadcast_json(
            {
                "type": "display_settings",
                "payload": payload,
            }
        )

    async def send_all_settings(self, settings: dict):
        """
        Keep backward compatibility with current ESP firmware (`settings_update`)
        and also send the display block as a dedicated command if it exists.
        """
        await self.conn.broadcast_json({"type": "settings_update", "payload": settings})

        display_payload = settings.get("display")
        if isinstance(display_payload, dict):
            await self.send_display_settings(display_payload)

    async def send_gif(
        self,
        *,
        name: str,
        remove_frames: list[int] | None = None,
        width: int = 80,
        height: int = 80,
        delay_ms: int = 200,
        chunk_size: int = 1460,
        chunk_delay_sec: float = 0.03,
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


    def is_connected(self) -> bool:
        return len(self.conn.clients) > 0

    async def on_load(self, event):
        await self.send("system_load", event)

    async def _send_schedule(self, schedule_data: dict):
        """
        Отправка расписания в формате:
        {"type": "schedule", "payload": dict}
        """
        await self.conn.broadcast({
            "type": "schedule",
            "payload": schedule_data
        })

    async def send(self, name, payload):
        await self.conn.broadcast({
            "type": "event",
            "name": name,
            "payload": payload
        })

