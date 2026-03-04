import asyncio
import json
import socket
from typing import Awaitable, Callable, Optional

import websockets

from backend.core.network import resolve_local_ip, wait_for_internet


MessageHandler = Callable[[str], Awaitable[None]]
ConnectHandler = Callable[[], Awaitable[None]]


class ESPConnection:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        *,
        udp_port: int = 45678,
        udp_interval_sec: float = 1.5,
        ws_ping_interval_sec: float = 10.0,
        ws_ping_timeout_sec: float = 10.0,
    ):
        self.host = host
        self.port = int(port)
        self.udp_port = int(udp_port)
        self.udp_interval_sec = float(max(0.5, udp_interval_sec))
        self.ws_ping_interval_sec = float(max(3.0, ws_ping_interval_sec))
        self.ws_ping_timeout_sec = float(max(3.0, ws_ping_timeout_sec))

        self.clients = set()
        self._on_message: Optional[MessageHandler] = None
        self._on_connect: Optional[ConnectHandler] = None
        self._udp_socket: Optional[socket.socket] = None
        self._udp_task: Optional[asyncio.Task] = None

    async def start(
        self,
        on_message: Optional[MessageHandler] = None,
        on_connect: Optional[ConnectHandler] = None,
    ):
        """
        Start websocket server.

        :param on_message: async callback which will be called for every
                          incoming text message from ESP.
        """
        self._on_message = on_message
        self._on_connect = on_connect
        await wait_for_internet()

        self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._udp_socket.setblocking(False)

        async def handler(ws):
            self.clients.add(ws)
            print("ESP connected")
            if self._on_connect is not None:
                try:
                    await self._on_connect()
                except Exception as e:
                    print("Error in ESP on_connect handler:", e)

            await ws.send(
                json.dumps(
                    {
                        "type": "get_schedule_data",
                    },
                    ensure_ascii=False,
                )
            )

            try:
                async for msg in ws:
                    print("ESP -> PC:", msg)
                    if self._on_message is not None:
                        try:
                            await self._on_message(msg)
                        except Exception as e:
                            print("Error in ESP on_message handler:", e)
            except websockets.exceptions.ConnectionClosed as e:
                code = getattr(e, "code", None)
                reason = getattr(e, "reason", "")
                print(f"ESP websocket closed: code={code}, reason={reason or 'no close reason'}")
            finally:
                self.clients.discard(ws)
                print("ESP disconnected")

        self.server = await websockets.serve(
            handler,
            self.host,
            self.port,
            ping_interval=self.ws_ping_interval_sec,
            ping_timeout=self.ws_ping_timeout_sec,
        )
        print(f"WS server listening on {self.host}:{self.port}")

        self._udp_task = asyncio.create_task(self._udp_announce_loop())

    async def _udp_announce_loop(self):
        while True:
            await asyncio.sleep(self.udp_interval_sec)
            if self.clients:
                # ESP already connected via WS: no discovery broadcasts needed.
                continue
            if self._udp_socket is None:
                continue

            payload = {
                "type": "ws_discovery",
                "ip": resolve_local_ip(),
                "port": self.port,
            }
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            try:
                self._udp_socket.sendto(raw, ("255.255.255.255", self.udp_port))
            except Exception as e:
                print("UDP discovery send failed:", e)

    async def broadcast_json(self, data: dict):
        if not self.clients:
            return

        message = json.dumps(data, ensure_ascii=False)
        await asyncio.gather(*[ws.send(message) for ws in self.clients])

    async def broadcast_bytes(self, data: bytes):
        if not self.clients:
            return
        await asyncio.gather(*[ws.send(data) for ws in self.clients])

    async def broadcast(self, data: dict):
        # Backward-compatible alias used across the existing codebase.
        await self.broadcast_json(data)
