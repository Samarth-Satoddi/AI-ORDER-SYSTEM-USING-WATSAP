from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from fastapi_app.core.config import get_settings
from fastapi_app.websocket.manager import manager

router = APIRouter()


@router.websocket("/ws/hotels/{hotel_id}/orders")
async def hotel_orders_websocket(websocket: WebSocket, hotel_id: int, token: str | None = None) -> None:
    settings = get_settings()
    if not settings.dashboard_token or token != settings.dashboard_token:
        await websocket.close(code=1008)
        return

    await manager.connect(hotel_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(hotel_id, websocket)

