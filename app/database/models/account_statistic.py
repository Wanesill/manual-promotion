from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    desc,
)
from sqlalchemy.orm import mapped_column

from app.database import Base


class AccountStatistic(Base):
    """Статистика звонков и чатов аккаунта.

    Агрегированные показатели коммуникаций аккаунта
    по временным меткам: звонки, чаты, среднее время
    ответа и длительность разговоров.
    """

    account_id = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    timestamp = mapped_column(DateTime, nullable=False)
    calls = mapped_column(Integer, nullable=False)
    calls_answered = mapped_column(Integer, nullable=False)
    avg_talk_duration = mapped_column(Float, nullable=False)
    avg_waiting_duration = mapped_column(Float, nullable=False)
    chats = mapped_column(Integer, nullable=False)
    avg_first_response_time = mapped_column(Float, nullable=False)
    avg_response_time = mapped_column(Float, nullable=False)
    avg_messages_per_chat = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "timestamp", name="as_account_timestamp"
        ),
        Index(
            "ix_account_statistic_acc_id_ts",
            "account_id",
            desc("timestamp"),
        ),
    )
