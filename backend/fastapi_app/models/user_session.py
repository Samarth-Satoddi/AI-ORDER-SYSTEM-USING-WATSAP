from sqlalchemy import BigInteger, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.models.base import Base, TimestampMixin


class UserSession(TimestampMixin, Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    hotel_id: Mapped[int | None] = mapped_column(ForeignKey("hotels.id", ondelete="SET NULL"), nullable=True)
    state: Mapped[str] = mapped_column(String(64), nullable=False, default="START")
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    hotel = relationship("Hotel", back_populates="sessions")

