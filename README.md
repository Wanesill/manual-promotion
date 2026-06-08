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
  (показы / просмотры / контакты / CPV / CPC) → границы ставки → дрейф со
  стороны Avito → cooldown 1 ч → почасовой snapshot.
- **Выполнение** — `set_manual_bid` / `remove_cpxpromo` через `AvitoService`
  (singleton `aiohttp.ClientSession`, 429/500 ретраи), запись в
  `manual_promotion_log` (раз в час + на смены состояния) и системные
  заметки `manual_promotion_note` (по одной на событие, без дубликатов).

## Ключевые архитектурные решения

- **Один инстанс на процесс.** Шардирования нет.
- **Не владеет схемой БД.** Родительский API создаёт/мигрирует таблицы; мы
  только читаем + редактируем whitelisted-поля (`log_message`,
  `critical_*`, `disabled_bid`).
- **Статистика метрик из БД.** Дневная дельта = `MAX − MIN` по таблице
  `ad_detail_statistic` за сегодня. Avito API за метриками не дёргаем.
- **Батч на 5000 объявлений.** Текущие ставки — одним вызовом
  `getPromotionsByItemIds` на аккаунт (TTL кэша 5 мин в Redis). Границы
  ставки (`get_bids`) — пер-объявление, кэш 1 ч.
- **Rate limiter** in-memory sliding-window per `(account_id, endpoint)`:
  `set_manual_bid` 20/мин, `get_bids`/`get_actual_rates` 20/мин,
  `remove_cpxpromo` 300/мин.
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
| `logging`  | Уровень, дублирование в stderr (файлы — всегда, в `logs/YYYY-MM-DD.log`, ретенция 30 дней)  |

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
│   │                            #   bulk_update_log_message, update_account_token
│   └── models/                  # SQLAlchemy 2.0 — read-only mirror схемы родителя
├── external_services/
│   └── avito_service.py         # singleton ClientSession, retry, AccountForbiddenError
├── infra/
│   ├── rate_limiter.py          # AccountRateLimiter — sliding window per (acc, ep)
│   ├── redis_cache.py           # AvitoCache — Redis + cachetools fallback
│   └── state_store.py           # StateStore — last_set_at / last_event
└── dispatcher/
    ├── process_dispatcher.py    # cycle() + run_dispatcher_loop
    ├── account_session.py       # обёртка над AvitoService с rate-limit acquire
    ├── critical_bids.py         # parse_critical_bids, pick_compare_percent
    ├── decision_engine.py       # compute_target_state — чистая функция
    └── apply_decision.py        # единственный мутирующий слой
```

## Логи и заметки

- **`manual_promotion_log`** — запись `(bid, compare_percent, timestamp)`
  раз в час + на изменения. UNIQUE на `(promotion_id, timestamp)` даёт
  идемпотентность.
- **`manual_promotion_note(kind="system")`** — заметка пишется один раз на
  событие; новая запись только если канонический `log_message` сменился
  по сравнению с кэшем в Redis.
- **Файловые логи** — `logs/YYYY-MM-DD.log`, ротация 30 дней.

## Лицензия

[MIT](./LICENSE)
