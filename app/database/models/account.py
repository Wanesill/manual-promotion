from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Account(Base):
    """Аккаунт Avito пользователя.

    Подключается по API-ключам или OAuth. Три
    статуса: active (работает), expired (ключи/токен
    невалидны - переподключение сохраняет настройки),
    deleted (мягкое удаление с каскадной очисткой).

    display_name возвращает custom_name или name.
    """

    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=False,
    )
    connect_date: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    custom_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    account_url: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, unique=True, index=True
    )
    email: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    client_secret: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    access_token: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    refresh_token: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    expires_in: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(7), nullable=False
    )  # ["active", "expired", "deleted"]
    analytics_status: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (Index("idx_account_profile_id", "profile_id"),)

    @property
    def display_name(self) -> str:
        return self.custom_name or self.name
