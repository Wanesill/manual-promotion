# manual-promotion

Автономный Python-сервис ручного продвижения объявлений Avito через CPxPromo
API. Каждые 5 минут читает таблицу `manual_promotion` из общей PostgreSQL,
сверяет состояние с расписанием/лимитами/бюджетом и при необходимости
выставляет ставку или отключает продвижение. Ставка переустанавливается не
чаще раза в час на одно объявление; условия отключения проверяются каждый
цикл.

## Что делает сервис

- **Диспетчер-цикл (5 мин)** — читает свежий снимок активных
  `manual_promotion` (`status=TRUE`, `deleted_at IS NULL`), обрабатывает
  по аккаунтам параллельно, по объявлениям внутри аккаунта — последовательно.
- **Решающее правило** — чистая функция `compute_target_state` с 18 ранними
  выходами: статус объявления → бюджет/тариф → расписание → метрики
  (показы / просмотры / контакты / CPV / CPC) → границы ставки → drift
  относительно последней записи в `manual_promotion_log` → cooldown 1 ч →
  почасовой snapshot.
- **Выполнение** — `set_manual_bid` / `remove_cpxpromo` через `AvitoService`
  (singleton `aiohttp.ClientSession`, 429/5xx ретраи через
  `x-ratelimit-retry-after`), запись в `manual_promotion_log` (раз в час +
  на смены состояния) и системные заметки `manual_promotion_note` (по одной
  на событие, без дубликатов).

## Ключевые архитектурные решения

- **Один инстанс на процесс.** Шардирования нет.
- **Не владеет схемой БД.** Родительский API создаёт/мигрирует таблицы; мы
  только читаем + редактируем whitelisted-поля (`log_message`,
  `critical_*`, `disabled_bid`) и append-only-таблицы
  `manual_promotion_log` / `manual_promotion_note`.
- **Токены аккаунтов не обновляем.** `access_token` / `expires_in` пишет
  родительский сервис; здесь только читаем. Если токен истёк —
  `LOG_DISABLED_BY_TOKEN_EXPIRED`, цикл по аккаунту пропускаем.
- **Статистика метрик из БД.** Каждая запись в `ad_detail_statistic` —
  накопительный счётчик за сегодня (сбрасывается в 00:00). Берём последнюю
  запись на ad за сегодня (`DISTINCT ON (ad_id) ... ORDER BY timestamp
  DESC`). Avito API за метриками не дёргаем.
- **Drift через лог.** «Что уже стоит на Avito» определяем по
  `ctx.last_log.bid`. Snapshot `getPromotionsByItemIds` с Avito не
  запрашиваем.
- **Кэш границ ставок.** `get_bids` per-ad — `mp:bids:{ad_id}` TTL 1 ч в
  Redis с in-process fallback (`cachetools.TTLCache`).
- **Rate-лимитера нет.** На 429/5xx `AvitoService` сам ждёт по
  `x-ratelimit-retry-after` и повторяет запрос. Внутри аккаунта вызовы
  последовательные (`asyncio.gather` — только по аккаунтам).
- **State store в Redis**: `mp:last_set:{ad_id}` (TTL ~25 ч) — для часового
  cooldown; `mp:last_event:{promotion_id}` (без TTL) — для дедупликации
  системных заметок. Namespace `mp:` — фиксированный (сервис рассчитан на
  один инстанс).
- **Время сервера = МСК.** `datetime.now()` без таймзоны.
- **Все user-visible строки на русском.** Константы `LOG_*` и текст заметок
  — часть публичного контракта с родительским API.

## Требования

- Python 3.12+
- Poetry 2.0+
- PostgreSQL (схема создана родительским сервисом)
- Redis 7+
- Сервер в таймзоне МСК
- Locale `ru_RU.UTF-8` (для названий дней недели в логах)

## Установка и запуск

```bash
poetry install                                  # установить зависимости
cp config.example.yml config.yml                # заполнить DSN и параметры
APP_CONFIG=config.yml poetry run python -m app
```

Грейсфул-остановка по `SIGINT` / `SIGTERM` (`Ctrl+C`).

## Конфигурация

Параметры в YAML (см. [`config.example.yml`](./config.example.yml)):

| Секция     | Назначение                                                                                  |
| ---------- | ------------------------------------------------------------------------------------------- |
| `database` | DSN PostgreSQL (`postgresql+asyncpg://…`), пул соединений                                    |
| `redis`    | DSN Redis (`redis://…/0`)                                                                   |
| `logging`  | Уровень, дублирование в stderr (файлы — всегда, в `logs/YYYY-MM-DD.log`)                    |

Параметры цикла (`CYCLE_INTERVAL_S=300`, `MAX_CYCLE_TIMEOUT_MULTIPLIER=3`)
зашиты константами в [`app/dispatcher/process_dispatcher.py`](./app/dispatcher/process_dispatcher.py)
— сервис рассчитан на один инстанс без фильтрации по `profile_id`.

## Структура `app/`

```
app/
├── __main__.py                  # bootstrap, signal handlers, graceful shutdown
├── log_messages.py              # русские LOG_* константы (контракт с API)
├── settings/config.py           # Pydantic-конфиг + YAML loader (APP_CONFIG)
├── utils/
│   ├── logging_utils.py         # sanitize_message
│   └── time_utils.py            # расписание работы (work_days, work_hours_mask)
├── database/
│   ├── database.py              # DAL: load_active_promotions, load_today_stats,
│   │                            #   insert_log, insert_system_note, upsert_critical,
│   │                            #   bulk_update_log_message
│   └── models/                  # SQLAlchemy 2.0 — read-only mirror схемы родителя
├── external_services/
│   └── avito_service.py         # singleton ClientSession, retry, AccountForbiddenError
├── infra/
│   ├── redis_cache.py           # AvitoCache (mp:bids:*) — Redis + cachetools fallback
│   └── state_store.py           # StateStore — last_set_at / last_event
└── dispatcher/
    ├── process_dispatcher.py    # cycle() + run_dispatcher_loop
    ├── account_session.py       # обёртка над AvitoService (проверка токена + bids-кэш)
    ├── critical_bids.py         # parse_critical_bids, pick_compare_percent
    ├── decision_engine.py       # compute_target_state — чистая функция
    └── apply_decision.py        # единственный мутирующий слой
```

## Логи и заметки

- **`manual_promotion_log`** — запись `(bid, compare_percent, timestamp)`
  раз в час + на изменения. UNIQUE на `(promotion_id, timestamp)` даёт
  идемпотентность. Этот же лог — источник «что мы последний раз отправили
  в Avito» для drift-детекта.
- **`manual_promotion_note(kind="system")`** — заметка пишется один раз на
  событие; новая запись только если канонический `log_message` сменился
  по сравнению с кэшем в Redis (`mp:last_event:*`).
- **Файловые логи** — `logs/YYYY-MM-DD.log`, ротации по retention нет —
  оставлено на внешний logrotate / systemd.

## Лицензия

[MIT](./LICENSE)
