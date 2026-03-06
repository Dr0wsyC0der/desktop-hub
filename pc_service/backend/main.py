import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    # Allow running via `python backend/main.py` from the project root.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from backend.api.http_server import APIServer
    from backend.core.alive_services import AppContext
    from backend.core.lifecycle import boot
    from backend.esp.service import ESPService
    from backend.modules.music.service import MediaPlayerService
    from backend.modules.volume.service import VolumeService
else:
    from .api.http_server import APIServer
    from .core.alive_services import AppContext
    from .core.lifecycle import boot
    from .esp.service import ESPService
    from .modules.music.service import MediaPlayerService
    from .modules.volume.service import VolumeService


async def main():
    bus = await boot()

    esp_service = ESPService(bus)
    api_server = APIServer()
    AppContext.esp_service = esp_service

    services = [
        MediaPlayerService(bus),
        VolumeService(bus),
        esp_service,
        api_server,
    ]

    tasks = []
    for s in services:
        tasks.append(asyncio.create_task(s.start()))

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
