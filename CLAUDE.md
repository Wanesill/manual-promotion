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

- **`set_manual_bid` runs at most once per hour per ad.** Cooldown anchor
  is `ctx.last_log.timestamp` (the latest row in `manual_promotion_log`).
  Disable-conditions are re-evaluated each iteration. For large accounts
  one iteration may itself take hours (see below), so we mitigate
  stat-staleness by re-reading `load_today_stats` and `now` every
  `STATS_REFRESH_INTERVAL_S` (5 min) inside the iteration.
- **Per-account workers**, not one global cycle. A supervisor task
  refreshes the active-account list every 5 min and spawns / stops
  per-account workers. One worker = one account; an iteration may take
  4+ hours (5000 ads × 20/min `get_bids` limit). There is no hard
  `asyncio.wait_for` timeout — instead a **soft cap `MAX_ITERATION_S`
  (6 h)** is checked between ads: if the iteration ran past the deadline
  we break the per-ad loop and start fresh next iteration. A single
  in-flight network call is never torn down mid-flight.
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
│   └── logging_utils.py         sanitize_message (loguru patcher)
├── database/
│   ├── database.py              DAL — see "Key DAL methods" below
│   └── models/                  SQLAlchemy 2.0 mirror of parent's schema
├── external_services/
│   └── avito_service.py         singleton aiohttp.ClientSession, @retry_with_backoff,
│                                  AccountForbiddenError, 429/5xx retry via
│                                  `x-ratelimit-retry-after`
├── infra/
│   └── redis_cache.py           AvitoCache — Redis + cachetools fallback
└── dispatcher/
    ├── process_dispatcher.py    run_dispatcher: supervisor + per-account workers,
    │                              inline token resolution (_resolve_avito)
    ├── critical_bids.py         parse_critical_bids, pick_compare_percent
    ├── decision_engine.py       compute_target_state — pure function, 17 stages
    └── apply_decision.py        only mutating layer (calls Avito + writes DB rows)
```

## Cycle in one paragraph

`run_dispatcher` runs a supervisor task: every `CYCLE_INTERVAL_S`
(default 300) it calls `load_active_account_ids`, spawns
`_account_loop(account_id)` for newly active ones, sets a per-worker `stop`
event for accounts that are no longer active (the worker exits between
ads — we never tear down a network call), and reaps crashed tasks (restart
happens on the next supervisor tick). Each per-account worker is an
infinite loop with target interval `CYCLE_INTERVAL_S`. One iteration:
`load_account_promotions` → if no active promotions remain, the worker
exits; otherwise `ensure_token`, `load_today_stats`, then sequentially
per ad: `compute_target_state` → if bid bounds are needed, `fetch_bids` +
`recompute_with_bids` → `apply_decision`. Inside the per-ad loop, every
`STATS_REFRESH_INTERVAL_S` (5 min) we re-read `stats` and refresh `now` —
without it a 4-hour iteration would carry hopelessly stale budget /
schedule data. Drift detection uses `ctx.last_log.bid` (no
`getPromotionsByItemIds` call). There is no proactive rate limiter: on
429/5xx `AvitoService` honours `x-ratelimit-retry-after` and retries.

## Key DAL methods (`app/database/database.py`)

- `load_active_account_ids()` — `SELECT DISTINCT account_id` over rows with
  `status IS TRUE AND deleted_at IS NULL`. Used by the supervisor.
- `load_account_promotions(account_id)` — snapshot of all active
  promotions of a single account (joined to `Account`/`Ad`/`Profile` and
  with the latest `manual_promotion_log` row per promotion). Also returns
  `profile_active_count` — total active promotions across **all** accounts
  of the same `profile_id`, used by `decision_engine` to detect tariff
  overuse. Returns `None` if no active rows remain — the worker exits and
  the supervisor reaps it.
- `load_today_stats(account_id, today=None)` — `DISTINCT ON (ad_id)` over
  `ad_detail_statistic` rows since 00:00, ordered by
  `ad_id, timestamp DESC`, joined with `Ad`. Returns the today-accumulated
  `views`, `contacts`, `impressions`, `presence_spending`,
  `promo_spending`, `rest_spending` shaped as
  `{avito_ad_id: {...camelCase keys for the decision engine...}}`.
- `insert_log(promotion_id, bid, compare_percent, timestamp)` — idempotent
  via `ON CONFLICT DO NOTHING` on `(promotion_id, timestamp)`.
- `insert_system_note(promotion_id, text, created_at)` — system notes are
  deduplicated by `decision_engine._system_note_text` against
  `ManualPromotion.log_message` before this is called.
- `upsert_critical(promotion_id, CriticalUpdate)` — writes
  `critical_min_bid`, `critical_max_bid`, `critical_min_limit`,
  `critical_max_limit`, `disabled_bid` after a `get_bids` fetch.
- `reset_critical(promotion_id)` — sets all 5 critical_* columns to NULL.
  Called from `apply_decision` when `set_manual_bid` returns 400 (Avito
  rejected the bid = our bounds are stale). The next worker iteration sees
  NULLs → `decision_engine` returns `FETCH_BIDS` → fresh values land via
  `upsert_critical`.
- `bulk_update_log_message(updates)` — single transaction with one
  `UPDATE` per (promotion_id, message). Called per-ad immediately so the
  UI sees fresh status without waiting for a multi-hour iteration to end.

The DAL does **not** mutate `Account` rows. Tokens (`access_token`,
`expires_in`) are read-only here — refreshing a stale token in DB remains
the parent API's job. Token resolution happens inline at the start of
each iteration in `_resolve_avito(account)`:
(a) if `Account.access_token` is present and `expires_in − now >=
TOKEN_REFRESH_THRESHOLD_S` (1 h), build `AvitoService` with it;
(b) otherwise call `AvitoService.authenticate(client_id, client_secret)`
and build `AvitoService` with the returned token.
The freshly fetched token is **not persisted** to DB and not cached
between iterations — the next iteration repeats (a)/(b). If credentials
are absent → `LOG_DISABLED_BY_TOKEN_EXPIRED`; if `authenticate` fails or
returns junk → `LOG_DISABLED_BY_AUTH_FAILED`.

## Decision engine contract

`compute_target_state(DecisionInput) -> Decision` is a **pure** function. It
returns an `Action` (NOOP, FETCH_BIDS, SET_BID, REMOVE) plus the bid/limit
to send, the canonical `log_message`, and flags for `write_log` /
`write_system_note` / `update_critical`. Stages are ordered with early
exit; the precise order is documented in the docstring of
`decision_engine.py` (17 stages, mirrored in the code).

Key rules:

- If `critical_*` fields on the row are NULL → return `FETCH_BIDS`. Caller
  fetches bid bounds via Avito API and re-runs `recompute_with_bids`.
- **`bid` is mandatory.** If outside `critical_min_bid` /
  `critical_max_bid` — NOOP with `LOG_BID_BELOW_MIN` /
  `LOG_BID_ABOVE_MAX`. We **do not clamp** the bid — that is the
  signal to the operator that the configured bid violates Avito's bounds.
- **`daily_budget` is optional.** If `None`, `limitPenny` is not sent to
  `set_manual_bid` and the budget stage (7) is skipped. If set, it goes
  through `_round_to_ruble_within_critical`: **half-up** rounding to
  100 kopecks (15.3 → 15 ₽, 15.5 → 16 ₽; Python's built-in `round()`
  uses banker's rounding and would give 100 for 100.5, which is
  counter-intuitive for us), then clamped into
  `[critical_min_limit, critical_max_limit]`. The bounds themselves are
  also snapped to the ruble: min — ceil, max — floor, so the result is
  guaranteed to lie inside Avito's platform limits.
- `compare_percent` is picked by `pick_compare_percent(bid, manual.bids[])`
  — sort by `valuePenny`, find the segment `current.valuePenny <= bid <
  next.valuePenny`. Below min → `bids[0].compare`; above max →
  `bids[-1].compare`; empty → `0`.
- Disabled-by-time: `inp.now.strftime("%a") not in p.work_days` or the
  hour's bit in the 24-bit `work_hours_mask` is unset → REMOVE.
  `strftime("%a")` returns the Russian abbreviation when
  `LC_TIME=ru_RU.UTF-8` (the locale is set in `__main__.setup_logging`;
  if the OS does not have it, every ad would cascade into
  `LOG_DISABLED_BY_TIME` — set the locale in the Dockerfile). On
  schedule-disable the logged bid is `disabled_bid` (the base rate, not
  the current `bid`).
- Tariff stage (3) is disabled when `profile.manual_promotion_limit <= 0`,
  the end date is past, or `profile_active_count` already exceeds the
  tariff limit (collective protection against parent-API races leaking
  over-quota promotions into the DB).

## Russian strings are contract, not localizable

`app/log_messages.py` constants (`LOG_SUCCESS = "Успешно"`,
`LOG_DISABLED_BY_BUDGET`, etc.) end up in user-visible UI rendered by the
parent service, in `manual_promotion_note.text`, and in PostgreSQL
`log_message`. **Do not translate them. Do not "improve" the wording.** The
parent API matches them by exact string equality; structure matters.

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

There is no proactive rate limiter: on 429/5xx `AvitoService` waits per
`x-ratelimit-retry-after` and retries. Inside an account the calls are
sequential (`asyncio.gather` only fans out across accounts), so no
uncontrolled burst.

The OAuth `authenticate` endpoint (`POST /token`) is called by
`_resolve_avito` at the start of each iteration when the DB token is
missing or expiring within `TOKEN_REFRESH_THRESHOLD_S` (1 h). The result
is used to build the per-iteration `AvitoService` only — we do not write
it to `Account.access_token` and we do not cache it between iterations.
Refreshing a stale token in DB remains the parent API's job.

The batch `getPromotionsByItemIds` endpoint is **not** called either —
drift ("did we already send this bid?") is detected against the last row
in `manual_promotion_log` rather than against Avito's actual state.
Trade-off: for ads with `daily_budget` set, this re-pushes
`set_manual_bid` once per cooldown (1 h) even when nothing has changed —
we don't write the limit to the log and don't track its state separately.
For ads without `daily_budget` drift triggers only when `bid` changes.
Both fit well within rate limits.

Statistics (`ad_detail_statistic`) are **not** cached in Redis — they're
read from PostgreSQL every cycle (cheap; the parent service maintains the
table).

## Dispatcher state lives in PostgreSQL, not Redis

There is no Redis state store. What used to be `mp:last_set:*` /
`mp:last_event:*` is now derived directly from DB:

- **1-hour cooldown** — anchored at `ctx.last_log.timestamp` (the latest
  `manual_promotion_log` row). Note: `manual_promotion_log` is written
  both on SET_BID and on the hourly snapshot, so the cooldown anchor can
  drift forward by up to ~1 h in the worst case (drift right after an
  hourly snapshot has to wait another hour). Accepted on purpose —
  simplicity over precision.
- **System-note deduplication** — we compare `decision.log_message`
  against `ctx.promotion.log_message`. If the state is unchanged, we skip
  the note. `promotion.log_message` is written per-ad inside the
  iteration via `bulk_update_log_message`, so the next iteration sees the
  fresh value.

## Coding conventions

- **Python 3.12**, `from __future__ import annotations` everywhere.
- **black** line-length 79, **ruff** line-length 88
  (`select = ["E","W","F","I","B","C4","UP"]`), **mypy** `py312`,
  `ignore_missing_imports = true`.
- **loguru** for logging — never stdlib `logging`. Use the
  `sanitize_message` patcher from `app/utils/logging_utils.py`.
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
