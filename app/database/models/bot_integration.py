from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BotIntegration(Base):
    """Интеграция профиля с ботом мессенджера.

    Хранит привязку пользователя к боту (Telegram, Max,
    в будущем VK). Один профиль может иметь по одной
    интеграции на каждую платформу.

    bot_user_id = NULL означает pending-привязку
    (токен сгенерирован, бот еще не завершил линковку).
    """

    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(10), nullable=False)
    bot_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bot_username: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    link_token: Mapped[str | None] = mapped_column(String(44), nullable=True)
    is_blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    __table_args__ = (
        UniqueConstraint(
            "platform",
            "bot_user_id",
            name="uq_bot_integration_platform_user",
        ),
        UniqueConstraint(
            "profile_id",
            "platform",
            name="uq_bot_integration_profile_platform",
        ),
        UniqueConstraint(
            "platform",
            "link_token",
            name="uq_bot_integration_platform_token",
        ),
        Index(
            "ix_bot_integration_platform_token",
            "platform",
            "link_token",
        ),
    )
