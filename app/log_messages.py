"""Русские константы log_message и системных заметок.

Все сообщения end-user-видимые, формат фиксирован и используется
также в API-сервисе (`docs/api/manual_promotion/service.py`) для
определения status_code (success/stopped/error). Не переводить
без продуктовой причины.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "DISABLED_EVENTS",
    "LOG_BID_ABOVE_MAX_PREFIX",
    "LOG_BID_BELOW_MIN",
    "LOG_BID_CHANGE_FAILED",
    "LOG_DISABLED_BY_ACCOUNT_BALANCE",
    "LOG_DISABLED_BY_ACCOUNT_DELETED",
    "LOG_DISABLED_BY_AUTH_FAILED",
    "LOG_DISABLED_BY_BUDGET",
    "LOG_DISABLED_BY_CONTACTS",
    "LOG_DISABLED_BY_CPC",
    "LOG_DISABLED_BY_CPV",
    "LOG_DISABLED_BY_IMPRESSIONS",
    "LOG_DISABLED_BY_TARIFF",
    "LOG_DISABLED_BY_TIME",
    "LOG_DISABLED_BY_TOKEN_EXPIRED",
    "LOG_DISABLED_BY_VIEWS",
    "LOG_LIMIT_EXCEEDED",
    "LOG_NOT_CONFIGURED",
    "LOG_PROMOTION_DISABLED",
    "LOG_PROMOTION_RESUMED",
    "LOG_PROMOTION_UNAVAILABLE",
    "LOG_SUCCESS",
    "LOG_USER_DELETED",
    "NOTE_KIND_SYSTEM",
    "SOFT_DISABLED_LOGS",
    "format_bid_above_max",
]

# Успех.
LOG_SUCCESS: Final[str] = "Успешно"

# Плановые остановки.
LOG_PROMOTION_DISABLED: Final[str] = "Продвижение выключено"
LOG_DISABLED_BY_BUDGET: Final[str] = "Отключено по бюджету"
LOG_DISABLED_BY_TIME: Final[str] = "Отключено по времени"
LOG_DISABLED_BY_IMPRESSIONS: Final[str] = "Отключено по показам"
LOG_DISABLED_BY_VIEWS: Final[str] = "Отключено по просмотрам"
LOG_DISABLED_BY_CONTACTS: Final[str] = "Отключено по контактам"
LOG_DISABLED_BY_CPV: Final[str] = "Отключено по стоимости просмотра"
LOG_DISABLED_BY_CPC: Final[str] = "Отключено по стоимости контакта"
LOG_USER_DELETED: Final[str] = "Снято с ручного продвижения"

# Возобновление после disable (для системной заметки).
LOG_PROMOTION_RESUMED: Final[str] = "Продвижение возобновлено"

# Ошибки и блокирующие условия.
LOG_NOT_CONFIGURED: Final[str] = "Не настроено ручное продвижение"
LOG_BID_BELOW_MIN: Final[str] = "Ставка должна быть больше минимального значения"
LOG_BID_ABOVE_MAX_PREFIX: Final[str] = (
    "Ставка должна быть меньше максимального значения"
)
LOG_DISABLED_BY_TARIFF: Final[str] = "Тариф закончился"
LOG_LIMIT_EXCEEDED: Final[str] = "Превышен лимит по подключенным объявлениям"
LOG_DISABLED_BY_ACCOUNT_DELETED: Final[str] = "Аккаунт удален"
LOG_DISABLED_BY_TOKEN_EXPIRED: Final[str] = "Токен аккаунта истек"
LOG_DISABLED_BY_AUTH_FAILED: Final[str] = "Не удалось авторизовать аккаунт"
LOG_DISABLED_BY_ACCOUNT_BALANCE: Final[str] = "Закончился аванс"
LOG_PROMOTION_UNAVAILABLE: Final[str] = "Продвижение за ставку недоступно"
LOG_BID_CHANGE_FAILED: Final[str] = "Не удалось изменить ставку"

# Вид системной заметки в ManualPromotionNote.
NOTE_KIND_SYSTEM: Final[str] = "system"


def format_bid_above_max(critical_max_bid_penny: int) -> str:
    """Форматирует сообщение `Ставка должна быть меньше …` с суммой в ₽."""
    rub = critical_max_bid_penny // 100
    return f"{LOG_BID_ABOVE_MAX_PREFIX}: {rub}"


# События мягкого отключения — для них пишем системную заметку
# при первом срабатывании и проверяем переход на возобновление.
SOFT_DISABLED_LOGS: Final[frozenset[str]] = frozenset(
    {
        LOG_DISABLED_BY_TIME,
        LOG_DISABLED_BY_BUDGET,
        LOG_DISABLED_BY_IMPRESSIONS,
        LOG_DISABLED_BY_VIEWS,
        LOG_DISABLED_BY_CONTACTS,
        LOG_DISABLED_BY_CPV,
        LOG_DISABLED_BY_CPC,
    }
)

# Все возможные «выключающие» события, после которых переход
# на LOG_SUCCESS требует заметки о возобновлении.
DISABLED_EVENTS: Final[frozenset[str]] = SOFT_DISABLED_LOGS | frozenset(
    {
        LOG_DISABLED_BY_TARIFF,
        LOG_LIMIT_EXCEEDED,
        LOG_PROMOTION_UNAVAILABLE,
        LOG_DISABLED_BY_ACCOUNT_DELETED,
        LOG_DISABLED_BY_TOKEN_EXPIRED,
        LOG_DISABLED_BY_AUTH_FAILED,
        LOG_DISABLED_BY_ACCOUNT_BALANCE,
        LOG_BID_CHANGE_FAILED,
        LOG_BID_BELOW_MIN,
    }
)
