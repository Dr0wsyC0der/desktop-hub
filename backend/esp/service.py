import asyncio
import json
from datetime import date, datetime
from typing import Optional

import GPUtil
import psutil

from .connection import ESPConnection
from ..models.esp.commands import ESPCommand
from ..core.alive_services import AppContext


class ESPService:
    def __init__(self, bus):
        self.bus = bus
        self.conn = ESPConnection()

        # Параметры мониторинга нагрузки ПК
        self._pc_load_interval: float = 0.5
        self._pc_load_task: Optional[asyncio.Task] = None
        self._pc_load_running: bool = False

    async def start(self):
        # Передаём обработчик входящих сообщений в соединение
        await self.conn.start(self.on_message)

        self.bus.subscribe("volume_changed", self.on_volume)
        self.bus.subscribe("track_changed", self.on_track)
        self.bus.subscribe("big_system_load", self.on_load)

    async def on_message(self, raw_msg: str):
        """
        Обработка входящих WS-сообщений от ESP.

        Ожидаем, в том числе:
        {"type": "pc_load", "action": "start"}
        {"type": "pc_load", "action": "stop"}
        {"type": "schedule_date", "date": "2026-02-12"}
        """
        try:
            data = json.loads(raw_msg)
        except json.JSONDecodeError:
            # Игнорируем не-JSON сообщения
            return

        msg_type = data.get("type")
        action = data.get("action")

        if msg_type == "pc_load":
            if action == "start":
                await self._start_pc_load()
            elif action == "stop":
                await self._stop_pc_load()
        elif msg_type == "schedule_date":
            await self._handle_schedule_date(data)

    async def _handle_schedule_date(self, data: dict):
        """
        Обработка ответа вида:
        {"type": "schedule_date", "date": "YYYY-MM-DD"}

        - если дата сегодняшняя — расписание НЕ отправляем
        - если дата вчерашняя или более старая — отправляем актуальное расписание
        - если дата невалидна/пустая — считаем расписание устаревшим и отправляем
        """
        raw_date = data.get("date")

        need_send = True
        if isinstance(raw_date, str) and raw_date:
            try:
                schedule_dt = datetime.fromisoformat(raw_date).date()
                today = date.today()
                # если дата раньше сегодняшней — нужно отправить новое расписание
                # если дата сегодня или в будущем — НЕ отправляем
                need_send = schedule_dt < today
            except ValueError:
                # не смогли распарсить дату — на всякий случай отправим расписание
                need_send = True

        if not need_send:
            print("Schedule on ESP is up-to-date, skip sending")
            return

        schedule_path = AppContext.bus_service.SCHEDULE_PATH
        if not schedule_path.exists():
            print("Schedule file not found, nothing to send")
            return

        try:
            with open(schedule_path, "r", encoding="utf-8") as f:
                schedule_data = json.load(f)
        except Exception as e:
            print("Failed to read schedule file:", e)
            return

        await self.send("schedule", schedule_data)

    async def _start_pc_load(self):
        if self._pc_load_running:
            return
        self._pc_load_running = True
        self._pc_load_task = asyncio.create_task(self._pc_load_loop())
        print("PC load monitoring started")

    async def _stop_pc_load(self):
        self._pc_load_running = False
        if self._pc_load_task:
            await self._pc_load_task
            self._pc_load_task = None
        print("PC load monitoring stopped")

    async def _pc_load_loop(self):
        while self._pc_load_running:
            await asyncio.sleep(self._pc_load_interval)

            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            gpu = self._get_gpu_load()

            await self._send_pc_load(cpu, gpu, ram)

    def _get_gpu_load(self) -> float:
        try:
            gpus = GPUtil.getGPUs()
            if not gpus:
                return 0.0
            return gpus[0].load * 100
        except Exception:
            return 0.0

    async def _send_pc_load(self, cpu: float, gpu: float, ram: float):
        """
        Отправка текущей нагрузки ПК в формате:
        {
          "type": "pc_load",
          "cpu": ...,
          "gpu": ...,
          "ram": ...
        }
        """
        await self.conn.broadcast({
            "type": "pc_load",
            "cpu": cpu,
            "gpu": gpu,
            "ram": ram,
        })

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

