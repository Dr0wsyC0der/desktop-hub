import asyncio
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume


class VolumeService:
    def __init__(self, bus, poll_interval=0.2):
        self.bus = bus
        self.poll_interval = poll_interval
        self._last = None

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(
            IAudioEndpointVolume._iid_,
            CLSCTX_ALL,
            None
        )
        self.volume = cast(interface, POINTER(IAudioEndpointVolume))

    async def start(self):
        self._last = int(self.volume.GetMasterVolumeLevelScalar() * 100)

        while True:
            current = int(self.volume.GetMasterVolumeLevelScalar() * 100)

            if current != self._last:
                self._last = current
                await self.bus.publish("volume_changed", {
                    "value": current
                })

            await asyncio.sleep(self.poll_interval)
