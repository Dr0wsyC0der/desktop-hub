import asyncio
import json
from typing import Awaitable, Callable, Optional

import websockets


MessageHandler = Callable[[str], Awaitable[None]]


class ESPConnection:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.clients = set()
        self._on_message: Optional[MessageHandler] = None

    async def start(self, on_message: Optional[MessageHandler] = None):
        """
        Start websocket server.

        :param on_message: async callback which will be called for every
                          incoming text message from ESP.
        """
        self._on_message = on_message

        async def handler(ws):
            self.clients.add(ws)
            print("ESP connected")

            # При новом подключении просим у ESP дату актуального расписания
            await ws.send(json.dumps({
                "type": "get_schedule_data"
            }, ensure_ascii=False))

            try:
                async for msg in ws:
                    print("ESP → PC:", msg)
                    if self._on_message is not None:
                        try:
                            await self._on_message(msg)
                        except Exception as e:
                            # Do not break connection on handler errors
                            print("Error in ESP on_message handler:", e)
            finally:
                self.clients.remove(ws)
                print("ESP disconnected")

        self.server = await websockets.serve(handler, self.host, self.port)

    async def broadcast(self, data: dict):
        if not self.clients:
            return

        message = json.dumps(data, ensure_ascii=False)
        await asyncio.gather(
            *[ws.send(message) for ws in self.clients]
        )

