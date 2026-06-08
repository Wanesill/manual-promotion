"""Парсинг ответа Avito get_bids в границы для нашего decision engine.

Сырая структура `manual` блока в ответе Avito CPxPromo:
    {
        "bidPenny": int,
        "limitPenny": int,
        "minBidPenny": int,
        "maxBidPenny": int,
        "minLimitPenny": int,
        "maxLimitPenny": int,
        "recBidPenny": int,
        "bids": [{"compare": int, "valuePenny": int, ...}, ...],
    }

`parse_critical_bids` возвращает None если CPxPromo на ad недоступен
(нет блока manual или нет minBidPenny) — caller интерпретирует это
как LOG_PROMOTION_UNAVAILABLE.

`pick_compare_percent` возвращает процент опережения для нашей ставки:
ищем сегмент [valuePenny_i; valuePenny_{i+1}) включающий bid и берём
compare i-го элемента. Граничные случаи: ниже самой малой ставки —
compare первой; выше самой большой — compare последней; нет данных — 0.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CriticalBidsData",
    "parse_critical_bids",
    "pick_compare_percent",
]

_CRITICAL_BID_MARGIN_PENNY: int = 10


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
    manual = bids_info.get("manual")
    if not isinstance(manual, dict):
        return None
    min_bid = manual.get("minBidPenny")
    max_bid = manual.get("maxBidPenny")
    if not isinstance(min_bid, int) or not isinstance(max_bid, int):
        return None

    bids_array = manual.get("bids", [])
    non_zero = [
        b
        for b in bids_array
        if isinstance(b, dict)
        and isinstance(b.get("compare"), int)
        and b["compare"] > 0
        and isinstance(b.get("valuePenny"), int)
    ]
    if non_zero:
        critical_min_bid = min(b["valuePenny"] for b in non_zero)
    else:
        critical_min_bid = min_bid + _CRITICAL_BID_MARGIN_PENNY

    critical_max_bid = max_bid - _CRITICAL_BID_MARGIN_PENNY
    critical_min_limit = int(manual.get("minLimitPenny") or 0)
    critical_max_limit = int(manual.get("maxLimitPenny") or 0)
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
        if sorted_bids[i]["valuePenny"] <= bid < sorted_bids[i + 1]["valuePenny"]:
            return sorted_bids[i]["compare"]
    return 0
