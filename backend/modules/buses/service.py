import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List

HEADERS = {"User-Agent": "Mozilla/5.0"}

def to_site_date(date_str: str) -> str:
    """
    YYYY-MM-DD -> DD.MM.YYYY
    """
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")

async def parse_stop_schedule(
    session: aiohttp.ClientSession,
    base_url: str,
    stop_name: str,
    date: str
) -> List[str]:
    """
    Асинхронная версия парсера расписания
    """
    params = {
        "mgt_schedule[date]": to_site_date(date)
    }

    try:
        async with session.get(
            base_url,
            params=params,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            resp.raise_for_status()
            text = await resp.text(encoding="utf-8")

            soup = BeautifulSoup(text, "html.parser")

            stop_div = soup.find(
                "div",
                class_="a_dotted d-inline",
                string=lambda s: s and stop_name in s
            )
            if not stop_div:
                raise ValueError(f"Остановка '{stop_name}' не найдена")

            route_block = stop_div.find_parent("li")
            if not route_block:
                raise ValueError("Контейнер остановки не найден")

            schedule_block = route_block.select_one("div.schedule_list_raspisanie")
            if not schedule_block:
                raise ValueError("Расписание не найдено")

            times = []

            for row in schedule_block.select("div.raspisanie_data"):
                hour = row.select_one("div.dt1 strong")
                if not hour:
                    continue

                hour = hour.text.replace(":", "").strip()

                for m in row.select("div.div10"):
                    minute = m.text.strip()
                    if minute.isdigit():
                        times.append(f"{int(hour):02d}:{int(minute):02d}")

            return times
            
    except Exception as e:
        print(f"Ошибка при парсинге {base_url}: {e}")
        return []

async def func(
    session: aiohttp.ClientSession,
    base_url: str,
    stop_name: str,
    date: str
) -> List[str]:
    """
    Обертка для асинхронного вызова парсера
    """
    return await parse_stop_schedule(session, base_url, stop_name, date)

async def main():
    """
    Основная асинхронная функция
    """
    urls = [
        "https://transport.mos.ru/transport/schedule/route/141509584", 
        "https://transport.mos.ru/transport/schedule/route/141509583"
    ]
    stop_names = ["Улица Марьинский Парк", "Улица Марьинский Парк"]
    date = "2026-01-18"

    # Создаем сессию для всех запросов
    async with aiohttp.ClientSession() as session:
        # Создаем список задач для параллельного выполнения
        tasks = []
        for i in range(len(urls)):
            task = func(session, urls[i], stop_names[i], date)
            tasks.append(task)
        
        # Выполняем все задачи параллельно
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Обрабатываем результаты
        for i, result in enumerate(results):
            print(f"Результат {i+1} ({urls[i]}):")
            if isinstance(result, Exception):
                print(f"  Ошибка: {result}")
            else:
                print(f"  Время прибытия: {result}")



if __name__ == "__main__":
    # Для параллельного выполнения запросов (быстрее)
    asyncio.run(main())
    
    # Или для последовательного выполнения
    # asyncio.run(main_sequential())