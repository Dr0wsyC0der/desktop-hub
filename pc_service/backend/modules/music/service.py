import asyncio
from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager
)


class MediaPlayerService:
    def __init__(self, bus, poll_interval=0.5):
        self.bus = bus
        self.poll_interval = poll_interval
        self._last_key = None
        self._sessions = None

    async def start(self):
        self._sessions = await MediaManager.request_async()

        while True:
            session = self._sessions.get_current_session()
            if session:
                props = await session.try_get_media_properties_async()

                if props.title:
                    key = (props.title, props.artist)
                    if key != self._last_key:
                        self._last_key = key
                        await self.bus.publish("track_changed", {
                            "name": props.title,
                            "author": props.artist,
                        })

            await asyncio.sleep(self.poll_interval)



