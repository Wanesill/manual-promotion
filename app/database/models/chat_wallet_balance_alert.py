from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChatWalletBalanceAlert(Base):
    """Привязка чата к уведомлению о балансе кошелька.

    Junction-таблица: определяет, в какие чаты
    отправлять алерты о балансе кошелька.
    """

    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat.id", ondelete="RESTRICT"), nullable=False
    )
    wallet_balance_alert_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("wallet_balance_alert.id", ondelete="RESTRICT"),
        nullable=False,
    )
