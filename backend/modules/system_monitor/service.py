import asyncio
import psutil
import GPUtil


class AsyncSystemMonitor:
    def __init__(
        self,
        bus,
        interval=0.2,
        cpu_spike=30.0,
        ram_spike=20.0,
        gpu_spike=30.0,
    ):
        self.bus = bus
        self.interval = interval
        self.cpu_spike = cpu_spike
        self.ram_spike = ram_spike
        self.gpu_spike = gpu_spike

        self._prev_cpu = psutil.cpu_percent(interval=0)
        self._prev_ram = psutil.virtual_memory().percent
        self._prev_gpu = self._get_gpu_load()

        self._running = False
        self._task = None

    def _get_gpu_load(self):
        try:
            gpus = GPUtil.getGPUs()
            if not gpus:
                return 0.0
            return gpus[0].load * 100
        except Exception:
            return 0.0

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task:
            await self._task

    async def _loop(self):
        while self._running:
            await asyncio.sleep(self.interval)

            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            gpu = self._get_gpu_load()

            events = []

            if cpu - self._prev_cpu > self.cpu_spike:
                events.append("CPU")
            if ram - self._prev_ram > self.ram_spike:
                events.append("RAM")
            if gpu - self._prev_gpu > self.gpu_spike:
                events.append("GPU")

            if events:
                data = {
                    "cpu": cpu,
                    "ram": ram,
                    "gpu": gpu,
                    "events": events,
                }

                await self.bus.publish("big_system_load", data)

            self._prev_cpu = cpu
            self._prev_ram = ram
            self._prev_gpu = gpu

   
