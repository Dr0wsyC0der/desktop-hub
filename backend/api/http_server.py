import asyncio
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

from backend.core.alive_services import AppContext


DEFAULT_APP_SETTINGS = {
    "wifi": {"ssid": "", "password": ""},
    "weather": {
        "api_key": "",
        "latitude": "55.7558",
        "longitude": "37.6173",
        "timeout_sec": 1800,
    },
    "display": {
        "brightness": 70,
        "weather_dependent": False,
        "off_time": "23:00",
        "on_time": "07:00",
        "accent_color": "#FFAA00",
    },
    "backlight": {
        "brightness": 70,
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
    "ota": {
        "firmware_path": "",
    },
}


class APIServer:
    SETTINGS_PATH = Path("backend/storage/settings.json")
    LEGACY_UI_SETTINGS_PATH = Path("backend/storage/ui_settings.json")
    BUS_SETTINGS_PATH = SETTINGS_PATH

    def __init__(self, host: str = "127.0.0.1", port: int = 8787):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.runner: web.AppRunner | None = None
        self._gif_state = {
            "stage": "idle",
            "progress": 0,
            "message": "Idle",
        }
        self._ota_state = {
            "stage": "idle",
            "progress": 0,
            "message": "Idle",
        }
        self._setup_routes()

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        print(f"HTTP API started on http://{self.host}:{self.port}")

    def _setup_routes(self):
        self.app.router.add_get("/api/status", self.get_status)
        self.app.router.add_post("/api/esp/command", self.post_command)
        self.app.router.add_post("/api/esp/color", self.post_color)
        self.app.router.add_post("/api/esp/display", self.post_display)
        self.app.router.add_post("/api/esp/backlight", self.post_backlight)
        self.app.router.add_post("/api/esp/gif", self.post_gif)
        self.app.router.add_post("/api/esp/ota", self.post_ota)
        self.app.router.add_get("/api/settings", self.get_settings)
        self.app.router.add_put("/api/settings", self.put_settings)

    async def get_status(self, _request: web.Request):
        esp_service = AppContext.esp_service
        connected = bool(esp_service and esp_service.is_connected())
        last_message = esp_service.last_message if esp_service else None
        return web.json_response(
            {
                "esp_connected": connected,
                "last_message": last_message,
                "gif_transfer": self._gif_state,
                "ota_transfer": self._ota_state,
            }
        )

    async def post_command(self, request: web.Request):
        payload = await request.json()
        await self._send_to_esp(payload)
        return web.json_response({"ok": True})

    async def post_color(self, request: web.Request):
        payload = await request.json()
        esp_service = self._require_esp_service()
        await esp_service.send_color(
            screen=payload.get("screen", "screen1"),
            element=payload["element"],
            color=payload["color"],
        )
        command = {
            "type": "set_color",
            "screen": payload.get("screen", "screen1"),
            "element": payload["element"],
            "color": payload["color"],
        }
        return web.json_response({"ok": True, "command": command})

    async def post_display(self, request: web.Request):
        payload = await request.json()
        payload = dict(payload)
        await self._apply_weather_dependent_brightness(payload)

        esp_service = self._require_esp_service()
        await esp_service.send_display_settings(payload)
        command = {"type": "display_settings", "payload": payload}
        return web.json_response({"ok": True, "command": command})

    async def post_backlight(self, request: web.Request):
        payload = await request.json()
        payload = dict(payload)
        await self._apply_weather_dependent_brightness(payload)

        esp_service = self._require_esp_service()
        await esp_service.send_backlight_settings(payload)
        command = {"type": "backlight_settings", "payload": payload}
        return web.json_response({"ok": True, "command": command})

    async def post_gif(self, request: web.Request):
        payload = await request.json()
        self._gif_state = {"stage": "queued", "progress": 0, "message": "GIF queued"}
        asyncio.create_task(self._run_gif_transfer(payload))
        return web.json_response({"ok": True})

    async def post_ota(self, request: web.Request):
        payload = await request.json()
        firmware_path = str(payload.get("firmware_path", "")).strip()
        if not firmware_path:
            raise web.HTTPBadRequest(text="firmware_path is required")

        self._ota_state = {"stage": "queued", "progress": 0, "message": "OTA queued"}
        asyncio.create_task(self._run_ota_transfer(firmware_path))
        return web.json_response({"ok": True})

    async def get_settings(self, _request: web.Request):
        data = self._load_settings()
        return web.json_response(data)

    async def put_settings(self, request: web.Request):
        payload = await request.json()
        current = self._load_settings()
        merged = self._deep_merge(current, payload)
        normalized = self._normalize_settings(merged)

        self._save_settings(normalized)
        self._sync_bus_settings(normalized.get("schedule", {}))
        self._refresh_bus_service_cache()

        sent_to_esp = False
        esp_service = AppContext.esp_service
        if esp_service and esp_service.is_connected():
            await esp_service.send_all_settings(normalized)
            sent_to_esp = True

        return web.json_response({"ok": True, "settings": normalized, "sent_to_esp": sent_to_esp})

    async def _run_gif_transfer(self, payload: dict[str, Any]):
        try:
            esp_service = self._require_esp_service()
            await esp_service.send_gif(
                name=payload.get("name", "custom.gif"),
                remove_frames=payload.get("remove_frames", []),
                width=int(payload.get("width", 80)),
                height=int(payload.get("height", 80)),
                delay_ms=int(payload.get("delay", payload.get("delay_ms", 200))),
                chunk_size=int(payload.get("chunk_size", 1460)),
                chunk_delay_sec=float(payload.get("chunk_delay_sec", 0.03)),
                progress_cb=self._set_gif_state,
            )
        except Exception as e:
            self._gif_state = {"stage": "error", "progress": 0, "message": f"GIF error: {e}"}

    async def _run_ota_transfer(self, firmware_path: str):
        try:
            esp_service = self._require_esp_service()
            path = Path(firmware_path)
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"Firmware file not found: {firmware_path}")

            await self._set_ota_state("working", 10, "Preparing firmware")
            await asyncio.sleep(0.2)

            await self._set_ota_state("working", 35, "Sending OTA command")
            await esp_service.send_ota_command(str(path))
            await asyncio.sleep(0.2)

            await self._set_ota_state("done", 100, f"OTA command sent: {path.name}")
        except Exception as e:
            self._ota_state = {"stage": "error", "progress": 0, "message": f"OTA error: {e}"}

    async def _set_gif_state(self, stage: str, progress: int, message: str):
        self._gif_state = {
            "stage": stage,
            "progress": max(0, min(int(progress), 100)),
            "message": message,
        }

    async def _set_ota_state(self, stage: str, progress: int, message: str):
        self._ota_state = {
            "stage": stage,
            "progress": max(0, min(int(progress), 100)),
            "message": message,
        }

    async def _apply_weather_dependent_brightness(self, payload: dict[str, Any]):
        if not bool(payload.get("weather_dependent", False)):
            return

        weather_brightness = await self._resolve_weather_brightness()
        if weather_brightness is None:
            return

        payload["brightness"] = weather_brightness
        payload["weather_brightness"] = weather_brightness

    async def _resolve_weather_brightness(self) -> int | None:
        settings = self._load_settings()
        weather = settings.get("weather", {})

        try:
            latitude = float(weather.get("latitude", "0"))
            longitude = float(weather.get("longitude", "0"))
        except (TypeError, ValueError):
            return None

        timeout_sec = max(2, min(15, int(weather.get("timeout_sec", 5))))
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={latitude}&longitude={longitude}"
            "&current=is_day,cloud_cover,weather_code"
            "&timezone=auto"
        )

        try:
            timeout = aiohttp.ClientTimeout(total=timeout_sec)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return None
                    payload = await response.json()
        except Exception:
            return None

        current = payload.get("current", {})
        is_day = bool(current.get("is_day", 1))
        cloud_cover = int(current.get("cloud_cover", 0))
        weather_code = int(current.get("weather_code", 0))

        now_hour = datetime.now().hour
        daylight = is_day or (7 <= now_hour <= 20)

        base = 85 if daylight else 40
        cloud_penalty = cloud_cover * (0.35 if daylight else 0.12)

        # Rain/snow/fog usually requires softer brightness.
        if weather_code in {
            45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67,
            71, 73, 75, 77, 80, 81, 82, 85, 86,
        }:
            base -= 12

        brightness = int(round(base - cloud_penalty))
        return max(15, min(brightness, 100))

    def _require_esp_service(self):
        esp_service = AppContext.esp_service
        if esp_service is None:
            raise web.HTTPServiceUnavailable(text="ESP service not ready")
        if not esp_service.is_connected():
            raise web.HTTPBadRequest(text="ESP is not connected")
        return esp_service

    async def _send_to_esp(self, payload: dict[str, Any]):
        esp_service = self._require_esp_service()
        await esp_service.conn.broadcast(payload)

    def _load_settings(self) -> dict[str, Any]:
        data: dict[str, Any] = {}

        if self.SETTINGS_PATH.exists():
            with open(self.SETTINGS_PATH, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except Exception:
                    data = {}

        # Backward compatibility: merge old ui_settings.json if it still exists.
        if self.LEGACY_UI_SETTINGS_PATH.exists():
            with open(self.LEGACY_UI_SETTINGS_PATH, "r", encoding="utf-8") as f:
                try:
                    legacy = json.load(f)
                except Exception:
                    legacy = {}
            # New settings.json has priority on key conflicts.
            data = self._deep_merge(legacy, data)

        merged = self._deep_merge(deepcopy(DEFAULT_APP_SETTINGS), data)
        return self._normalize_settings(merged)

    def _save_settings(self, data: dict[str, Any]):
        self.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self.SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _normalize_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = self._deep_merge(deepcopy(DEFAULT_APP_SETTINGS), data)

        display = normalized.get("display", {})
        backlight = normalized.get("backlight", {})

        # Migrate legacy fields from display block.
        if "backlight" in display and "brightness" not in backlight:
            backlight["brightness"] = display.get("backlight", 70)
        if "mode" in display and "mode" not in backlight:
            backlight["mode"] = str(display.get("mode", "5"))
        if "led_mode" in display and "led_mode" not in backlight:
            backlight["led_mode"] = int(display.get("led_mode", 5))
        if "auto_brightness" in display and "weather_dependent" not in display:
            display["weather_dependent"] = bool(display.get("auto_brightness", False))

        backlight["mode"] = str(backlight.get("mode", "5"))
        try:
            backlight["led_mode"] = int(backlight.get("led_mode", backlight.get("mode", 5)))
        except (TypeError, ValueError):
            backlight["led_mode"] = 5

        display["brightness"] = self._clamp_percent(display.get("brightness", 70))
        backlight["brightness"] = self._clamp_percent(backlight.get("brightness", 70))

        display["weather_dependent"] = bool(display.get("weather_dependent", False))
        backlight["weather_dependent"] = bool(backlight.get("weather_dependent", False))

        schedule = normalized.get("schedule", {})
        schedule_sources = self._normalize_schedule_sources(schedule.get("sources", []))
        schedule["sources"] = schedule_sources
        schedule["start_time"] = self._normalize_time(schedule.get("start_time", "07:30"), "07:30")
        schedule["end_time"] = self._normalize_time(schedule.get("end_time", "19:30"), "19:30")

        # If bus settings exist in the same settings.json, they are source of truth
        # for schedule window/sources shown in UI.
        bus_settings = normalized.get("bus_settings", {})
        if isinstance(bus_settings, dict):
            interval = bus_settings.get("time_interval", {})
            if isinstance(interval, dict):
                schedule["start_time"] = self._normalize_time(interval.get("start", schedule["start_time"]), schedule["start_time"])
                schedule["end_time"] = self._normalize_time(interval.get("end", schedule["end_time"]), schedule["end_time"])

            bus_stops = bus_settings.get("stops", [])
            if isinstance(bus_stops, list) and bus_stops:
                mapped_sources = []
                for stop in bus_stops:
                    if not isinstance(stop, dict):
                        continue
                    mapped_sources.append(
                        {
                            "url": str(stop.get("url", "")).strip(),
                            "stop_name": str(stop.get("stop_name", "")).strip(),
                            "bus_number": str(stop.get("name", "")).strip(),
                        }
                    )
                schedule["sources"] = self._normalize_schedule_sources(mapped_sources)

        normalized["display"] = display
        normalized["backlight"] = backlight
        normalized["schedule"] = schedule
        normalized["ota"] = {"firmware_path": str(normalized.get("ota", {}).get("firmware_path", "")).strip()}

        return normalized

    def _normalize_schedule_sources(self, raw_sources: Any) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for entry in raw_sources or []:
            if isinstance(entry, str):
                normalized.append({"url": entry.strip(), "stop_name": "", "bus_number": ""})
            elif isinstance(entry, dict):
                normalized.append(
                    {
                        "url": str(entry.get("url", "")).strip(),
                        "stop_name": str(entry.get("stop_name", entry.get("name", ""))).strip(),
                        "bus_number": str(entry.get("bus_number", entry.get("name", ""))).strip(),
                    }
                )

        while len(normalized) < 4:
            normalized.append({"url": "", "stop_name": "", "bus_number": ""})
        return normalized[:4]

    def _normalize_time(self, value: Any, fallback: str) -> str:
        raw = str(value or "").strip()
        try:
            parts = raw.split(":")
            if len(parts) != 2:
                return fallback
            hours = int(parts[0])
            minutes = int(parts[1])
            if not (0 <= hours <= 23 and 0 <= minutes <= 59):
                return fallback
            return f"{hours:02d}:{minutes:02d}"
        except Exception:
            return fallback

    def _clamp_percent(self, value: Any) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = 70
        return max(0, min(number, 100))

    def _sync_bus_settings(self, schedule: dict[str, Any]):
        if self.BUS_SETTINGS_PATH.exists():
            with open(self.BUS_SETTINGS_PATH, "r", encoding="utf-8") as f:
                bus_settings = json.load(f)
        else:
            bus_settings = {"bus_settings": {"stops": [], "time_interval": {"start": "07:30", "end": "19:30"}}}

        if "bus_settings" not in bus_settings:
            bus_settings["bus_settings"] = {}

        stops = []
        for source in self._normalize_schedule_sources(schedule.get("sources", [])):
            if not source["url"]:
                continue
            stops.append(
                {
                    "url": source["url"],
                    "stop_name": source["stop_name"],
                    "name": source["bus_number"] or source["stop_name"] or "Bus",
                }
            )

        bus_settings["bus_settings"]["stops"] = stops
        bus_settings["bus_settings"]["time_interval"] = {
            "start": self._normalize_time(schedule.get("start_time"), "07:30"),
            "end": self._normalize_time(schedule.get("end_time"), "19:30"),
        }

        self.BUS_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self.BUS_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(bus_settings, f, ensure_ascii=False, indent=2)

    def _refresh_bus_service_cache(self):
        bus_service = AppContext.bus_service
        if bus_service is None:
            return

        try:
            bus_service.settings = bus_service._load_settings()
            bus_service.time_interval = bus_service.settings["bus_settings"]["time_interval"]
            asyncio.create_task(bus_service.update_cache())
        except Exception as e:
            print("Failed to refresh bus service cache:", e)

    def _deep_merge(self, base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        for k, v in patch.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                base[k] = self._deep_merge(base[k], v)
            else:
                base[k] = v
        return base
