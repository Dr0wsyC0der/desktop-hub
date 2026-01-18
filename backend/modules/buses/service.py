import aiohttp
import asyncio
import json
from pathlib import Path
from datetime import date, timedelta, datetime
from backend.parsers.bus_shedule_parser import TransportScheduleParser


class BusService:
    SCHEDULE_PATH = Path("backend/storage/schedule.json")
    SETTINGS_PATH = Path("backend/storage/settings.json")

    def __init__(self):
        self.settings = self._load_settings()
        self.parser = TransportScheduleParser()

    async def update_cache(self):
        today = date.today().isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        async with aiohttp.ClientSession(
            headers=self.parser.HEADERS
        ) as session:

            tasks = []
            meta = []  # <-- ЧТО именно мы парсим

            for stop in self.settings["bus_settings"]["stops"]:
                url = stop["url"]
                name = stop["stop_name"]

                tasks.append(self.parser.parse_stop(session, url, name, today))
                meta.append(("today", url, name))

                tasks.append(self.parser.parse_stop(session, url, name, tomorrow))
                meta.append(("tomorrow", url, name))

            results = await asyncio.gather(*tasks)

        schedule = self._build_schedule(results, meta)
        self.save_schedule(schedule)

    def _build_schedule(self, results, meta):
        schedule = {
            "today": [],
            "tomorrow": []
        }

        for (day, url, name), times in zip(meta, results):
            schedule[day].append({
                "url": url,
                "stop_name": name,
                "times": times
            })

        return schedule

    def _load_settings(self) -> dict:
        if not self.SETTINGS_PATH.exists():
            raise FileNotFoundError("settings.json not found")

        with open(self.SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_schedule(self, data: dict):
        self.SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self.SCHEDULE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_nearest_bus(self):
        if not self.SCHEDULE_PATH.exists():
            return None

        now = datetime.now()
        today = date.today()

        with open(self.SCHEDULE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        nearest = None

        for stop in data.get("today", []):
            for bus_time in stop.get("times", []):
                bus_dt = datetime.strptime(
                    f"{today} {bus_time}:00",
                    "%Y-%m-%d %H:%M:%S"
                )

                if bus_dt >= now:
                    if nearest is None or bus_dt < nearest["datetime"]:
                        nearest = {
                            "stop_name": stop["stop_name"],
                            "time": bus_time,
                            "datetime": bus_dt
                        }

        if nearest:
            nearest.pop("datetime")
            return nearest

        return None
