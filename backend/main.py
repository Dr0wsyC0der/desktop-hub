import asyncio
from backend.core.event_bus import EventBus
from backend.modules.music.service import MediaPlayerService
from backend.modules.volume.service import VolumeService
from backend.modules.system_monitor.service import AsyncSystemMonitor
from backend.modules.output.console import ConsoleOutput
from backend.modules.buses.service import BusService
from backend.core.lifecycle import AppContext

async def main():
    bus = EventBus()

    console = ConsoleOutput(show_album=True)

    bus.subscribe("track_changed", console.on_track)
    bus.subscribe("volume_changed", console.on_volume)
    bus.subscribe("big_system_load", console.on_load)


    bus_service = BusService()
    try:
        await bus_service.update_cache()
    except Exception as e:
        print("Не удалось обновить расписание:", e)
    AppContext.bus_service = bus_service

    await asyncio.gather(
        MediaPlayerService(bus).start(),
        VolumeService(bus).start(),
        AsyncSystemMonitor(bus).start()
    )

asyncio.run(main())