from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.models.base import Base, TimestampMixin


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    username: Mapped[str | None] = mapped_column(String(120), nullable=True)

    orders = relationship("Order", back_populates="customer")

    @property
    def display_name(self) -> str:
        parts = [self.first_name, self.last_name]
        name = " ".join(part for part in parts if part)
        return name or self.username or str(self.telegram_user_id)

