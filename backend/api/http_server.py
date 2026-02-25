import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

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
        "backlight": 70,
        "mode": "static",
        "auto_brightness": True,
        "off_time": "23:00",
        "on_time": "07:00",
    },
    "schedule": {
        "hours_ahead": 4,
        "sources": [],
    },
}


class APIServer:
    SETTINGS_PATH = Path("backend/storage/ui_settings.json")

    def __init__(self, host: str = "127.0.0.1", port: int = 8787):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.runner: web.AppRunner | None = None
        self._gif_state = {
            "stage": "idle",
            "progress": 0,
            "message": "Ожидание",
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
        self.app.router.add_post("/api/esp/gif", self.post_gif)
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
            }
        )

    async def post_command(self, request: web.Request):
        payload = await request.json()
        await self._send_to_esp(payload)
        return web.json_response({"ok": True})

    async def post_color(self, request: web.Request):
        payload = await request.json()
        command = {
            "type": "set_color",
            "screen": payload.get("screen", "screen1"),
            "element": payload["element"],
            "color": payload["color"],
        }
        await self._send_to_esp(command)
        return web.json_response({"ok": True, "command": command})

    async def post_display(self, request: web.Request):
        payload = await request.json()
        command = {
            "type": "display_settings",
            "payload": payload,
        }
        await self._send_to_esp(command)
        return web.json_response({"ok": True, "command": command})

    async def post_gif(self, request: web.Request):
        payload = await request.json()
        asyncio.create_task(self._simulate_gif_transfer(payload))
        return web.json_response({"ok": True})

    async def get_settings(self, _request: web.Request):
        data = self._load_settings()
        return web.json_response(data)

    async def put_settings(self, request: web.Request):
        payload = await request.json()
        current = self._load_settings()
        merged = self._deep_merge(current, payload)
        self._save_settings(merged)
        await self._send_to_esp({"type": "settings_update", "payload": merged})
        return web.json_response({"ok": True, "settings": merged})

    async def _simulate_gif_transfer(self, payload: dict[str, Any]):
        steps = [
            (10, "Подготовка GIF"),
            (30, "Удаление лишних кадров"),
            (60, "Сжатие и упаковка"),
            (85, "Отправка на устройство"),
            (100, "Готово"),
        ]

        self._gif_state = {"stage": "working", "progress": 0, "message": "Запуск"}

        for progress, message in steps:
            self._gif_state = {"stage": "working", "progress": progress, "message": message}
            await asyncio.sleep(0.8)

        command = {
            "type": "set_gif",
            "name": payload.get("name", "custom"),
            "remove_frames": payload.get("remove_frames", []),
        }
        await self._send_to_esp(command)
        self._gif_state = {"stage": "done", "progress": 100, "message": "GIF отправлена"}

    async def _send_to_esp(self, payload: dict[str, Any]):
        esp_service = AppContext.esp_service
        if esp_service is None:
            raise web.HTTPServiceUnavailable(text="ESP service not ready")
        if not esp_service.is_connected():
            raise web.HTTPBadRequest(text="ESP is not connected")
        await esp_service.conn.broadcast(payload)

    def _load_settings(self) -> dict[str, Any]:
        if not self.SETTINGS_PATH.exists():
            return deepcopy(DEFAULT_APP_SETTINGS)

        with open(self.SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        return self._deep_merge(deepcopy(DEFAULT_APP_SETTINGS), data)

    def _save_settings(self, data: dict[str, Any]):
        self.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self.SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _deep_merge(self, base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        for k, v in patch.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                base[k] = self._deep_merge(base[k], v)
            else:
                base[k] = v
        return base
