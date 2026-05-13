from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.models.base import Base, TimestampMixin


class OrderStatus(StrEnum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="RESTRICT"), index=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default=OrderStatus.NEW.value)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    pickup_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    customer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="telegram")

    hotel = relationship("Hotel", back_populates="orders")
    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id", ondelete="RESTRICT"), index=True, nullable=False)
    item_name_snapshot: Mapped[str] = mapped_column(String(180), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem", back_populates="order_items")
