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


class AccountStateHistory(Base):
    """История состояния аккаунта Avito.

    Снимки отзывов, рейтинга и балансов аккаунта
    по временным меткам. Используется для отслеживания
    динамики показателей аккаунта.
    """

    account_id = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    timestamp = mapped_column(DateTime, nullable=False)
    reviews = mapped_column(Integer, nullable=False)
    rating_score = mapped_column(Float, nullable=False)
    balance = mapped_column(Float, nullable=True)
    advance_balance = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "timestamp", name="ash_account_timestamp"
        ),
        Index(
            "ix_account_state_history_acc_id_ts_desc",
            "account_id",
            desc("timestamp"),
        ),
    )
