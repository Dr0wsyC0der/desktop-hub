import asyncio
from .core.lifecycle import boot
from .modules.music.service import MediaPlayerService
from .modules.volume.service import VolumeService
from .modules.system_monitor.service import AsyncSystemMonitor
from .esp.service import ESPService

async def main():
    bus = await boot()

    services = [
        MediaPlayerService(bus),
        VolumeService(bus),
        AsyncSystemMonitor(bus),
        ESPService(bus),
    ]

    tasks = []
    for s in services:
        tasks.append(asyncio.create_task(s.start()))

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
