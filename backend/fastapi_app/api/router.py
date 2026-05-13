from fastapi import APIRouter

from fastapi_app.api.routes import ai, hotels, menu, orders, telegram, websocket

api_router = APIRouter()
api_router.include_router(hotels.router, prefix="/hotels", tags=["hotels"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(menu.router, prefix="/menu", tags=["menu"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(telegram.router, prefix="/telegram", tags=["telegram"])
api_router.include_router(websocket.router, tags=["websocket"])

