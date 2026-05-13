import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, hotel_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[hotel_id].add(websocket)

    async def disconnect(self, hotel_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(hotel_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(hotel_id, None)

    async def broadcast_to_hotel(self, hotel_id: int, payload: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._connections.get(hotel_id, set()))

        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)

        if stale:
            async with self._lock:
                for websocket in stale:
                    self._connections.get(hotel_id, set()).discard(websocket)


manager = ConnectionManager()
