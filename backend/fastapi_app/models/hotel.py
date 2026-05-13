from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.models.base import Base, TimestampMixin


class Hotel(TimestampMixin, Base):
    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True, nullable=False)
    telegram_label: Mapped[str | None] = mapped_column(String(180), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    menu_items = relationship("MenuItem", back_populates="hotel", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="hotel")
    sessions = relationship("UserSession", back_populates="hotel")

