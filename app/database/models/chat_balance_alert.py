from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChatBalanceAlert(Base):
    """Привязка чата к уведомлению о балансе.

    Junction-таблица: определяет, в какие чаты
    отправлять алерты о балансе аккаунта.
    """

    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat.id", ondelete="RESTRICT"), nullable=False
    )
    balance_alert_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("balance_alert.id", ondelete="RESTRICT"),
        nullable=False,
    )
