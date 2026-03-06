import asyncio
from collections import defaultdict

class EventBus:
    def __init__(self):
        self._subscribers = defaultdict(list)

    def subscribe(self, event_type: str, callback):
        """
        callback: async function(event)
        """
        self._subscribers[event_type].append(callback)

    async def publish(self, event_type: str, event: dict):
        if event_type not in self._subscribers:
            return

        for callback in self._subscribers[event_type]:
            try:
                await callback(event)
            except Exception as e:
                print(f"EventBus error: {e}")   