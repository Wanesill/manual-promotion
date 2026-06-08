from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MessageTelegram(Base):
    """Связь сообщения Avito с Telegram.

    Привязывает пересланное в Telegram сообщение
    к исходному сообщению Avito и топику форума.
    message_telegram_id - ID сообщения в Telegram.
    """

    message_telegram_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    message_avito_id: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True
    )
    forum_topic_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("forum_topic.id", ondelete="RESTRICT"),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
