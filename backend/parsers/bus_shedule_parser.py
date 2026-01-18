import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List

class TransportScheduleParser:
    HEADERS = {"User-Agent": "Mozilla/5.0"}

    @staticmethod
    def to_site_date(date_str: str) -> str:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")

    async def parse_stop(
        self,
        session: aiohttp.ClientSession,
        url: str,
        stop_name: str,
        date: str
    ) -> List[str]:

        params = {
            "mgt_schedule[date]": self.to_site_date(date)
        }

        try:
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                html = await resp.text(encoding="utf-8")

            soup = BeautifulSoup(html, "html.parser")

            stop_div = soup.find(
                "div",
                class_="a_dotted d-inline",
                string=lambda s: s and stop_name in s
            )
            if not stop_div:
                raise ValueError(f"Остановка '{stop_name}' не найдена")

            route_block = stop_div.find_parent("li")
            schedule_block = route_block.select_one(
                "div.schedule_list_raspisanie"
            )
            if not schedule_block:
                raise ValueError("Расписание не найдено")

            times = []

            for row in schedule_block.select("div.raspisanie_data"):
                hour_tag = row.select_one("div.dt1 strong")
                if not hour_tag:
                    continue

                hour = hour_tag.text.replace(":", "").strip()

                for m in row.select("div.div10"):
                    minute = m.text.strip()
                    if minute.isdigit():
                        times.append(f"{int(hour):02d}:{int(minute):02d}")

            return times

        except Exception as e:
            print(f"Ошибка [{url}]: {e}")
            return []
