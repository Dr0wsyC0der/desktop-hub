from .connection import ESPConnection
from ..models.esp.commands import ESPCommand
from ..core.alive_services import AppContext
import json

class ESPService:
    def __init__(self, bus):
        self.bus = bus
        self.conn = ESPConnection()

    async def start(self):
        await self.conn.start()

        self.bus.subscribe("volume_changed", self.on_volume)
        self.bus.subscribe("track_changed", self.on_track)
        self.bus.subscribe("big_system_load", self.on_load)

        schedule = AppContext.bus_service.SCHEDULE_PATH
        if schedule.exists():
            with open(schedule, "r", encoding="utf-8") as f:
                await self.send("schedule", json.load(f))

    async def on_volume(self, event):
        await self.send("volume", event)

    async def on_track(self, event):
        await self.send("music", event)

    async def on_load(self, event):
        await self.send("system_load", event)

    async def send(self, name, payload):
        await self.conn.broadcast({
            "type": "event",
            "name": name,
            "payload": payload
        })


