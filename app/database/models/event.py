from sqlalchemy import (
    BigInteger,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column

from app.database import Base


class Event(Base):
    """Событие по объявлению.

    Фиксирует события (event_type) по объявлению
    и дате. Уникальная комбинация: аккаунт +
    объявление + дата.
    """

    account_id = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ad_id = mapped_column(BigInteger, nullable=False)
    date = mapped_column(Date, nullable=False)
    event_type = mapped_column(String(10), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "ad_id",
            "date",
            name="ev_account_ad_date",
        ),
        Index("ix_event_account_date", "account_id", "date"),
        Index(
            "ix_event_account_event_type_date",
            "account_id",
            "event_type",
            "date",
        ),
    )
