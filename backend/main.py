import asyncio

from .api.http_server import APIServer
from .core.alive_services import AppContext
from .core.lifecycle import boot
from .esp.service import ESPService
from .modules.music.service import MediaPlayerService
from .modules.system_monitor.service import AsyncSystemMonitor
from .modules.volume.service import VolumeService


async def main():
    bus = await boot()

    esp_service = ESPService(bus)
    api_server = APIServer()
    AppContext.esp_service = esp_service

    services = [
        MediaPlayerService(bus),
        VolumeService(bus),
        AsyncSystemMonitor(bus),
        esp_service,
        api_server,
    ]

    tasks = []
    for s in services:
        tasks.append(asyncio.create_task(s.start()))

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
