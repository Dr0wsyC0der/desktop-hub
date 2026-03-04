import asyncio
import json
import re
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
    "ota": {
        "url": "",
        "firmware_path": "",
    },
    "network": {
        "ws_port": 8765,
        "udp_port": 45678,
    },
    "ui_colors": {},
}
HEX_COLOR_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")


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
        self._weather_task: asyncio.Task | None = None
        self._last_weather_display: int | None = None
        self._last_weather_backlight: int | None = None
        self._setup_routes()

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        if self._weather_task is None or self._weather_task.done():
            self._weather_task = asyncio.create_task(self._weather_push_loop())
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
        screen = str(payload.get("screen", "screen1")).strip() or "screen1"
        element = str(payload.get("element", "")).strip()
        color = self._normalize_hex_color(payload.get("color"))
        if not element:
            raise web.HTTPBadRequest(text="element is required")
        if not color:
            raise web.HTTPBadRequest(text="color must be HEX like #RRGGBB")

        esp_service = self._require_esp_service()
        await esp_service.send_color(
            screen=screen,
            element=element,
            color=color,
        )
        self._store_interface_color(screen=screen, element=element, color=color)
        command = {
            "type": "set_color",
            "screen": screen,
            "element": element,
            "color": color,
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
        ota_url = str(payload.get("url", "")).strip()
        if ota_url:
            self._ota_state = {"stage": "working", "progress": 20, "message": "Sending OTA URL to device"}
            await self._send_to_esp({"type": "ota", "url": ota_url})
            self._ota_state = {"stage": "done", "progress": 100, "message": "OTA URL sent"}
            return web.json_response({"ok": True})

        firmware_path = str(payload.get("firmware_path", "")).strip()
        if not firmware_path:
            raise web.HTTPBadRequest(text="url or firmware_path is required")

        self._ota_state = {"stage": "queued", "progress": 0, "message": "OTA queued"}
        asyncio.create_task(self._run_ota_transfer(firmware_path))
        return web.json_response({"ok": True})

    async def get_settings(self, _request: web.Request):
        data = self._load_settings()
        return web.json_response(data)

    async def put_settings(self, request: web.Request):
        payload = await request.json()
        current = self._load_settings()
        merged = self._deep_merge(deepcopy(current), payload)
        normalized = self._normalize_settings(merged, prefer_bus_settings=False)

        self._save_settings(normalized)
        self._sync_bus_settings(normalized.get("schedule", {}))
        self._refresh_bus_service_cache()

        esp_patch = self._build_esp_settings_patch(current, normalized)
        sent_to_esp = False
        esp_service = AppContext.esp_service
        esp_connected = bool(esp_service and esp_service.is_connected())
        patch_to_send = dict(esp_patch)
        send_mode = "diff"
        if esp_connected and not patch_to_send:
            patch_to_send = self._build_esp_settings_snapshot(normalized)
            send_mode = "snapshot" if patch_to_send else "none"

        print(
            f"[API] PUT /settings: esp_connected={esp_connected}, "
            f"send_mode={send_mode}, patch_keys={list(patch_to_send.keys())}"
        )
        if esp_connected and patch_to_send:
            await esp_service.send_settings_patch(patch_to_send)
            sent_to_esp = True

        return web.json_response(
            {
                "ok": True,
                "settings": normalized,
                "sent_to_esp": sent_to_esp,
                "esp_connected": esp_connected,
            }
        )

    async def _run_gif_transfer(self, payload: dict[str, Any]):
        try:
            esp_service = self._require_esp_service()
            await esp_service.send_gif(
                name=payload.get("name", "custom.gif"),
                remove_frames=payload.get("remove_frames", []),
                width=int(payload.get("width", 80)),
                height=int(payload.get("height", 80)),
                delay_ms=int(payload.get("delay", payload.get("delay_ms", 200))),
                chunk_size=int(payload.get("chunk_size", 1024)),
                chunk_delay_sec=float(payload.get("chunk_delay_sec", 0.05)),
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

    async def _resolve_weather_brightness(self, settings: dict[str, Any] | None = None) -> int | None:
        settings = settings or self._load_settings()
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

        base = 220 if daylight else 95
        cloud_penalty = cloud_cover * (1.1 if daylight else 0.45)

        # Rain/snow/fog usually requires softer brightness.
        if weather_code in {
            45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67,
            71, 73, 75, 77, 80, 81, 82, 85, 86,
        }:
            base -= 28

        brightness = int(round(base - cloud_penalty))
        return max(0, min(brightness, 255))

    async def _weather_push_loop(self):
        while True:
            await asyncio.sleep(2.0)
            try:
                settings = self._load_settings()
                display = settings.get("display", {})
                backlight = settings.get("backlight", {})

                need_display = bool(display.get("weather_dependent", False))
                need_backlight = bool(backlight.get("weather_dependent", False))
                if not (need_display or need_backlight):
                    self._last_weather_display = None
                    self._last_weather_backlight = None
                    await asyncio.sleep(3.0)
                    continue

                brightness = await self._resolve_weather_brightness(settings)
                if brightness is None:
                    await asyncio.sleep(5.0)
                    continue

                esp_service = AppContext.esp_service
                if esp_service is None or not esp_service.is_connected():
                    await asyncio.sleep(2.0)
                    continue

                if need_display and brightness != self._last_weather_display:
                    await esp_service.send_display_settings(
                        {
                            "brightness": brightness,
                            "weather_dependent": True,
                            "weather_brightness": brightness,
                        }
                    )
                    self._last_weather_display = brightness

                if need_backlight and brightness != self._last_weather_backlight:
                    await esp_service.send_backlight_settings(
                        {
                            "brightness": brightness,
                            "weather_dependent": True,
                            "weather_brightness": brightness,
                            "mode": backlight.get("mode", "5"),
                            "led_mode": backlight.get("led_mode", backlight.get("mode", 5)),
                            "color": backlight.get("color", ""),
                        }
                    )
                    self._last_weather_backlight = brightness

                # Weather API update cadence.
                await asyncio.sleep(58.0)
            except Exception as e:
                print("Weather push loop error:", e)
                await asyncio.sleep(5.0)

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

    def _store_interface_color(self, *, screen: str, element: str, color: str):
        settings = self._load_settings()
        ui_colors = settings.get("ui_colors")
        if not isinstance(ui_colors, dict):
            ui_colors = {}
            settings["ui_colors"] = ui_colors

        screen_colors = ui_colors.get(screen)
        if not isinstance(screen_colors, dict):
            screen_colors = {}
            ui_colors[screen] = screen_colors

        if screen_colors.get(element) == color:
            return

        screen_colors[element] = color
        normalized = self._normalize_settings(settings, prefer_bus_settings=False)
        self._save_settings(normalized)

    def _normalize_settings(self, data: dict[str, Any], prefer_bus_settings: bool = True) -> dict[str, Any]:
        normalized = self._deep_merge(deepcopy(DEFAULT_APP_SETTINGS), data)

        display = normalized.get("display", {})
        backlight = normalized.get("backlight", {})

        # Migrate legacy fields from display block.
        if "backlight" in display and "brightness" not in backlight:
            backlight["brightness"] = display.get("backlight", 180)
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

        display["brightness"] = self._clamp_brightness(display.get("brightness", 180))
        backlight["brightness"] = self._clamp_brightness(backlight.get("brightness", 180))

        display["weather_dependent"] = bool(display.get("weather_dependent", False))
        backlight["weather_dependent"] = bool(backlight.get("weather_dependent", False))

        schedule = normalized.get("schedule", {})
        schedule_sources = self._normalize_schedule_sources(schedule.get("sources", []))
        schedule["sources"] = schedule_sources
        schedule["start_time"] = self._normalize_time(schedule.get("start_time", "07:30"), "07:30")
        schedule["end_time"] = self._normalize_time(schedule.get("end_time", "19:30"), "19:30")

        # Legacy compatibility: when loading settings for UI/runtime, allow bus_settings
        # to backfill schedule block. During PUT /settings we keep schedule values from payload.
        if prefer_bus_settings:
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
        normalized["ota"] = {
            "url": str(normalized.get("ota", {}).get("url", "")).strip(),
            "firmware_path": str(normalized.get("ota", {}).get("firmware_path", "")).strip(),
        }
        normalized["network"] = {
            "ws_port": self._normalize_port(normalized.get("network", {}).get("ws_port", 8765), 8765),
            "udp_port": self._normalize_port(normalized.get("network", {}).get("udp_port", 45678), 45678),
        }
        normalized["ui_colors"] = self._normalize_ui_colors(normalized.get("ui_colors", {}))

        return normalized

    def _normalize_ui_colors(self, raw_ui_colors: Any) -> dict[str, dict[str, str]]:
        normalized: dict[str, dict[str, str]] = {}
        if not isinstance(raw_ui_colors, dict):
            return normalized

        for screen, elements in raw_ui_colors.items():
            screen_key = str(screen or "").strip()
            if not screen_key or not isinstance(elements, dict):
                continue

            normalized_elements: dict[str, str] = {}
            for element, color in elements.items():
                element_key = str(element or "").strip()
                color_hex = self._normalize_hex_color(color)
                if not element_key or not color_hex:
                    continue
                normalized_elements[element_key] = color_hex

            if normalized_elements:
                normalized[screen_key] = normalized_elements

        return normalized

    def _normalize_hex_color(self, value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if not HEX_COLOR_RE.fullmatch(raw):
            return ""
        prefixed = raw if raw.startswith("#") else f"#{raw}"
        return prefixed.upper()

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

    def _clamp_brightness(self, value: Any) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = 180
        return max(0, min(number, 255))

    def _normalize_port(self, value: Any, fallback: int) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            port = fallback
        return max(1, min(65535, port))

    def _normalize_timeout_sec(self, value: Any, fallback: int = 1800) -> int:
        try:
            timeout = int(value)
        except (TypeError, ValueError):
            timeout = fallback
        return max(1, timeout)

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

    def _build_esp_settings_patch(self, previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        # Base rule: send every changed setting except schedule.sources.
        patch: dict[str, Any] = self._build_generic_settings_diff(previous, current)

        previous_weather = previous.get("weather", {}) if isinstance(previous.get("weather"), dict) else {}
        current_weather = current.get("weather", {}) if isinstance(current.get("weather"), dict) else {}

        prev_api_key = str(previous_weather.get("api_key", "")).strip()
        curr_api_key = str(current_weather.get("api_key", "")).strip()
        if prev_api_key != curr_api_key:
            patch["weather_api_key"] = curr_api_key

        prev_timeout = self._normalize_timeout_sec(previous_weather.get("timeout_sec", 1800))
        curr_timeout = self._normalize_timeout_sec(current_weather.get("timeout_sec", 1800))
        if prev_timeout != curr_timeout:
            patch["weather_timeout_sec"] = curr_timeout

        prev_lat = str(previous_weather.get("latitude", "")).strip()
        curr_lat = str(current_weather.get("latitude", "")).strip()

        prev_lon = str(previous_weather.get("longitude", "")).strip()
        curr_lon = str(current_weather.get("longitude", "")).strip()
        lat_changed = prev_lat != curr_lat
        lon_changed = prev_lon != curr_lon
        if lat_changed or lon_changed:
            patch["weather_lat"] = self._coord_payload_value(curr_lat)
            patch["weather_lon"] = self._coord_payload_value(curr_lon)
            patch["latitude"] = curr_lat
            patch["longitude"] = curr_lon

        previous_display = previous.get("display", {}) if isinstance(previous.get("display"), dict) else {}
        current_display = current.get("display", {}) if isinstance(current.get("display"), dict) else {}

        prev_screen_brightness = self._clamp_brightness(previous_display.get("brightness", 180))
        curr_screen_brightness = self._clamp_brightness(current_display.get("brightness", 180))
        if prev_screen_brightness != curr_screen_brightness:
            patch["screen_brightness"] = curr_screen_brightness

        prev_display_weather = bool(previous_display.get("weather_dependent", previous_display.get("auto_brightness", False)))
        curr_display_weather = bool(current_display.get("weather_dependent", current_display.get("auto_brightness", False)))
        if prev_display_weather != curr_display_weather:
            patch["auto_brightness"] = curr_display_weather

        prev_accent_color = str(previous_display.get("accent_color", "")).strip()
        curr_accent_color = str(current_display.get("accent_color", "")).strip()
        if prev_accent_color != curr_accent_color and curr_accent_color:
            patch["accent_color"] = curr_accent_color

        previous_backlight = previous.get("backlight", {}) if isinstance(previous.get("backlight"), dict) else {}
        current_backlight = current.get("backlight", {}) if isinstance(current.get("backlight"), dict) else {}

        prev_backlight_brightness = self._clamp_brightness(previous_backlight.get("brightness", 180))
        curr_backlight_brightness = self._clamp_brightness(current_backlight.get("brightness", 180))
        if prev_backlight_brightness != curr_backlight_brightness:
            patch["led_brightness"] = curr_backlight_brightness

        prev_led_mode = self._normalize_led_mode(previous_backlight.get("led_mode", previous_backlight.get("mode", 5)))
        curr_led_mode = self._normalize_led_mode(current_backlight.get("led_mode", current_backlight.get("mode", 5)))
        if prev_led_mode != curr_led_mode:
            patch["led_mode"] = curr_led_mode

        prev_led_color = str(previous_backlight.get("color", "")).strip()
        curr_led_color = str(current_backlight.get("color", "")).strip()
        if prev_led_color != curr_led_color and curr_led_color:
            patch["led_color"] = curr_led_color

        prev_backlight_weather = bool(previous_backlight.get("weather_dependent", False))
        curr_backlight_weather = bool(current_backlight.get("weather_dependent", False))
        if prev_backlight_weather != curr_backlight_weather:
            patch["led_weather_dependent"] = curr_backlight_weather

        prev_on = self._normalize_time(previous_display.get("on_time", "07:00"), "07:00")
        curr_on = self._normalize_time(current_display.get("on_time", "07:00"), "07:00")
        if prev_on != curr_on:
            patch["screen_on_time"] = curr_on

        prev_off = self._normalize_time(previous_display.get("off_time", "23:00"), "23:00")
        curr_off = self._normalize_time(current_display.get("off_time", "23:00"), "23:00")
        if prev_off != curr_off:
            patch["screen_off_time"] = curr_off

        previous_schedule = previous.get("schedule", {}) if isinstance(previous.get("schedule"), dict) else {}
        current_schedule = current.get("schedule", {}) if isinstance(current.get("schedule"), dict) else {}

        prev_start = self._normalize_time(previous_schedule.get("start_time", "07:30"), "07:30")
        curr_start = self._normalize_time(current_schedule.get("start_time", "07:30"), "07:30")
        if prev_start != curr_start:
            patch["schedule_start_time"] = curr_start
            patch["backlight_on_time"] = curr_start

        prev_end = self._normalize_time(previous_schedule.get("end_time", "19:30"), "19:30")
        curr_end = self._normalize_time(current_schedule.get("end_time", "19:30"), "19:30")
        if prev_end != curr_end:
            patch["schedule_end_time"] = curr_end
            patch["backlight_off_time"] = curr_end

        previous_ota = previous.get("ota", {}) if isinstance(previous.get("ota"), dict) else {}
        current_ota = current.get("ota", {}) if isinstance(current.get("ota"), dict) else {}
        prev_ota_url = str(previous_ota.get("url", "")).strip()
        curr_ota_url = str(current_ota.get("url", "")).strip()
        if prev_ota_url != curr_ota_url:
            patch["ota_url"] = curr_ota_url

        previous_network = previous.get("network", {}) if isinstance(previous.get("network"), dict) else {}
        current_network = current.get("network", {}) if isinstance(current.get("network"), dict) else {}
        prev_ws_port = self._normalize_port(previous_network.get("ws_port", 8765), 8765)
        curr_ws_port = self._normalize_port(current_network.get("ws_port", 8765), 8765)
        if prev_ws_port != curr_ws_port:
            patch["ws_port"] = curr_ws_port

        if prev_on != curr_on or prev_off != curr_off:
            sleep_start_hour, sleep_start_minute = self._time_to_parts(curr_off)
            sleep_end_hour, sleep_end_minute = self._time_to_parts(curr_on)
            patch["sleep_enabled"] = True
            patch["sleep_start_hour"] = sleep_start_hour
            patch["sleep_start_minute"] = sleep_start_minute
            patch["sleep_end_hour"] = sleep_end_hour
            patch["sleep_end_minute"] = sleep_end_minute

        return patch

    def _build_esp_settings_snapshot(self, settings: dict[str, Any]) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}

        display = settings.get("display", {}) if isinstance(settings.get("display"), dict) else {}
        backlight = settings.get("backlight", {}) if isinstance(settings.get("backlight"), dict) else {}
        weather = settings.get("weather", {}) if isinstance(settings.get("weather"), dict) else {}

        snapshot["screen_brightness"] = self._clamp_brightness(display.get("brightness", 180))
        snapshot["auto_brightness"] = bool(display.get("weather_dependent", display.get("auto_brightness", False)))
        snapshot["led_brightness"] = self._clamp_brightness(backlight.get("brightness", 180))
        snapshot["led_mode"] = self._normalize_led_mode(backlight.get("led_mode", backlight.get("mode", 5)))

        led_color = str(backlight.get("color", "")).strip()
        if led_color:
            snapshot["led_color"] = led_color

        lat = str(weather.get("latitude", "")).strip()
        lon = str(weather.get("longitude", "")).strip()
        if lat and lon:
            snapshot["weather_lat"] = self._coord_payload_value(lat)
            snapshot["weather_lon"] = self._coord_payload_value(lon)
            snapshot["latitude"] = lat
            snapshot["longitude"] = lon

        api_key = str(weather.get("api_key", "")).strip()
        snapshot["weather_api_key"] = api_key
        snapshot["weather_timeout_sec"] = self._normalize_timeout_sec(weather.get("timeout_sec", 1800))

        on_time = self._normalize_time(display.get("on_time", "07:00"), "07:00")
        off_time = self._normalize_time(display.get("off_time", "23:00"), "23:00")
        sleep_start_hour, sleep_start_minute = self._time_to_parts(off_time)
        sleep_end_hour, sleep_end_minute = self._time_to_parts(on_time)
        snapshot["sleep_enabled"] = True
        snapshot["sleep_start_hour"] = sleep_start_hour
        snapshot["sleep_start_minute"] = sleep_start_minute
        snapshot["sleep_end_hour"] = sleep_end_hour
        snapshot["sleep_end_minute"] = sleep_end_minute

        return snapshot

    def _build_generic_settings_diff(self, previous: Any, current: Any, path: tuple[str, ...] = ()) -> dict[str, Any]:
        if self._is_excluded_settings_path(path):
            return {}

        # Recurse dictionaries key by key to keep patch granular.
        if isinstance(previous, dict) and isinstance(current, dict):
            diff: dict[str, Any] = {}
            for key in sorted(set(previous.keys()) | set(current.keys())):
                child_prev = previous.get(key)
                child_curr = current.get(key)
                diff.update(self._build_generic_settings_diff(child_prev, child_curr, path + (str(key),)))
            return diff

        if previous == current:
            return {}

        if not path:
            return {}

        return {"_".join(path): current}

    def _is_excluded_settings_path(self, path: tuple[str, ...]) -> bool:
        # Explicitly do not send schedule sources to ESP.
        if len(path) >= 2 and path[0] == "schedule" and path[1] == "sources":
            return True
        # Interface color map is replayed via `set_color` on connect.
        return len(path) >= 1 and path[0] == "ui_colors"

    def _normalize_led_mode(self, value: Any) -> int:
        try:
            mode = int(str(value).strip())
        except (TypeError, ValueError):
            mode = 5
        return max(1, min(7, mode))

    def _coord_payload_value(self, value: Any) -> float | str:
        raw = str(value).strip()
        try:
            return float(raw)
        except (TypeError, ValueError):
            return raw

    def _time_to_parts(self, value: Any) -> tuple[int, int]:
        normalized = self._normalize_time(value, "00:00")
        hours, minutes = normalized.split(":")
        return int(hours), int(minutes)

    def _deep_merge(self, base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        for k, v in patch.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                base[k] = self._deep_merge(base[k], v)
            else:
                base[k] = v
        return base
