# AGENTS.md

## Что это за проект

ZakharCompanion — асинхронный Telegram-бот на aiogram 3 для небольшой Minecraft-комьюнити. Он связывает Telegram-профиль с Minecraft-ником, следит за онлайном через Source RCON и ведёт игровую экономику: опыт, Zbucks, предметы, работы, мини-игры, рынок, долги, ставки и бизнесы.

Код и пользовательские тексты в основном русскоязычные. Сохраняй текущий юмористический тон, но не смешивай игровые тексты с инфраструктурной логикой.

## Среда, запуск и проверки

Нужен Python 3.10+ (`X | None` используется без `from __future__ import annotations`). Локальная установка:

```bash
python3 -c 'import sys; assert sys.version_info >= (3, 10), sys.version'
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
test -e .env || cp .env.example .env
```

Установка зависимостей и полноценный запуск в текущем checkout не проверялись. Рабочий запуск выполняется из корня репозитория:

```bash
python main.py
```

Это не smoke test: команда мигрирует `DB_PATH`, начинает Telegram long polling, подключается к RCON и запускает фоновые экономические операции. Не запускай её с реальными токеном, БД или RCON без явного разрешения и не поднимай второй экземпляр с теми же token/DB: нет leader election, возможны конфликт polling и двойные операции других scheduler. Shutdown отменяет и дожидается scheduler/update-задач и закрывает Telegram-сессию с обоими SQLite-соединениями; RCON-сокет явно не закрывается.

Проверки после подготовки окружения:

```bash
PYTHONPYCACHEPREFIX=/tmp/zachary2-pycache python -m compileall -q main.py config.py keyboards.py content db game handlers mc utils
python -m pip check
python -B -c 'import main; print("imports OK")'
PYTHONPYCACHEPREFIX=/tmp/zachary2-pycache python -m unittest -v tests.test_lottery
git diff --check
git diff --cached --check
git status --short
```

В этом checkout по умолчанию есть только Python 3.9 без зависимостей; `pip check`, import и tests выполняй после setup на Python 3.10+. Import `main` не вызывает `main()` и не трогает БД/сеть. Есть узкие stdlib-тесты лотереи; общих линтера, type checker и CI по-прежнему нет. Не утверждай, что незапущенные проверки прошли. Для изменённой чистой логики добавляй узкую проверку или тест, если это оправдано, но не вводи новый toolchain мимоходом.

## Конфигурация и внешние системы

- `config.py` — источник истины; значения считываются из `.env` при первом импорте, поэтому тестовый env выставляй заранее.
- Telegram: `BOT_TOKEN` обязателен; `ADMIN_ID` и `CHANNEL_ID` фактически нужны рабочим сценариям, `THREAD_ID` опционален (`0` = без topic). Startup проверяет только token; пустые ID молча становятся `0`, а нечисловые integer env ломают импорт.
- Minecraft: `RCON_HOST`, `RCON_PORT`, `RCON_PASSWORD`; `POLL_INTERVAL` задаёт период опроса.
- SQLite: `DB_PATH`, по умолчанию относительный `zachary.db`.
- Опыт: `XP_DAILY_QUOTA`, `XP_MIN`, `XP_NOPLAY_MULT`, `XP_DECAY_PER_MINUTE`, `XP_LEVEL_STEP`. Они пока не перечислены в `.env.example`; при изменении конфигурации синхронизируй пример.
- В проекте нет `.gitignore`. Никогда не добавляй в git `.env`, `*.db`, `.venv`, `__pycache__`, токены, пароли или дампы пользовательских данных.

## Карта архитектуры

- `main.py` — composition root: инициализирует storage, Bot/Dispatcher, вручную подключает routers в значимом порядке, запускает polling и одиннадцать scheduler-задач.
- `handlers/` — Telegram boundary. Router принимает update, проверяет контекст и актуальное состояние, координирует storage/game/UI и отвечает пользователю.
- `game/` — правила, константы, расчёты и долгоживущие scheduler-циклы. Это не полностью чистый слой: schedulers получают `Bot` и рассылают результаты.
- `content/` — реплики, лор, наборы случайных текстов и статические данные для сценариев.
- `db/storage.py` — единственный repository facade и единственное место для SQL, схемы и миграций.
- `mc/rcon.py` — один переиспользуемый RCON-сокет; доступ сериализован `asyncio.Lock`, при обрыве есть одна попытка переподключения.
- `mc/poller.py` — сравнивает текущий online set с процессным `known_online`, пишет playtime/first seen и публикует приветствия.
- `utils/` и `keyboards.py` — guards, редактируемые фото/текстовые экраны, объявления, отложенное удаление и общие клавиатуры.
- `static/` — исходные изображения меню; Telegram `file_id`/`file_unique_id` кэшируются в SQLite `meta`.

Типичный поток: Telegram update → feature router → private/owner/profile guard → повторная проверка БД → правило из `game/`/операция `storage` → edit/answer → best-effort announcement. Minecraft-поток: RCON `list` → poller diff → SQLite → сообщение в channel/thread.

Куб: `game/cube.py` содержит детерминированный генератор 4×4 и scheduler, `content/cube.py` — долговечные ключи описаний, `handlers/cube.py` — private-only интерфейс. Поколение глобально для всех игроков; authoritative комнаты, проходы, раскрытия, ловушки, позиции, idempotency-запросы, waitlist и lease-outbox находятся в SQLite. Вход/победа/расход предмета выполняются одной economy-транзакцией, а Telegram и проверка Густава идут после commit. Таймеры, цена, приз на участника и лимит задаются `CUBE_*` в `config.py`/`.env.example`.

## Как хранится состояние

1. **SQLite переживает рестарт.** `storage.init()` открывает общий `aiosqlite.Connection` и отдельное сериализованное economy-соединение для критичных списаний/лотереи/Куба. В SQLite живут профили, деньги, опыт, inventory, cooldown/status, статистика, рынок, ставки, долги, рыбалка, бизнесы, отмыв, тиражи/билеты/outbox лотереи, поколения/комнаты/забеги/outbox Куба и `meta`.
2. **FSM — только короткий ввод.** `Dispatcher()` использует стандартный in-memory storage aiogram со стратегией `USER_IN_CHAT`, без TTL и явной event isolation. Паттерн: `set_state()` → `update_data()` с доменными ID и актуальными `chat_id/msg_id` → state-filtered message handler → `get_data()` → `clear()` → повторная проверка БД. FSM теряется при рестарте; общего `/cancel` нет. Переход в меню или команда сами state не очищают, а state-handler более раннего router может перехватить команду — отмену проектируй явно.
3. **Активные партии — RAM.** `cashier`, `chef`, `courier`, `vpn`, `vovka`, `scammer` держат `_games[tg_id]`; у scammer FSM лишь маршрутизирует сообщения, а authoritative state находится в `_games`. `_bg`, `_tasks` и `_hit_log` тоже процессные. Перезапуск обрывает партии, но уже записанный SQLite cooldown остаётся.
4. **Callback data — публичный маршрут, не источник истины.** Формат вручную namespaced через `:`. Храни там только короткие ID/choice/page/round/owner; секретный ответ и authoritative round держи на сервере. Перед мутацией перечитывай БД и отвергай stale/double click.
5. **Долгие ожидания — абсолютный ISO timestamp в SQLite + scheduler.** Не клади рынок, улов, долг, рейд, тираж лотереи или бизнес-таймер в FSM/RAM. Scheduler-поля используют naive `datetime.now().isoformat()` в локальном времени, а schema defaults `datetime('now')` — UTC. Сохраняй представление конкретной колонки; не смешивай aware/naive или local/UTC без общей миграции.

## Правила слоя данных и экономики

- Не пиши SQL вне `db/storage.py`. Используй `?`-параметры; новую таблицу создавай идемпотентно в `init()`, additive-колонку добавляй через `_ensure_column`.
- Storage обычно возвращает позиционные tuple; лотерея использует frozen dataclass для явно именованных снимков/результатов. Для tuple сверяй индекс с конкретным `SELECT` и docstring; при изменении формы обновляй все call sites.
- Почти каждый mutating helper сам делает `commit()`. Несколько helper-вызовов не образуют транзакцию и могут перемежаться конкурентными update. `spend_zbucks[_traced]`, активация прятки, лотерея, Куб, `add_item`, `remove_item` и `clear_inventory` сериализованы через economy connection + `BEGIN IMMEDIATE`; `take_stock` остаётся read-check-write и сам по себе не concurrency-safe.
- Новую критичную денежную/inventory операцию делай атомарным условным SQL. Если нужна транзакция, сериализуй всю её границу либо используй отдельное connection: простой `BEGIN` на общем `_db` не мешает другой coroutine вклинить SQL в ту же транзакцию. Одна большая storage-функция без такой границы атомарность не гарантирует.
- Обычный доход начисляй через `game.taxman.grant()`: это каноническая точка правил dirty/Gustav, но сейчас она сама состоит из нескольких commit и не crash-atomic. Для перевода сохраняй происхождение денег: `spend_zbucks_traced()` → `grant(..., dirty_part=...)`. Прямой `add_zbucks()` допустим только для осознанного refund/служебного сценария.
- Расходы проводи через `spend_zbucks()`/`spend_zbucks_traced()`, предметы — через storage helpers: спрятанные и грязные деньги имеют особую семантику.
- Не путай `set_cooldown()` (время последнего использования) и `set_cooldown_until()` (expiry). `cooldowns` также хранит статусы, налоги и рейды; глобальный reset удаляет их все.
- Scheduler-флоу проектируй идемпотентными и безопасными к рестарту. Durable claim/status и экономический результат должны меняться атомарно; Telegram/RCON notification выполняй после commit и считай best effort. Не копируй существующий delete/status-first порядок ряда schedulers: падение между шагами теряет результат, а partial daily может повторить награду.
- RCON/Telegram side effects не помещай в storage. Если пользователь платит за внешний эффект, выбери порядок так, чтобы сбой RCON не списал деньги, и продумай повторный клик.

## Правила handlers, callback и UI

- Новый feature обычно получает `handlers/<feature>.py` с `router = Router()`; не забудь импорт и `include_router()` в `main.py`. Порядок routers важен, особенно для FSM message handlers.
- Общего auth middleware нет. До действий явно проверяй профиль и контекст. Для доступного в группе экрана используй `with_owner(...)` (owner — последний сегмент) + `ensure_owner()`; для private-only callback обычно не нужен owner, но первым вызывается `ensure_private()`. Адресный admin/lender callback проверяй по фактическому `from_user`. `ensure_owner()` при битом/отсутствующем suffix сейчас пропускает клик — не считай его единственной проверкой мутации.
- Для обычной menu-навигации используй `show_photo_menu`, `show_screen`, `show_text_menu`; отдельное сообщение допустимо как часть механики или уведомление. `show_text_menu()` может удалить фото и вернуть новый `Message`; FSM обязан сохранить именно возвращённый `message_id`.
- Глобальный parse mode — HTML. Экранируй пользовательские и внешние строки перед вставкой; не ломай лимит Telegram caption (1024) и callback data (64 bytes).
- Каждый callback-путь, включая stale/no-op, должен завершать spinner через `cb.answer()`.
- Любую fire-and-forget `asyncio.create_task()` держи сильной ссылкой до завершения. Новый глобальный scheduler добавь и в startup, и в shutdown cancellation.
- Ожидаемые ошибки редактирования/доставки Telegram могут деградировать в новый ответ или best effort. Ошибки доменной операции не проглатывай; scheduler должен логировать их и продолжать следующий tick.
- Для новой механики ищи ближайший аналог и сохраняй разделение: тексты → `content/`, параметры/расчёты → `game/`, Telegram orchestration → `handlers/`, persistence → `db/storage.py`.

## Границы и Definition of Done

Всегда сохраняй существующие пользовательские изменения и сначала проверяй `git status`. Сначала согласуй destructive schema/data migration, массовый reset, новый внешний сервис/storage либо любой тест на живых Telegram/RCON/DB. Не меняй экономические коэффициенты или публичный тон за пределами поставленной задачи.

Изменение готово, когда:

- код находится в правильных слоях; новый router/scheduler подключён и корректно завершается;
- restart-critical state долговечен, transient state явно допустим к потере;
- действия защищены от чужих, stale и повторных callback, а актуальные DB-инварианты перепроверены;
- денежные/inventory операции сохраняют atomicity и правила `grant`/dirty/hidden funds;
- пользовательский HTML экранирован, меню корректно переживает photo ↔ text переход;
- схема, `config.py`, `.env.example` и этот файл обновлены вместе с затронутым контрактом;
- применимые исполняемые проверки выше и новые targeted checks завершаются с exit code 0;
- `git status --short`, intended diff и все untracked-файлы осмотрены вручную: секретов, локальной БД и окружения в изменении нет; непроверенные live-сценарии честно перечислены в отчёте.
