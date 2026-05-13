from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from fastapi_app.core.security import require_backend_api_key, require_dashboard_token, require_order_write_access
from fastapi_app.db.session import get_db
from fastapi_app.models.order import Order
from fastapi_app.schemas.order import OrderCreate, OrderOut, OrderStatusUpdate
from fastapi_app.services.order_service import (
    create_order,
    list_orders,
    serialize_order,
    status_message,
    update_order_status,
)
from fastapi_app.services.telegram_service import TelegramClient
from fastapi_app.websocket.manager import manager

router = APIRouter()


@router.get("", response_model=list[OrderOut], dependencies=[Depends(require_dashboard_token)])
def get_orders(
    hotel_id: int | None = Query(default=None, gt=0),
    status: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
) -> list[Order]:
    return list_orders(db, hotel_id=hotel_id, order_status=status)


@router.post("", response_model=OrderOut, dependencies=[Depends(require_backend_api_key)])
async def create_order_endpoint(payload: OrderCreate, db: Session = Depends(get_db)) -> Order:
    order = create_order(db, payload)
    await manager.broadcast_to_hotel(order.hotel_id, {"type": "order.created", "order": serialize_order(order)})
    return order


@router.patch("/{order_id}/status", response_model=OrderOut, dependencies=[Depends(require_order_write_access)])
async def update_status_endpoint(
    order_id: int,
    payload: OrderStatusUpdate,
    db: Session = Depends(get_db),
) -> Order:
    order = update_order_status(db, order_id, payload.status)
    serialized = serialize_order(order)
    await manager.broadcast_to_hotel(order.hotel_id, {"type": "order.status_changed", "order": serialized})
    await TelegramClient().send_message(order.customer.telegram_chat_id, status_message(order))
    return order

