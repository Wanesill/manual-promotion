from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    desc,
)
from sqlalchemy.orm import mapped_column

from app.database import Base


class AdStatistic(Base):
    """Статистика коммуникаций по объявлению.

    Звонки, чаты, отзывы, скидки и параметры
    продвижения (ставка, бюджет, период) по
    временным меткам для конкретного объявления.
    """

    account_id = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ad_id = mapped_column(
        BigInteger, ForeignKey("ad.id", ondelete="RESTRICT"), nullable=False
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
    reviews = mapped_column(Integer, nullable=False)
    count_discounts = mapped_column(Integer, nullable=False)
    accepted_discounts = mapped_column(Integer, nullable=False)
    acquainted_discounts = mapped_column(Integer, nullable=False)
    actual_manual_rate = mapped_column(Float, nullable=False)
    actual_auto_budget = mapped_column(Integer, nullable=False)
    actual_auto_period = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index(
            "ix_ad_statistic_acc_id_ts",
            "account_id",
            desc("timestamp"),
        ),
        Index(
            "ix_ad_statistic_ad_id_ts_desc",
            "ad_id",
            desc("timestamp"),
        ),
    )
