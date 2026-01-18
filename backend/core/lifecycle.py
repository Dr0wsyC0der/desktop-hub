from core.event_bus import EventBus
from core.alive_services import AppContext
from modules.buses.service import BusService
from modules.output.console import ConsoleOutput

async def boot() -> EventBus:
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

    return bus
