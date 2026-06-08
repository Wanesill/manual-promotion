# manual-promotion

Автономный Python-сервис ручного продвижения объявлений Avito через CPxPromo
API. Supervisor каждые 5 минут синхронизирует список активных аккаунтов из
общей PostgreSQL и держит per-account воркеры; каждый воркер бесконечно
прокручивает свой аккаунт, сверяет состояние с расписанием / лимитами /
бюджетом и при необходимости выставляет ставку или отключает продвижение.
Ставка переустанавливается не чаще раза в час на одно объявление; условия
отключения проверяются каждый цикл.

## Что делает сервис

- **Supervisor + per-account workers.** Один supervisor-таск каждые 5 мин
  читает список активных аккаунтов (тех, у кого есть строки
  `manual_promotion` со `status=TRUE`, `deleted_at IS NULL`), спавнит
  воркер на каждый новый аккаунт и сигналит остановку отвалившимся
  (воркер выходит между объявлениями, не разрывая сетевой вызов). Упавшие
  воркеры перезапускаются на следующем тике supervisor'а.
- **Цикл одного аккаунта.** Воркер бесконечно повторяет итерации с целевым
  интервалом 5 мин. Если у аккаунта 5000 объявлений и большая часть
  требует `getBids` (лимит Avito 20/мин), одна итерация может занять
  ~4 ч — это норма, хард-таймаута нет. Чтобы бюджет/метрики не сильно
  устаревали, каждые 5 мин внутри итерации воркер дозагружает `stats` и
  пересчитывает `now`.
- **Решающее правило** — чистая функция `compute_target_state` с 17 ранними
  выходами: статус объявления → бюджет/тариф (включая суммарное число
  активных promotion'ов профиля) → расписание → метрики (показы / просмотры
  / контакты / CPV / CPC) → границы ставки → drift по последней записи в
  `manual_promotion_log` → cooldown 1 ч → почасовой snapshot.
- **Выполнение** — `set_manual_bid` / `remove_cpxpromo` через `AvitoService`
  (singleton `aiohttp.ClientSession`, 429/5xx ретраи через
  `x-ratelimit-retry-after`). Лог `manual_promotion_log`
  `(bid, compare_percent, timestamp)` — раз в час + на смены состояния.
  Системные заметки `manual_promotion_note(kind="system")` — по одной на
  событие, без дубликатов (дедуп по `ManualPromotion.log_message`).
- **На 400 от Avito** (ставка вне платформенных границ) сбрасываем
  `critical_*` в БД в NULL и инвалидируем Redis-кэш bids — следующая
  итерация перечитает свежие границы через `getBids`.

## Ключевые архитектурные решения

- **Один инстанс на процесс.** Шардирования нет.
- **Не владеет схемой БД.** Родительский API создаёт/мигрирует таблицы; мы
  только читаем + редактируем whitelisted-поля (`log_message`,
  `critical_*`, `disabled_bid`) и append-only-таблицы
  `manual_promotion_log` / `manual_promotion_note`.
- **Токены аккаунтов в БД не обновляем.** Refresh устаревшего
  `Account.access_token` — задача родительского сервиса. Здесь приоритет
  источников: (a) валидный `access_token` из БД; (b) in-memory токен от
  предыдущего `authenticate` в этом же воркере; (c) свежий
  `authenticate(client_id, client_secret)` — результат **не сохраняется в
  БД**, живёт в `AccountSession` до перезапуска воркера. Если ни одного
  источника — `LOG_DISABLED_BY_TOKEN_EXPIRED` (нет credentials) либо
  `LOG_DISABLED_BY_AUTH_FAILED` (Avito отверг).
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
- **Dispatcher state — в PostgreSQL.** Cooldown 1 ч считается от
  `manual_promotion_log.timestamp` (`ctx.last_log`), дедупликация
  системных заметок — по `manual_promotion.log_message`. Отдельного state
  store в Redis нет.
- **Время сервера = МСК.** `datetime.now()` без таймзоны.
- **Все user-visible строки на русском.** Константы `LOG_*` и текст заметок
  — часть публичного контракта с родительским API; родитель парсит часть
  по префиксу (`LOG_BID_ABOVE_MAX_PREFIX + " (…₽)"`) — переводить нельзя.

## Требования

- Python 3.12+
- Poetry 2.0+
- PostgreSQL (схема создана родительским сервисом)
- Redis 7+
- Сервер в таймзоне МСК
- Locale `ru_RU.UTF-8` (`strftime("%a")` используется в проверке расписания
  и при отсутствии локали все объявления уйдут в `LOG_DISABLED_BY_TIME`)

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

Параметры цикла (`CYCLE_INTERVAL_S=300`, `STATS_REFRESH_INTERVAL_S=300`)
зашиты константами в [`app/dispatcher/process_dispatcher.py`](./app/dispatcher/process_dispatcher.py)
— сервис рассчитан на один инстанс без фильтрации по `profile_id`.

## Структура `app/`

```
app/
├── __main__.py                  # bootstrap, signal handlers, graceful shutdown
├── log_messages.py              # русские LOG_* константы (контракт с API)
├── settings/config.py           # Pydantic-конфиг + YAML loader (APP_CONFIG)
├── utils/
│   └── logging_utils.py         # sanitize_message
├── database/
│   ├── database.py              # DAL: load_active_account_ids, load_account_promotions,
│   │                            #   load_today_stats, insert_log, insert_system_note,
│   │                            #   upsert_critical, reset_critical, bulk_update_log_message
│   └── models/                  # SQLAlchemy 2.0 — read-only mirror схемы родителя
├── external_services/
│   └── avito_service.py         # singleton ClientSession, retry, authenticate,
│                                #   AccountForbiddenError
├── infra/
│   └── redis_cache.py           # AvitoCache (mp:bids:*) — Redis + cachetools fallback
└── dispatcher/
    ├── process_dispatcher.py    # supervisor + per-account worker (run_dispatcher)
    ├── account_session.py       # обёртка над AvitoService (token resolution + bids-кэш)
    ├── critical_bids.py         # parse_critical_bids, pick_compare_percent
    ├── decision_engine.py       # compute_target_state — чистая функция
    └── apply_decision.py        # единственный мутирующий слой
```

## Логи и заметки

- **`manual_promotion_log`** — запись `(bid, compare_percent, timestamp)`
  раз в час + на изменения. UNIQUE на `(promotion_id, timestamp)` даёт
  идемпотентность. Этот же лог — источник «что мы последний раз отправили
  в Avito» для drift-детекта и якорь cooldown'а.
- **`manual_promotion.log_message`** — пишется per-ad сразу (а не bulk в
  конце цикла), чтобы UI родителя видел статус без многочасовой задержки.
- **`manual_promotion_note(kind="system")`** — заметка пишется один раз на
  событие; новая запись только если канонический `log_message` сменился
  относительно `ManualPromotion.log_message`.
- **Файловые логи** — `logs/YYYY-MM-DD.log`, ротации по retention нет —
  оставлено на внешний logrotate / systemd.

## Лицензия

[MIT](./LICENSE)
