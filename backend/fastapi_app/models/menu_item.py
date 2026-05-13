from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.models.base import Base, TimestampMixin


class MenuItem(TimestampMixin, Base):
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    hotel = relationship("Hotel", back_populates="menu_items")
    order_items = relationship("OrderItem", back_populates="menu_item")

