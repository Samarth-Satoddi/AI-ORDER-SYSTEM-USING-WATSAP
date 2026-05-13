from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from fastapi_app.models.order import OrderStatus


class OrderItemCreate(BaseModel):
    menu_item_id: int
    quantity: int = Field(..., ge=1, le=99)


class OrderCreate(BaseModel):
    hotel_id: int
    customer_id: int
    items: list[OrderItemCreate]
    pickup_time: datetime | None = None
    customer_note: str | None = Field(default=None, max_length=1000)


class CustomerOut(BaseModel):
    id: int
    telegram_user_id: int
    telegram_chat_id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    display_name: str

    model_config = ConfigDict(from_attributes=True)


class OrderItemOut(BaseModel):
    id: int
    menu_item_id: int
    item_name_snapshot: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal

    model_config = ConfigDict(from_attributes=True)


class OrderOut(BaseModel):
    id: int
    hotel_id: int
    customer_id: int
    status: str
    total_amount: Decimal
    pickup_time: datetime | None = None
    customer_note: str | None = None
    source: str
    created_at: datetime
    updated_at: datetime
    customer: CustomerOut
    items: list[OrderItemOut]

    model_config = ConfigDict(from_attributes=True)


class OrderStatusUpdate(BaseModel):
    status: OrderStatus

