import asyncio
import json
import websockets

class ESPConnection:
    def __init__(self, host="0.0.0.0", port=8765):
        self.host = host
        self.port = port
        self.clients = set()

    async def start(self):
        async def handler(ws):
            self.clients.add(ws)
            try:
                async for msg in ws:
                    print("ESP → PC:", msg)
            finally:
                self.clients.remove(ws)


        self.server = await websockets.serve(handler, self.host, self.port)

    async def broadcast(self, data: dict):
        if not self.clients:
            return

        message = json.dumps(data, ensure_ascii=False)
        await asyncio.gather(
            *[ws.send(message) for ws in self.clients]
        )
