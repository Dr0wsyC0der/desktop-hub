import asyncio
from core.lifecycle import boot
from modules.music.service import MediaPlayerService
from modules.volume.service import VolumeService
from modules.system_monitor.service import AsyncSystemMonitor

async def main():
    bus = await boot()

    await asyncio.gather(
        MediaPlayerService(bus).start(),
        VolumeService(bus).start(),
        AsyncSystemMonitor(bus).start()
    )

if __name__ == "__main__":
    asyncio.run(main())
