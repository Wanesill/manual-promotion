from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MailingMessageLog(Base):
    """Лог отправки сообщения рассылки.

    Фиксирует факт доставки конкретного сообщения
    конкретному профилю: ID сообщения в мессенджере
    и время отправки. Платформа определяется через
    mailing_message.mailing_id -> mailing.platform.
    """

    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=False,
    )
    mailing_message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("mailing_message.id", ondelete="RESTRICT"),
        nullable=False,
    )
    message_platform_id: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
