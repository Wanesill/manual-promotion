from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChatAccountReport(Base):
    """Привязка чата к автоотчету.

    Junction-таблица: определяет, в какие чаты
    отправлять автоматические отчеты по аккаунту.
    """

    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat.id", ondelete="RESTRICT"), nullable=False
    )
    account_report_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account_report.id", ondelete="RESTRICT"),
        nullable=False,
    )
