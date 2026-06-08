# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## What this service does

`manual-promotion` is a standalone **dispatcher** for the Avito CPxPromo
"manual promotion" feature (ручное продвижение). It reads the
`manual_promotion` table from a shared PostgreSQL every 5 minutes and, for
each active ad, either calls `set_manual_bid` against the Avito API or
removes the promotion (`remove_cpxpromo`) based on schedule, metric limits,
budget, and bid bounds. The end-user UI / public HTTP API lives in a
**separate parent service** — this repo only owns the loop that keeps
Avito's state in sync with the rows the parent service writes.

Critical constraints baked into the design:

- **`set_manual_bid` runs at most once per hour per ad**, but
  disable-conditions are re-evaluated every 5 minutes (so a budget breach
  takes effect quickly, but the bid itself isn't re-pushed without reason).
- **Single instance** — no sharding, no leader election.
- **Schema is owned by the parent service** — we only read from it and write
  to whitelisted columns (`log_message`, `critical_min_bid`,
  `critical_max_bid`, `critical_min_limit`, `critical_max_limit`,
  `disabled_bid`) and to the append-only tables `manual_promotion_log` and
  `manual_promotion_note`.
- **Metric statistics come from the DB**, not from the Avito API. The
  parent service populates `ad_detail_statistic` as a per-day cumulative
  counter that resets at 00:00; today's value = latest row of today
  per ad (`DISTINCT ON (ad_id) ... ORDER BY timestamp DESC`).
- **Server is in MSK** — `datetime.now()` without tzinfo is the source of
  truth for "now". Don't add tz conversions.

## Project layout

```
app/
├── __main__.py                  bootstrap: locale, signal handlers, graceful shutdown
├── log_messages.py              Russian LOG_* constants — contract with the parent API
├── settings/config.py           Pydantic + YAML (APP_CONFIG env var) + lru_cache
├── utils/
│   ├── logging_utils.py         sanitize_message (loguru patcher)
│   └── time_utils.py            work-schedule helpers (WORK_DAY_NAMES, hour_is_active)
├── database/
│   ├── database.py              DAL — see "Key DAL methods" below
│   └── models/                  SQLAlchemy 2.0 mirror of parent's schema
├── external_services/
│   └── avito_service.py         singleton aiohttp.ClientSession, @retry_with_backoff,
│                                  AccountForbiddenError, 429/5xx retry via
│                                  `x-ratelimit-retry-after`
├── infra/
│   ├── redis_cache.py           AvitoCache — Redis + cachetools fallback
│   └── state_store.py           StateStore — last_set_at, last_event
└── dispatcher/
    ├── process_dispatcher.py    cycle() + run_dispatcher_loop (fixed cycle_interval windows)
    ├── account_session.py       wraps AvitoService (token check + bids cache)
    ├── critical_bids.py         parse_critical_bids, pick_compare_percent
    ├── decision_engine.py       compute_target_state — pure function, 18 stages
    └── apply_decision.py        only mutating layer (calls Avito + writes DB rows)
```

## Cycle in one paragraph

`run_dispatcher_loop` repeats `cycle()` every `CYCLE_INTERVAL_S` seconds
(constant in `app/dispatcher/process_dispatcher.py`, default 300) with a
hard timeout of `CYCLE_INTERVAL_S * MAX_CYCLE_TIMEOUT_MULTIPLIER`
(default ×3). Both knobs are intentionally hard-coded — this service runs
as a single instance, no per-deployment tuning is expected. One cycle: load
active promotions (one SQL with the necessary JOINs), group by `account`, fan
out per-account in `asyncio.gather`. Inside an account: one `load_today_stats`
(from `ad_detail_statistic`, latest row per ad of today), then sequentially
per ad: `compute_target_state` → if it needs bid bounds, `fetch_bids` +
recompute → `apply_decision`. Внутри аккаунта вызовы Avito идут
последовательно (нет проактивного rate-лимитера; на 429 `AvitoService` сам
ждёт по `x-ratelimit-retry-after`). Drift детектится по
`ctx.last_log.bid` — текущее состояние на стороне Avito с API не
запрашиваем.

## Key DAL methods (`app/database/database.py`)

- `load_active_promotions()` — the one SELECT with JOIN on
  `ManualPromotion`/`Account`/`Ad`/`Profile`, filters `status IS TRUE`,
  `deleted_at IS NULL`. Returns a `Snapshot` grouped by account. No
  profile filtering — this is a single-instance service.
- `load_today_stats(account_id, today=None)` — `DISTINCT ON (ad_id)` over
  `ad_detail_statistic` rows since 00:00, ordered by `ad_id, timestamp DESC`,
  joined with `Ad`. Возвращает накопленные сегодня
  `views`, `contacts`, `impressions`, `presence_spending`, `promo_spending`,
  `rest_spending` в формате `{avito_ad_id: {...camelCase keys for the
  decision engine...}}`.
- `insert_log(promotion_id, bid, compare_percent, timestamp)` — idempotent
  via `ON CONFLICT DO NOTHING` on `(promotion_id, timestamp)`.
- `insert_system_note(promotion_id, text, created_at)` — system notes are
  deduplicated by `StateStore.last_event` before this is called.
- `upsert_critical(promotion_id, CriticalUpdate)` — writes
  `critical_min_bid`, `critical_max_bid`, `critical_min_limit`,
  `critical_max_limit`, `disabled_bid` after a `get_bids` fetch.
- `bulk_update_log_message(updates)` — single statement at the end of each
  account batch.

The DAL does **not** mutate `Account` rows. Tokens (`access_token`,
`expires_in`) are read-only here — refresh is the parent service's
responsibility. If `expires_in <= now()` we log `LOG_DISABLED_BY_TOKEN_EXPIRED`
and skip the account for this cycle.

## Decision engine contract

`compute_target_state(DecisionInput) -> Decision` is a **pure** function. It
returns an `Action` (NOOP, FETCH_BIDS, SET_BID, REMOVE) plus the bid/limit
to send, the canonical `log_message`, and flags for `write_log` /
`write_system_note` / `update_critical`. Stages are ordered with early
exit; the precise order is documented in the docstring of
`decision_engine.py` (18 stages, повторены в коде). Key rules:

- If `critical_*` fields on the row are NULL → return `FETCH_BIDS`. Caller
  fetches bid bounds via Avito API and re-runs `recompute_with_bids`.
- Limit clamp: `limit_to_send = clamp(daily_budget, critical_min_limit,
  critical_max_limit)` — always sent to Avito if `daily_budget` is set.
- `compare_percent` is picked by `pick_compare_percent(bid, manual.bids[])`
  — sort by `valuePenny`, find the segment `current.valuePenny <= bid <
  next.valuePenny`. Below min → `bids[0].compare`; above max →
  `bids[-1].compare`; empty → `0`.
- Disabled-by-time uses `weekday_abbr(now)` against `work_days` and a
  24-bit `work_hours_mask`. On disable due to schedule, the logged bid is
  `disabled_bid` (the base rate, not the current `bid`).

## Russian strings are contract, not localizable

`app/log_messages.py` constants (`LOG_SUCCESS = "Успешно"`,
`LOG_DISABLED_BY_BUDGET`, etc.) end up in user-visible UI rendered by the
parent service, in `manual_promotion_note.text`, and in PostgreSQL
`log_message`. **Do not translate them. Do not "improve" the wording.** The
parent API has parsing code that matches some of them by prefix
(`LOG_BID_ABOVE_MAX_PREFIX + " ({critical_max_bid//100}₽)"`); structure
matters.

The same goes for log lines that contain bid/limit values for operators —
keep them Russian.

## Money representation

Bids and limits are stored and exchanged in **kopecks** (rubles × 100)
across the wire and in our DB. Conversion to rubles happens only in the
parent service's HTTP serializers. Don't introduce a ruble field on our
side.

## Rate limits and caching cheatsheet

| Endpoint                          | Avito limit       | Cache (Redis TTL)                            |
| --------------------------------- | ----------------- | -------------------------------------------- |
| `get_bids` (per ad)               | 20/min/account    | `mp:bids:{ad_id}` 3600s                      |
| `set_manual_bid`                  | 20/min/account    | — (invalidates bids cache)                   |
| `remove_cpxpromo`                 | 300/min/account   | —                                            |

Проактивного rate-лимитера нет: на 429/5xx `AvitoService` сам ждёт по
`x-ratelimit-retry-after` и повторяет запрос. Внутри аккаунта вызовы
последовательные (`asyncio.gather` — только по аккаунтам), так что
неконтролируемого фан-аута нет.

The OAuth `authenticate` endpoint is **not** called from this service —
token refresh is owned by the parent API.

The batch `getPromotionsByItemIds` endpoint is **not** called either — drift
("did we already send this bid?") is detected against the last row in
`manual_promotion_log` rather than against Avito's actual state. Trade-off: for
ads with `daily_budget` set (which is every active row, per stage 2), this
re-pushes `set_manual_bid` once per cooldown (1h) even when nothing changed.
That's within rate limits.

Statistics (`ad_detail_statistic`) are **not** cached in Redis — they're
read from PostgreSQL every cycle (cheap; the parent service maintains the
table).

## State store (`infra/state_store.py`)

| Key                            | TTL  | Purpose                                                       |
| ------------------------------ | ---- | ------------------------------------------------------------- |
| `mp:last_set:{ad_id}`          | ~25h | timestamp of last `set_manual_bid` — for hourly cooldown      |
| `mp:last_event:{promotion_id}` | none | last canonical `log_message` — for system-note deduplication  |

Namespace `mp:` is fixed — single instance, no need for per-deployment
scoping.

Worst case after losing Redis: one redundant `set_manual_bid` per ad in the
next cycle and one duplicated note per promotion. Acceptable.

## Coding conventions

- **Python 3.12**, `from __future__ import annotations` everywhere.
- **black** line-length 79, **ruff** line-length 88
  (`select = ["E","W","F","I","B","C4","UP"]`), **mypy** `py312`,
  `ignore_missing_imports = true`.
- **loguru** for logging — never stdlib `logging`. Use the bidder's
  `sanitize_message` patcher.
- **SQLAlchemy 2.0 async** with `async_sessionmaker(expire_on_commit=False)`.
- **No new top-level dependencies without a reason** — the runtime set is
  intentionally minimal (no aiogram / no aiohttp-socks; logs go only to
  stderr + file).

## Development commands

```bash
poetry install                                  # install runtime + dev deps
cp config.example.yml config.yml                # fill DSNs
APP_CONFIG=config.yml poetry run python -m app  # run the dispatcher

poetry run ruff check app                       # lint
poetry run black --check app                    # format check
poetry run mypy app                             # type check
```

`SIGINT` / `SIGTERM` triggers graceful shutdown (cycle finishes, aiohttp
session + Redis + SQLAlchemy engine close in `finally`).
