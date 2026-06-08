from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WebSession(Base):
    """Сессия веб-авторизации.

    Хранит хеш refresh-токена (SHA-256), срок действия
    и метаданные клиента. Один профиль может иметь
    несколько активных сессий. Токен ротируется
    при каждом обновлении.
    """

    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
