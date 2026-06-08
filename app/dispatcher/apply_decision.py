"""Единственный мутирующий слой: применяет Decision."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from app.dispatcher.decision_engine import Action, Decision
from app.external_services.avito_service import AccountForbiddenError
from app.log_messages import (
    LOG_BID_CHANGE_FAILED,
    LOG_DISABLED_BY_AUTH_FAILED,
)

if TYPE_CHECKING:
    from app.database.database import Database, PromotionContext
    from app.dispatcher.account_session import AccountSession

__all__ = ["apply_decision"]


async def apply_decision(
    decision: Decision,
    ctx: PromotionContext,
    session: AccountSession,
    database: Database,
    now: datetime,
) -> str | None:
    """Применяет Decision и возвращает финальный log_message.

    Возвращает None если ничего применять не нужно. Caller bulk-обновляет
    `manual_promotion.log_message` в конце цикла по аккаунту.
    """
    log_message = decision.log_message or None

    # 1. critical_* (записать сразу, до сетевых вызовов)
    if decision.update_critical is not None:
        await database.upsert_critical(
            promotion_id=ctx.promotion.id,
            payload=decision.update_critical,
        )

    # 2. сетевой вызов
    if decision.action == Action.SET_BID:
        try:
            result = await session.set_manual_bid(
                ad_id=ctx.ad.ad_id,
                bid=decision.bid_penny,  # type: ignore[arg-type]
                limit_penny=decision.limit_penny,
            )
        except AccountForbiddenError:
            log_message = LOG_DISABLED_BY_AUTH_FAILED
            await session.invalidate_caches_for_ad(ctx.ad.ad_id)
            return log_message
        if result:
            await session.invalidate_caches_for_ad(ctx.ad.ad_id)
        elif result is None:
            # Avito отверг ставку — границы устарели, сбросим bids-кэш
            await session.invalidate_caches_for_ad(ctx.ad.ad_id)
            log_message = LOG_BID_CHANGE_FAILED
        else:
            log_message = LOG_BID_CHANGE_FAILED

    elif decision.action == Action.REMOVE:
        try:
            await session.remove_cpxpromo(ad_id=ctx.ad.ad_id)
        except AccountForbiddenError:
            log_message = LOG_DISABLED_BY_AUTH_FAILED
            return log_message

    # 3. запись лога (после успешного сетевого вызова или просто snapshot).
    # Эта запись — единственный источник для cooldown (1 ч) и для drift-
    # детекта в decision_engine: см. ctx.last_log в следующем цикле.
    if decision.write_log and decision.log_bid is not None:
        # Если SET_BID не удался — лог не пишем (фактическая ставка
        # не изменилась). Логируем только подтверждённые состояния.
        if decision.action == Action.SET_BID and log_message == LOG_BID_CHANGE_FAILED:
            pass
        else:
            try:
                await database.insert_log(
                    promotion_id=ctx.promotion.id,
                    bid=decision.log_bid,
                    compare_percent=decision.compare_percent,
                    timestamp=now,
                )
            except Exception:
                logger.exception(
                    "insert_log сбой promotion={} bid={}",
                    ctx.promotion.id,
                    decision.log_bid,
                )

    # 4. системная заметка (один раз на событие). Дедупликация —
    # `_system_note_text` уже сравнил с `promotion.log_message`; здесь
    # просто пишем без апдейта какого-либо внешнего state.
    if decision.write_system_note is not None and log_message is not None:
        need_write, text = decision.write_system_note
        if need_write:
            try:
                await database.insert_system_note(
                    promotion_id=ctx.promotion.id,
                    text=text,
                    created_at=now,
                )
            except Exception:
                logger.exception(
                    "insert_system_note сбой promotion={} text={}",
                    ctx.promotion.id,
                    text,
                )

    return log_message
