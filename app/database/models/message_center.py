from sqlalchemy import BigInteger, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MessageCenter(Base):
    """Настройки Message Center для аккаунта.

    Управляет вебхуком Avito для пересылки сообщений
    в Telegram-группу. status = True означает активный
    вебхук. Требует привязку Telegram (не Max).
    """

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chat.id", ondelete="RESTRICT"), nullable=True
    )
