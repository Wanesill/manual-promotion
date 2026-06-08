"""Парсинг ответа Avito get_bids в границы для нашего decision engine.

Сырая структура ответа `/cpxpromo/1/getBids/{ad_id}` (см. docstring
`AvitoService.get_bids`):
    {
        "actionTypeID": int,
        "message": str | absent,
        "manual": {
            "bidPenny": int,
            "limitPenny": int,
            "minBidPenny": int,
            "maxBidPenny": int,
            "minLimitPenny": int,
            "maxLimitPenny": int,
            "recBidPenny": int,
            "bids": [{"compare": int, "valuePenny": int, ...}, ...],
        },
    }

`parse_critical_bids` возвращает None если CPxPromo на ad **недоступен**:
- ответ — не dict;
- есть поле `message` (Avito так сигнализирует «продвижение
  недоступно» / ошибку);
- `actionTypeID` отличается от `MANUAL_PROMOTION_ACTION_TYPE_ID`;
- блок `manual` отсутствует или не dict;
- `minBidPenny` / `maxBidPenny` отсутствуют либо не int.
Caller интерпретирует None как `LOG_PROMOTION_UNAVAILABLE`.

К границам применяется safety-margin (`CRITICAL_*_SAFETY_MARGIN_PENNY`),
чтобы не оказаться ровно на платформенной границе:
- нижним (`critical_min_bid` fallback, `critical_min_limit`) +margin;
- верхним (`critical_max_bid`, `critical_max_limit`) −margin.
Если у объявления есть реальный `bids[]` с `compare > 0`, `critical_min_bid`
берём из первого такого элемента (а не из `minBidPenny + margin`).

`pick_compare_percent` возвращает процент опережения для нашей ставки:
ищем сегмент [valuePenny_i; valuePenny_{i+1}) включающий bid и берём
compare i-го элемента. Граничные случаи: ниже самой малой ставки —
compare первой; выше самой большой — compare последней; нет данных — 0.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.external_services.avito_service import MANUAL_PROMOTION_ACTION_TYPE_ID

__all__ = [
    "CRITICAL_MAX_SAFETY_MARGIN_PENNY",
    "CRITICAL_MIN_SAFETY_MARGIN_PENNY",
    "CriticalBidsData",
    "parse_critical_bids",
    "pick_compare_percent",
]

# 1 рубль = 100 копеек. Отступ от платформенной границы, чтобы не быть на
# самой кромке (избегаем 400 от Avito на пограничных значениях).
CRITICAL_MIN_SAFETY_MARGIN_PENNY: int = 100
CRITICAL_MAX_SAFETY_MARGIN_PENNY: int = 100


@dataclass(frozen=True)
class CriticalBidsData:
    critical_min_bid: int
    critical_max_bid: int
    critical_min_limit: int
    critical_max_limit: int
    disabled_bid: int


def parse_critical_bids(bids_info: dict | None) -> CriticalBidsData | None:
    """Извлекает границы из get_bids; None — CPxPromo недоступен."""
    if not isinstance(bids_info, dict):
        return None
    if bids_info.get("message"):
        return None
    if bids_info.get("actionTypeID") != MANUAL_PROMOTION_ACTION_TYPE_ID:
        return None

    manual = bids_info.get("manual")
    if not isinstance(manual, dict):
        return None

    min_bid = manual.get("minBidPenny")
    max_bid = manual.get("maxBidPenny")
    if not isinstance(min_bid, int) or not isinstance(max_bid, int):
        return None

    bids_array = manual.get("bids") or []
    first_non_zero = next(
        (
            b
            for b in bids_array
            if isinstance(b, dict)
            and isinstance(b.get("compare"), int)
            and b["compare"] > 0
            and isinstance(b.get("valuePenny"), int)
        ),
        None,
    )
    if first_non_zero is not None:
        critical_min_bid = int(first_non_zero["valuePenny"])
    else:
        critical_min_bid = min_bid + CRITICAL_MIN_SAFETY_MARGIN_PENNY

    critical_max_bid = max_bid - CRITICAL_MAX_SAFETY_MARGIN_PENNY

    raw_min_limit = manual.get("minLimitPenny")
    if isinstance(raw_min_limit, int) and raw_min_limit > 0:
        critical_min_limit = raw_min_limit + CRITICAL_MIN_SAFETY_MARGIN_PENNY
    else:
        critical_min_limit = 0

    raw_max_limit = manual.get("maxLimitPenny")
    if isinstance(raw_max_limit, int) and raw_max_limit > 0:
        critical_max_limit = max(
            0, raw_max_limit - CRITICAL_MAX_SAFETY_MARGIN_PENNY
        )
    else:
        critical_max_limit = 0

    return CriticalBidsData(
        critical_min_bid=critical_min_bid,
        critical_max_bid=critical_max_bid,
        critical_min_limit=critical_min_limit,
        critical_max_limit=critical_max_limit,
        disabled_bid=min_bid,
    )


def pick_compare_percent(bid: int, bids_array: list[dict] | None) -> int:
    """Возвращает compare для сегмента, в который попадает ставка."""
    if not bids_array:
        return 0
    sorted_bids = sorted(
        (
            b
            for b in bids_array
            if isinstance(b, dict)
            and isinstance(b.get("valuePenny"), int)
            and isinstance(b.get("compare"), int)
        ),
        key=lambda x: x["valuePenny"],
    )
    if not sorted_bids:
        return 0
    if bid <= sorted_bids[0]["valuePenny"]:
        return sorted_bids[0]["compare"]
    if bid >= sorted_bids[-1]["valuePenny"]:
        return sorted_bids[-1]["compare"]
    for i in range(len(sorted_bids) - 1):
        if (
            sorted_bids[i]["valuePenny"]
            <= bid
            < sorted_bids[i + 1]["valuePenny"]
        ):
            return sorted_bids[i]["compare"]
    return 0
