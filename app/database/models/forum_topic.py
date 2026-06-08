from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ForumTopic(Base):
    """Топик форума в Telegram-группе.

    Каждый чат Avito (ChatAvito) получает отдельный
    топик в Telegram-группе (Chat) для пересылки
    сообщений. message_thread_id - идентификатор
    топика в Telegram.
    """

    account_id = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chat.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    chat_avito_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chat_avito.id", ondelete="RESTRICT"),
        nullable=False,
    )
    message_thread_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "chat_id", "chat_avito_id", name="uq_forum_topic_chat_chatavito"
        ),
        Index("ix_forum_topic_chat_thread", "chat_id", "message_thread_id"),
    )
