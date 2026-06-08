from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BidderData(Base):
    """Настройки автоматического биддера для объявления.

    Конфигурация автоставок: URL поиска, целевой
    диапазон позиций, границы ставки, шаг, дневной
    бюджет, расписание (битмаска часов + дни недели),
    стартовая ставка, задержка изменения, лимиты по
    метрикам, ставка вне графика, исключение «своих»
    объявлений из выдачи. status = True означает
    активный биддер. log_message хранит последний
    результат работы. deleted_at - момент soft-delete
    биддера из веб-UI: запись со значением IS NOT NULL
    скрыта во всех листинговых и детальных эндпоинтах
    модуля bidder; настройки, заметки и логи позиций
    при этом физически сохраняются.

    Поля critical_min_limit / critical_max_limit задают
    допустимый диапазон значения лимита по объявлению,
    а disabled_bid (в копейках) - ставку, применяемую
    при выключенном продвижении. Все три заполняются
    исключительно внешним server-side биддером: API
    их не принимает, не валидирует и не отдает наружу.
    """

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ad_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ad.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    search_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    position_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_budget: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    min_bid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_bid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    critical_min_bid: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    critical_max_bid: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    critical_min_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    critical_max_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    disabled_bid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_days: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="Пн,Вт,Ср,Чт,Пт,Сб,Вс",
    )
    work_hours_mask: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0xFFFFFF,
    )
    start_bid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offhours_bid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_delay: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    status_change_delay_counter: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    exclude_own_ads: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    disable_impressions_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    disable_views_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    disable_contacts_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    disable_cost_per_view_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    disable_cost_per_contact_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    status: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    log_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )

    __table_args__ = (
        Index("idx_bidder_data_acc_status", "account_id", "status"),
        Index("idx_bidder_data_account_id", "account_id"),
        Index("ix_bidder_data_ad_id_id", "ad_id", "id"),
        Index(
            "ix_bidder_data_status",
            "status",
            postgresql_where=text("status IS TRUE"),
        ),
        Index(
            "ix_bidder_data_deleted_at",
            "deleted_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
