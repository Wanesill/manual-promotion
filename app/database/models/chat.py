from sqlalchemy import BigInteger, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Chat(Base):
    """Чат пользователя в мессенджере.

    Telegram-группа или Max-чат, привязанный к
    профилю. Используется для отправки уведомлений,
    отчетов и пересылки сообщений Avito.
    platform: telegram или max.
    """

    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=False,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    platform: Mapped[str] = mapped_column(
        String(10), nullable=False, default="telegram"
    )

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "chat_id",
            "platform",
            name="ch_profile_chat_platform",
        ),
        Index("ix_chat_chat_id", "chat_id"),
    )
