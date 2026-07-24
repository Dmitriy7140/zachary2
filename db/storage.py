"""Хранилище: игроки (для детекта новичков) и профили ZakharCompanion."""
import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Literal

import aiosqlite

from config import config

_db: aiosqlite.Connection | None = None
_economy_db: aiosqlite.Connection | None = None
_economy_lock = asyncio.Lock()

LotteryPurchaseStatus = Literal[
    "ok", "duplicate", "closed", "insufficient", "no_profile"
]

CubeEnterStatus = Literal[
    "entered",
    "resumed",
    "not_recruiting",
    "full",
    "closed",
    "insufficient",
    "no_profile",
    "invalid",
]
CubeMoveStatus = Literal[
    "moved", "won", "wall", "hazard", "bounced", "stale", "closed", "no_run"
]
CubeActionStatus = Literal[
    "resolved_and_moved",
    "already_resolved",
    "missing_item",
    "stale",
    "closed",
    "no_run",
    "invalid",
]
CubeObserveStatus = Literal["observed", "wall", "stale", "closed", "no_run"]
CubeNotifyStatus = Literal[
    "subscribed", "already_subscribed", "cancelled", "stale", "invalid"
]


@dataclass(frozen=True)
class CubeDirectionView:
    direction: str
    exists: bool
    room_id: int | None = None
    room_code: str | None = None
    category: str | None = None
    hazard_active: bool = False


@dataclass(frozen=True)
class CubeView:
    generation_id: int
    generation_status: str
    created_at: str
    idle_expires_at: str
    lobby_closes_at: str | None
    closes_at: str | None
    roster_locked: bool
    participant_count: int
    prize_amount: int
    entry_cost: int
    prize_per_participant: int
    max_participants: int
    balance: int | None
    run_id: int | None
    run_status: str | None
    run_version: int | None
    current_room_id: int | None
    room_code: str | None
    room_kind: str | None
    room_description_key: str | None
    room_effect_kind: str | None
    room_effect_arg: str | None
    room_hazard_kind: str | None
    room_hazard_resolved: bool
    room_resolved_by_nick: str | None
    subscription_id: int | None
    subscription_generation_id: int | None
    pending_hazard_room_id: int | None
    pending_hazard_kind: str | None
    pending_required_item_key: str | None
    pending_consume_qty: int
    explored_count: int
    directions: tuple[CubeDirectionView, ...]


@dataclass(frozen=True)
class CubeLifecycleResult:
    generation_id: int
    status: str
    transitioned: bool
    closed_generation_id: int | None = None


@dataclass(frozen=True)
class CubeEnterResult:
    status: CubeEnterStatus
    generation_id: int
    run_id: int | None
    version: int | None
    participant_count: int
    prize_amount: int
    balance: int


@dataclass(frozen=True)
class CubeObserveResult:
    status: CubeObserveStatus
    generation_id: int
    version: int | None
    target_room_id: int | None = None
    category: str | None = None


@dataclass(frozen=True)
class CubeMoveResult:
    status: CubeMoveStatus
    generation_id: int
    version: int | None
    entered_room_id: int | None = None
    final_room_id: int | None = None
    effect_kind: str | None = None
    effect_arg: str | None = None
    target_room_id: int | None = None
    prize_amount: int = 0
    next_generation_id: int | None = None


@dataclass(frozen=True)
class CubeActionResult:
    status: CubeActionStatus
    generation_id: int
    version: int | None
    target_room_id: int | None = None
    final_room_id: int | None = None
    effect_kind: str | None = None
    required_item_key: str | None = None
    consume_qty: int = 0
    hazard_kind: str | None = None


@dataclass(frozen=True)
class CubeNotifyResult:
    status: CubeNotifyStatus
    generation_id: int
    subscription_id: int | None


@dataclass(frozen=True)
class CubeWinnerClaim:
    generation_id: int
    winner_tg_id: int
    winner_nick: str
    participant_count: int
    prize_amount: int
    winner_balance_before: int
    winner_balance_after: int
    claim_token: str | None = None


@dataclass(frozen=True)
class CubeNotification:
    notification_id: int
    generation_id: int
    kind: str
    recipient_tg_id: int | None
    subscription_id: int | None
    attempts: int
    next_attempt_at: str
    winner_tg_id: int | None
    winner_nick: str | None
    participant_count: int | None
    prize_amount: int | None
    claim_token: str | None = None


@dataclass(frozen=True)
class LotteryRoundView:
    round_id: int
    starts_at: str
    closes_at: str
    ticket_price: int
    fee_bps: int
    total_tickets: int
    own_tickets: int
    gross_pool: int
    prize_amount: int
    balance: int

    @property
    def opens_at(self) -> str:
        """Совместимый UI-alias: момент открытия тиража."""
        return self.starts_at

    @property
    def prize_pool(self) -> int:
        """Совместимый UI-alias: ожидаемый приз."""
        return self.prize_amount


@dataclass(frozen=True)
class LotteryPurchaseResult:
    status: LotteryPurchaseStatus
    ticket_id: int | None
    ticket_number: int | None
    round_id: int | None
    total_tickets: int
    own_tickets: int
    gross_pool: int
    prize_amount: int
    balance: int


@dataclass(frozen=True)
class LotteryTicketCounts:
    active_tickets: int
    expired_tickets: int

    @property
    def active(self) -> int:
        return self.active_tickets

    @property
    def expired(self) -> int:
        return self.expired_tickets


@dataclass(frozen=True)
class LotterySettlement:
    round_id: int
    winner_ticket_id: int | None
    winner_ticket_number: int | None
    winner_tg_id: int | None
    ticket_count: int
    gross_pool: int
    house_cut: int
    prize_amount: int
    winner_balance_before: int | None
    winner_balance_after: int | None
    claim_token: str | None = None


@dataclass(frozen=True)
class LotteryNotification:
    notification_id: int
    round_id: int
    kind: str
    recipient_tg_id: int | None
    attempts: int
    next_attempt_at: str
    winner_ticket_id: int
    winner_ticket_number: int
    winner_tg_id: int
    winner_nick: str
    ticket_count: int
    gross_pool: int
    house_cut: int
    prize_amount: int
    claim_token: str | None = None


async def init() -> None:
    global _db, _economy_db
    if _db is not None or _economy_db is not None:
        await close()
    _db = await aiosqlite.connect(config.db_path)
    await _db.execute("PRAGMA busy_timeout = 5000")
    await _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS players (
            nick       TEXT PRIMARY KEY,
            first_seen TEXT DEFAULT (datetime('now')),
            last_seen  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS profiles (
            tg_id      INTEGER PRIMARY KEY,
            username   TEXT,
            nick       TEXT UNIQUE,
            zbucks     INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- наигранное время за день (только зарегистрированные)
        CREATE TABLE IF NOT EXISTS playtime (
            nick    TEXT,
            day     TEXT,
            seconds INTEGER DEFAULT 0,
            PRIMARY KEY (nick, day)
        );

        -- инвентарь игроков
        CREATE TABLE IF NOT EXISTS inventory (
            tg_id INTEGER,
            item  TEXT,
            qty   INTEGER DEFAULT 0,
            PRIMARY KEY (tg_id, item)
        );

        -- кулдауны мини-игр
        CREATE TABLE IF NOT EXISTS cooldowns (
            tg_id   INTEGER,
            game    TEXT,
            used_at TEXT,
            PRIMARY KEY (tg_id, game)
        );

        -- активные продажи на рынке
        CREATE TABLE IF NOT EXISTS market (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id   INTEGER,
            item    TEXT,
            price   INTEGER,
            sell_at TEXT
        );

        -- ставки: события и ставки игроков
        CREATE TABLE IF NOT EXISTS bets_events (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id     INTEGER,
            creator_name   TEXT,
            description    TEXT,
            duration_hours INTEGER,
            bet_close_at   TEXT,
            resolve_at     TEXT,
            status         TEXT,   -- betting / closed / pending / resolved
            outcome        TEXT
        );
        CREATE TABLE IF NOT EXISTS bets_stakes (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            tg_id    INTEGER,
            side     TEXT,         -- yes / no
            amount   INTEGER
        );

        -- долги (взял в долг у игрока)
        CREATE TABLE IF NOT EXISTS debts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            borrower_id INTEGER,
            lender_id   INTEGER,
            lender_nick TEXT,
            amount      INTEGER,
            created_at  TEXT,
            defaulted   INTEGER DEFAULT 0
        );

        -- статистика (счётчики и суммы по игрокам)
        CREATE TABLE IF NOT EXISTS stats (
            tg_id INTEGER,
            key   TEXT,
            value INTEGER DEFAULT 0,
            PRIMARY KEY (tg_id, key)
        );

        -- произвольные мета-значения (напр. текущий богач)
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        -- закинутые удочки (рыбалка)
        CREATE TABLE IF NOT EXISTS fishing (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id     INTEGER,
            bait_tier INTEGER,
            catch_at  TEXT
        );

        -- бизнесы игроков (tier: small/medium/large — малый/средний/крупный)
        CREATE TABLE IF NOT EXISTS businesses (
            tg_id       INTEGER,
            biz         TEXT,
            tier        TEXT,
            level       INTEGER DEFAULT 1,
            custom_name TEXT,
            paused      INTEGER DEFAULT 0,
            produce_at  TEXT,
            upkeep_at   TEXT,
            bought_at   TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (tg_id, biz)
        );

        -- отмыв грязных денег через бизнес: закладка вернётся чистой в ready_at
        CREATE TABLE IF NOT EXISTS laundering (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id    INTEGER,
            amount   INTEGER,
            ready_at TEXT
        );

        -- рыночный сток («стакан»): всё, что продали игроки, лежит тут
        -- и продаётся другим с наценкой; price — уже цена ПОКУПКИ
        CREATE TABLE IF NOT EXISTS market_stock (
            item  TEXT,
            price INTEGER,
            qty   INTEGER DEFAULT 0,
            PRIMARY KEY (item, price)
        );
        """
    )
    # миграции для уже существующей БД
    await _ensure_column("profiles", "xp", "INTEGER DEFAULT 0")
    await _ensure_column("profiles", "level", "INTEGER DEFAULT 0")
    await _ensure_column("profiles", "thefts", "INTEGER DEFAULT 0")
    await _ensure_column("profiles", "honest", "INTEGER DEFAULT 0")
    # грязные деньги (Густав Налоговик); default 0 = все текущие балансы легальны
    await _ensure_column("profiles", "dirty", "INTEGER DEFAULT 0")
    # самозанятость (оформляется через Самсунг, нужна для покупки бизнеса)
    await _ensure_column("profiles", "self_employed", "INTEGER DEFAULT 0")
    # рынок: лот может содержать несколько штук по одной цене
    await _ensure_column("market", "qty", "INTEGER DEFAULT 1")
    await _db.commit()
    await _init_lottery_schema()
    await _init_cube_schema()

    # Критичные денежные операции идут через отдельное соединение. В отличие
    # от набора helper-вызовов на общем connection, BEGIN IMMEDIATE здесь
    # действительно сериализует всю границу операции между coroutine/process.
    if config.db_path == ":memory:":
        # У двух обычных :memory: connection разные БД; сохраняем работоспособный
        # тестовый режим, всё равно сериализуя операции через economy lock.
        _economy_db = _db
    else:
        _economy_db = await aiosqlite.connect(config.db_path)
        await _economy_db.execute("PRAGMA busy_timeout = 5000")


async def close() -> None:
    """Закрыть оба SQLite-соединения после остановки фоновых задач."""
    global _db, _economy_db
    async with _economy_lock:
        economy_db = _economy_db
        main_db = _db
        _economy_db = None
        _db = None
        if economy_db is not None and economy_db is not main_db:
            await economy_db.close()
        if main_db is not None:
            await main_db.close()


async def _init_lottery_schema() -> None:
    """Идемпотентная атомарная additive-миграция таблиц лотереи."""
    statements = (
        """
        CREATE TABLE IF NOT EXISTS lottery_rounds (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            starts_at             TEXT NOT NULL,
            closes_at             TEXT NOT NULL,
            status                TEXT NOT NULL DEFAULT 'open'
                                      CHECK (status IN ('open', 'settled')),
            active_slot           INTEGER UNIQUE
                                      CHECK (active_slot IS NULL OR active_slot = 1),
            ticket_price          INTEGER NOT NULL CHECK (ticket_price > 0),
            fee_bps               INTEGER NOT NULL
                                      CHECK (fee_bps >= 0 AND fee_bps <= 10000),
            ticket_count          INTEGER,
            gross_pool            INTEGER,
            house_cut             INTEGER,
            winner_ticket_id      INTEGER,
            winner_tg_id          INTEGER,
            prize_amount          INTEGER,
            winner_balance_before INTEGER,
            winner_balance_after  INTEGER,
            settled_at            TEXT,
            tax_processed_at      TEXT,
            tax_claim_token       TEXT,
            tax_claim_until       TEXT,
            CHECK ((status = 'open' AND active_slot = 1)
                OR (status = 'settled' AND active_slot IS NULL))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS lottery_tickets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id      INTEGER NOT NULL,
            ticket_number INTEGER NOT NULL,
            tg_id         INTEGER NOT NULL,
            purchased_at  TEXT NOT NULL,
            paid_amount   INTEGER NOT NULL CHECK (paid_amount > 0),
            dirty_amount  INTEGER NOT NULL DEFAULT 0
                              CHECK (dirty_amount >= 0 AND dirty_amount <= paid_amount),
            request_key   TEXT NOT NULL UNIQUE,
            UNIQUE (round_id, ticket_number)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS lottery_notifications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id        INTEGER NOT NULL,
            kind            TEXT NOT NULL
                                CHECK (kind IN ('winner_private', 'result_public')),
            recipient_tg_id INTEGER,
            attempts        INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL,
            sent_at         TEXT,
            last_error      TEXT,
            created_at      TEXT NOT NULL,
            claim_token     TEXT,
            claim_until     TEXT,
            UNIQUE (round_id, kind)
        )
        """,
        """CREATE INDEX IF NOT EXISTS lottery_rounds_due_idx
           ON lottery_rounds (status, closes_at)""",
        """CREATE INDEX IF NOT EXISTS lottery_tickets_round_idx
           ON lottery_tickets (round_id, id)""",
        """CREATE INDEX IF NOT EXISTS lottery_tickets_owner_idx
           ON lottery_tickets (tg_id, round_id)""",
        """CREATE INDEX IF NOT EXISTS lottery_notifications_due_idx
           ON lottery_notifications (sent_at, next_attempt_at, id)""",
    )
    await _db.execute("BEGIN IMMEDIATE")
    try:
        for statement in statements:
            await _db.execute(statement)
        # Эти колонки нужны и при повторном запуске checkout, в котором
        # таблицы лотереи уже успели появиться до введения lease-claims.
        await _ensure_column("lottery_rounds", "tax_claim_token", "TEXT")
        await _ensure_column("lottery_rounds", "tax_claim_until", "TEXT")
        await _ensure_column("lottery_notifications", "claim_token", "TEXT")
        await _ensure_column("lottery_notifications", "claim_until", "TEXT")
        await _db.execute(
            """CREATE INDEX IF NOT EXISTS lottery_rounds_tax_claim_idx
               ON lottery_rounds (tax_processed_at, tax_claim_until, id)"""
        )
        await _db.execute(
            """CREATE INDEX IF NOT EXISTS lottery_notifications_claim_idx
               ON lottery_notifications (sent_at, next_attempt_at, claim_until, id)"""
        )
        await _db.commit()
    except BaseException:
        await _db.rollback()
        raise


async def _init_cube_schema() -> None:
    """Идемпотентно добавить durable-состояние общей игры «Куб»."""
    statements = (
        """
        CREATE TABLE IF NOT EXISTS cube_generations (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at            TEXT NOT NULL,
            idle_expires_at       TEXT NOT NULL,
            recruitment_started_at TEXT,
            lobby_closes_at       TEXT,
            roster_locked_at      TEXT,
            closes_at             TEXT,
            status                TEXT NOT NULL
                                      CHECK (status IN
                                        ('waiting','lobby','active','won','expired')),
            active_slot           INTEGER UNIQUE
                                      CHECK (active_slot IS NULL OR active_slot = 1),
            seed                  INTEGER NOT NULL,
            layout_version        INTEGER NOT NULL,
            size                  INTEGER NOT NULL,
            start_room_id         INTEGER NOT NULL,
            prize_room_id         INTEGER NOT NULL,
            mandatory_room_id     INTEGER NOT NULL,
            reset_minutes         INTEGER NOT NULL CHECK (reset_minutes > 0),
            lobby_seconds         INTEGER NOT NULL CHECK (lobby_seconds > 0),
            entry_cost            INTEGER NOT NULL CHECK (entry_cost > 0),
            prize_per_participant INTEGER NOT NULL
                                      CHECK (prize_per_participant > 0),
            max_participants      INTEGER NOT NULL CHECK (max_participants > 0),
            participant_count     INTEGER,
            prize_amount          INTEGER,
            winner_tg_id          INTEGER,
            winner_balance_before INTEGER,
            winner_balance_after  INTEGER,
            finished_at           TEXT,
            finish_reason         TEXT,
            tax_processed_at      TEXT,
            tax_claim_token       TEXT,
            tax_claim_until       TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cube_rooms (
            generation_id       INTEGER NOT NULL,
            room_id             INTEGER NOT NULL,
            row_no              INTEGER NOT NULL,
            column_no           INTEGER NOT NULL,
            code                TEXT NOT NULL,
            kind                TEXT NOT NULL,
            description_key     TEXT NOT NULL,
            hazard_kind         TEXT,
            required_item_key   TEXT,
            consume_qty         INTEGER NOT NULL DEFAULT 0 CHECK (consume_qty >= 0),
            is_required         INTEGER NOT NULL DEFAULT 0 CHECK (is_required IN (0,1)),
            effect_kind         TEXT,
            effect_target_room_id INTEGER,
            effect_arg          TEXT,
            revealed_at         TEXT,
            revealed_by         INTEGER,
            resolved_at         TEXT,
            resolved_by         INTEGER,
            PRIMARY KEY (generation_id, room_id),
            UNIQUE (generation_id, row_no, column_no),
            UNIQUE (generation_id, code)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cube_passages (
            generation_id INTEGER NOT NULL,
            room_a         INTEGER NOT NULL,
            room_b         INTEGER NOT NULL,
            is_extra       INTEGER NOT NULL DEFAULT 0 CHECK (is_extra IN (0,1)),
            PRIMARY KEY (generation_id, room_a, room_b),
            CHECK (room_a < room_b)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cube_runs (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            generation_id          INTEGER NOT NULL,
            tg_id                  INTEGER NOT NULL,
            entry_request_key      TEXT NOT NULL UNIQUE,
            status                 TEXT NOT NULL
                                       CHECK (status IN ('active','won','lost','expired')),
            current_room_id        INTEGER NOT NULL,
            previous_room_id       INTEGER,
            pending_hazard_room_id INTEGER,
            version                INTEGER NOT NULL DEFAULT 0,
            steps                  INTEGER NOT NULL DEFAULT 0,
            paid_amount            INTEGER NOT NULL CHECK (paid_amount >= 0),
            dirty_amount           INTEGER NOT NULL DEFAULT 0 CHECK (dirty_amount >= 0),
            entered_at             TEXT NOT NULL,
            updated_at             TEXT NOT NULL,
            won_at                 TEXT,
            UNIQUE (generation_id, tg_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cube_entry_requests (
            request_key   TEXT PRIMARY KEY,
            generation_id INTEGER NOT NULL,
            tg_id          INTEGER NOT NULL,
            status         TEXT NOT NULL,
            run_id         INTEGER,
            created_at     TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cube_observations (
            generation_id INTEGER NOT NULL,
            tg_id          INTEGER NOT NULL,
            source_room_id INTEGER NOT NULL,
            direction      TEXT NOT NULL CHECK (direction IN ('n','e','s','w')),
            target_room_id INTEGER NOT NULL,
            category       TEXT NOT NULL,
            observed_at    TEXT NOT NULL,
            PRIMARY KEY (generation_id, tg_id, source_room_id, direction)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cube_waitlist (
            id                            INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id                         INTEGER NOT NULL UNIQUE,
            requested_after_generation_id INTEGER NOT NULL,
            request_key                   TEXT NOT NULL UNIQUE,
            requested_at                  TEXT NOT NULL,
            claim_token                   TEXT,
            claim_until                   TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cube_subscription_requests (
            request_key     TEXT PRIMARY KEY,
            generation_id   INTEGER NOT NULL,
            tg_id            INTEGER NOT NULL,
            subscription_id INTEGER,
            status           TEXT NOT NULL
                                 CHECK (status IN ('active','cancelled','delivered')),
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cube_notifications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            generation_id   INTEGER NOT NULL,
            kind            TEXT NOT NULL CHECK (kind IN ('winner_public','lobby_private')),
            recipient_tg_id INTEGER,
            subscription_id INTEGER,
            status          TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','sent','cancelled','stale')),
            attempts        INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL,
            sent_at         TEXT,
            last_error      TEXT,
            created_at      TEXT NOT NULL,
            claim_token     TEXT,
            claim_until     TEXT
        )
        """,
        """CREATE UNIQUE INDEX IF NOT EXISTS cube_current_generation_idx
           ON cube_generations (active_slot) WHERE active_slot IS NOT NULL""",
        """CREATE INDEX IF NOT EXISTS cube_generations_due_idx
           ON cube_generations (active_slot, status, idle_expires_at, closes_at)""",
        """CREATE INDEX IF NOT EXISTS cube_runs_generation_idx
           ON cube_runs (generation_id, status, id)""",
        """CREATE UNIQUE INDEX IF NOT EXISTS cube_winner_notification_idx
           ON cube_notifications (generation_id, kind)
           WHERE kind = 'winner_public'""",
        """CREATE UNIQUE INDEX IF NOT EXISTS cube_lobby_notification_idx
           ON cube_notifications (generation_id, kind, recipient_tg_id)
           WHERE kind = 'lobby_private' AND recipient_tg_id IS NOT NULL""",
    )
    await _db.execute("BEGIN IMMEDIATE")
    try:
        for statement in statements:
            await _db.execute(statement)
        # Additive safety for databases created by an earlier Cube checkout.
        await _ensure_column("cube_runs", "pending_hazard_room_id", "INTEGER")
        await _ensure_column("cube_generations", "tax_claim_token", "TEXT")
        await _ensure_column("cube_generations", "tax_claim_until", "TEXT")
        await _ensure_column("cube_waitlist", "claim_token", "TEXT")
        await _ensure_column("cube_waitlist", "claim_until", "TEXT")
        await _ensure_column("cube_notifications", "claim_token", "TEXT")
        await _ensure_column("cube_notifications", "claim_until", "TEXT")
        await _db.execute(
            """CREATE INDEX IF NOT EXISTS cube_generations_tax_claim_idx
               ON cube_generations
                  (tax_processed_at, tax_claim_until, id)"""
        )
        await _db.execute(
            """CREATE INDEX IF NOT EXISTS cube_notifications_due_idx
               ON cube_notifications
                  (status, next_attempt_at, claim_until, id)"""
        )
        await _db.commit()
    except BaseException:
        await _db.rollback()
        raise


async def _ensure_column(table: str, column: str, decl: str) -> None:
    cur = await _db.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in await cur.fetchall()}
    if column not in existing:
        await _db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


async def register_seen(nick: str) -> bool:
    """Отметить, что игрок зашёл. Вернуть True, если видим его впервые."""
    cur = await _db.execute("SELECT 1 FROM players WHERE nick = ?", (nick,))
    if await cur.fetchone():
        await _db.execute(
            "UPDATE players SET last_seen = datetime('now') WHERE nick = ?", (nick,)
        )
        await _db.commit()
        return False
    await _db.execute("INSERT INTO players (nick) VALUES (?)", (nick,))
    await _db.commit()
    return True


async def create_profile(tg_id: int, username: str | None, nick: str) -> bool:
    """Создать профиль. False, если tg_id или ник уже заняты."""
    cur = await _db.execute(
        "INSERT OR IGNORE INTO profiles (tg_id, username, nick) VALUES (?, ?, ?)",
        (tg_id, username, nick),
    )
    await _db.commit()
    return cur.rowcount == 1


async def get_profile(tg_id: int) -> tuple | None:
    """Вернуть (tg_id, username, nick, zbucks, xp, level) или None."""
    cur = await _db.execute(
        "SELECT tg_id, username, nick, zbucks, xp, level FROM profiles WHERE tg_id = ?",
        (tg_id,),
    )
    return await cur.fetchone()


async def get_tg_id_by_nick(nick: str) -> int | None:
    """tg_id зарегистрированного игрока по майнкрафт-нику, иначе None."""
    cur = await _db.execute("SELECT tg_id FROM profiles WHERE nick = ?", (nick,))
    row = await cur.fetchone()
    return row[0] if row else None


async def get_profile_by_nick(nick: str) -> tuple | None:
    """(tg_id, level) зарегистрированного игрока по нику, иначе None."""
    cur = await _db.execute(
        "SELECT tg_id, level FROM profiles WHERE nick = ?", (nick,)
    )
    return await cur.fetchone()


async def add_zbucks(tg_id: int, amount: int) -> None:
    await _db.execute(
        "UPDATE profiles SET zbucks = zbucks + ? WHERE tg_id = ?", (amount, tg_id)
    )
    await _db.commit()


# --- наигранное время и опыт ---

async def add_playtime(nicks: set[str], seconds: int) -> None:
    """Прибавить `seconds` к сегодняшнему счётчику для онлайн-ников.

    Учитываются только зарегистрированные (EXISTS в profiles).
    """
    if not nicks:
        return
    day = datetime.now().date().isoformat()
    for nick in nicks:
        await _db.execute(
            """
            INSERT INTO playtime (nick, day, seconds)
            SELECT ?, ?, ? WHERE EXISTS (SELECT 1 FROM profiles WHERE nick = ?)
            ON CONFLICT (nick, day) DO UPDATE SET seconds = seconds + excluded.seconds
            """,
            (nick, day, seconds, nick),
        )
    await _db.commit()


async def get_day_playtime(day: str) -> dict[str, int]:
    """{nick: seconds} за указанный день."""
    cur = await _db.execute(
        "SELECT nick, seconds FROM playtime WHERE day = ?", (day,)
    )
    return {row[0]: row[1] for row in await cur.fetchall()}


async def all_profiles() -> list[tuple]:
    """Список (tg_id, nick, xp, level) всех профилей."""
    cur = await _db.execute("SELECT tg_id, nick, xp, level FROM profiles")
    return await cur.fetchall()


async def apply_daily_xp(tg_id: int, xp: int, level: int, zbucks_gain: int) -> None:
    await _db.execute(
        "UPDATE profiles SET xp = ?, level = ?, zbucks = zbucks + ? WHERE tg_id = ?",
        (xp, level, zbucks_gain, tg_id),
    )
    await _db.commit()


async def clear_playtime(until_day: str) -> None:
    """Удалить накопленное время по день `until_day` включительно."""
    await _db.execute("DELETE FROM playtime WHERE day <= ?", (until_day,))
    await _db.commit()


# --- Zbucks / инвентарь / кулдауны ---

# --- прятки от Густава (ключи живут тут, чтобы spend_zbucks их видел) ---
HIDE_KEY = "gustav_hide"
HIDE_CD_KEY = "gustav_hide_cd"


def hidden_meta_key(tg_id: int) -> str:
    return f"gustav_hidden:{tg_id}"


async def hidden_now(tg_id: int) -> int:
    """Сколько Z сейчас спрятано от Густава (0 — прятка не активна)."""
    return await _hidden_amount_on(_db, tg_id, datetime.now())


async def _hidden_amount_on(
    connection: aiosqlite.Connection, tg_id: int, at: datetime
) -> int:
    """Прочитать спрятанную сумму через заданное соединение/транзакцию."""
    cur = await connection.execute(
        "SELECT used_at FROM cooldowns WHERE tg_id = ? AND game = ?", (tg_id, HIDE_KEY)
    )
    row = await cur.fetchone()
    if not row or datetime.fromisoformat(row[0]) <= at:
        return 0
    cur = await connection.execute(
        "SELECT value FROM meta WHERE key = ?", (hidden_meta_key(tg_id),)
    )
    meta_row = await cur.fetchone()
    val = meta_row[0] if meta_row else None
    try:
        return int(val or 0)
    except ValueError:
        return 0


async def activate_hidden_money(
    tg_id: int,
    cap: int,
    hide_until: str,
    cooldown_until: str,
    now_iso: str | None = None,
) -> int:
    """Атомарно включить прятку и вернуть фактически спрятанную сумму.

    Ноль означает, что профиль/грязные деньги/кулдаун уже изменились после
    проверки handler. Одна writer-транзакция не даёт покупке лотерейного
    билета увидеть срок прятки без соответствующей суммы в ``meta``.
    """
    if cap <= 0:
        return 0
    current_iso = now_iso or datetime.now().isoformat()
    current = datetime.fromisoformat(current_iso)
    if datetime.fromisoformat(hide_until) <= current:
        raise ValueError("hide_until must be after now_iso")
    if datetime.fromisoformat(cooldown_until) <= current:
        raise ValueError("cooldown_until must be after now_iso")

    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT game, used_at FROM cooldowns
                   WHERE tg_id = ? AND game IN (?, ?)""",
                (tg_id, HIDE_KEY, HIDE_CD_KEY),
            )
            for key, used_at in await cur.fetchall():
                if key in (HIDE_KEY, HIDE_CD_KEY) and datetime.fromisoformat(used_at) > current:
                    await connection.rollback()
                    return 0

            cur = await connection.execute(
                "SELECT zbucks, dirty FROM profiles WHERE tg_id = ?", (tg_id,)
            )
            profile = await cur.fetchone()
            if not profile:
                await connection.rollback()
                return 0
            amount = min(cap, max(0, profile[0]), max(0, profile[1] or 0))
            if amount <= 0:
                await connection.rollback()
                return 0

            await connection.executemany(
                """INSERT INTO cooldowns (tg_id, game, used_at) VALUES (?, ?, ?)
                   ON CONFLICT (tg_id, game)
                   DO UPDATE SET used_at = excluded.used_at""",
                (
                    (tg_id, HIDE_KEY, hide_until),
                    (tg_id, HIDE_CD_KEY, cooldown_until),
                ),
            )
            await connection.execute(
                """INSERT INTO meta (key, value) VALUES (?, ?)
                   ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
                (hidden_meta_key(tg_id), str(amount)),
            )
            await connection.commit()
            return amount
        except BaseException:
            await connection.rollback()
            raise


async def spend_zbucks_traced(tg_id: int, amount: int) -> int | None:
    """Списать Zbucks и вернуть, СКОЛЬКО из списанного было грязными.

    None — денег не хватает (ничего не списано).
    Спрятанные от Густава деньги потратить нельзя — они заняты в носках.
    Из доступного первыми тратятся ГРЯЗНЫЕ (не спрятанные) — так от них
    можно избавиться, пока Густав едет с проверкой.
    """
    if amount < 0:
        raise ValueError("amount must be non-negative")
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                "SELECT zbucks, dirty FROM profiles WHERE tg_id = ?", (tg_id,)
            )
            row = await cur.fetchone()
            if not row:
                await connection.rollback()
                return None
            balance, dirty = row[0], row[1] or 0
            hidden = await _hidden_amount_on(connection, tg_id, datetime.now())
            if balance - hidden < amount:
                await connection.rollback()
                return None
            dirty_spend = min(amount, max(0, dirty - hidden))
            await connection.execute(
                """UPDATE profiles
                   SET zbucks = zbucks - ?, dirty = dirty - ?
                   WHERE tg_id = ?""",
                (amount, dirty_spend, tg_id),
            )
            await connection.commit()
            return dirty_spend
        except BaseException:
            await connection.rollback()
            raise


def _economy_connection() -> aiosqlite.Connection:
    if _economy_db is None:
        raise RuntimeError("storage.init() must be called first")
    return _economy_db


async def spend_zbucks(tg_id: int, amount: int) -> bool:
    """Списать Zbucks. False, если не хватает."""
    return await spend_zbucks_traced(tg_id, amount) is not None


# --- грязные деньги (Густав Налоговик) ---

async def get_dirty(tg_id: int) -> int:
    cur = await _db.execute("SELECT dirty FROM profiles WHERE tg_id = ?", (tg_id,))
    row = await cur.fetchone()
    return row[0] if row and row[0] else 0


async def add_dirty(tg_id: int, amount: int) -> None:
    """Пометить часть баланса грязной (не больше самого баланса)."""
    await _db.execute(
        "UPDATE profiles SET dirty = MIN(zbucks, dirty + ?) WHERE tg_id = ?",
        (amount, tg_id),
    )
    await _db.commit()


async def set_dirty(tg_id: int, value: int) -> None:
    await _db.execute("UPDATE profiles SET dirty = ? WHERE tg_id = ?", (value, tg_id))
    await _db.commit()


async def get_item_qty(tg_id: int, item: str) -> int:
    cur = await _db.execute(
        "SELECT qty FROM inventory WHERE tg_id = ? AND item = ?", (tg_id, item)
    )
    row = await cur.fetchone()
    return row[0] if row else 0


async def get_inventory(tg_id: int) -> dict[str, int]:
    cur = await _db.execute(
        "SELECT item, qty FROM inventory WHERE tg_id = ? AND qty > 0", (tg_id,)
    )
    return {row[0]: row[1] for row in await cur.fetchall()}


async def add_item(tg_id: int, item: str, qty: int = 1, max_qty: int | None = None) -> int:
    """Добавить предмет (с потолком max_qty). Вернуть новое количество."""
    if qty < 0:
        raise ValueError("qty must be non-negative")
    if max_qty is not None and max_qty < 0:
        raise ValueError("max_qty must be non-negative")
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            new = await _add_item_on(connection, tg_id, item, qty, max_qty)
            await connection.commit()
            return new
        except BaseException:
            await connection.rollback()
            raise


async def remove_item(tg_id: int, item: str, qty: int = 1) -> bool:
    """Снять qty предметов. False, если столько нет."""
    if qty < 0:
        raise ValueError("qty must be non-negative")
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            removed = await _take_item_on(connection, tg_id, item, qty)
            await connection.commit()
            return removed
        except BaseException:
            await connection.rollback()
            raise


async def _add_item_on(
    connection: aiosqlite.Connection,
    tg_id: int,
    item: str,
    qty: int,
    max_qty: int | None = None,
) -> int:
    """Connection-aware inventory upsert; caller owns the writer transaction."""
    if max_qty is None:
        await connection.execute(
            """INSERT INTO inventory (tg_id, item, qty) VALUES (?, ?, ?)
               ON CONFLICT (tg_id, item)
               DO UPDATE SET qty = inventory.qty + excluded.qty""",
            (tg_id, item, qty),
        )
    else:
        await connection.execute(
            """INSERT INTO inventory (tg_id, item, qty) VALUES (?, ?, MIN(?, ?))
               ON CONFLICT (tg_id, item)
               DO UPDATE SET qty = MIN(?, inventory.qty + excluded.qty)""",
            (tg_id, item, qty, max_qty, max_qty),
        )
    cur = await connection.execute(
        "SELECT qty FROM inventory WHERE tg_id = ? AND item = ?", (tg_id, item)
    )
    row = await cur.fetchone()
    return row[0] if row else 0


async def _has_item_on(
    connection: aiosqlite.Connection, tg_id: int, item: str, qty: int = 1
) -> bool:
    cur = await connection.execute(
        """SELECT 1 FROM inventory
           WHERE tg_id = ? AND item = ? AND qty >= ?""",
        (tg_id, item, qty),
    )
    return await cur.fetchone() is not None


async def _take_item_on(
    connection: aiosqlite.Connection, tg_id: int, item: str, qty: int = 1
) -> bool:
    """Условно снять предметы внутри уже открытой writer-транзакции."""
    if qty == 0:
        return await _has_item_on(connection, tg_id, item, 1)
    cur = await connection.execute(
        """UPDATE inventory SET qty = qty - ?
           WHERE tg_id = ? AND item = ? AND qty >= ?""",
        (qty, tg_id, item, qty),
    )
    if cur.rowcount != 1:
        return False
    await connection.execute(
        "DELETE FROM inventory WHERE tg_id = ? AND item = ? AND qty <= 0",
        (tg_id, item),
    )
    return True


# --- глобальная 24-часовая лотерея ---

def _lottery_prize(gross_pool: int, fee_bps: int) -> int:
    return gross_pool * (10_000 - fee_bps) // 10_000


async def ensure_lottery_round(
    now_iso: str,
    closes_at: str,
    ticket_price: int = 50,
    fee_bps: int = 1_000,
) -> int:
    """Вернуть открытый тираж или атомарно создать первый."""
    if ticket_price <= 0:
        raise ValueError("ticket_price must be positive")
    if not 0 <= fee_bps <= 10_000:
        raise ValueError("fee_bps must be between 0 and 10000")
    if datetime.fromisoformat(closes_at) <= datetime.fromisoformat(now_iso):
        raise ValueError("lottery closes_at must be after starts_at")

    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT id FROM lottery_rounds
                   WHERE status = 'open' AND active_slot = 1
                   ORDER BY id LIMIT 1"""
            )
            row = await cur.fetchone()
            if row:
                await connection.commit()
                return row[0]

            cur = await connection.execute(
                """INSERT INTO lottery_rounds
                   (starts_at, closes_at, status, active_slot, ticket_price, fee_bps)
                   VALUES (?, ?, 'open', 1, ?, ?)""",
                (now_iso, closes_at, ticket_price, fee_bps),
            )
            await connection.commit()
            return cur.lastrowid
        except BaseException:
            await connection.rollback()
            raise


async def get_lottery_view(
    tg_id: int, now_iso: str | None = None
) -> LotteryRoundView | None:
    """Снимок открытого тиража и участия конкретного игрока."""
    del now_iso  # дедлайн показываем даже между закрытием кассы и scheduler tick
    cur = await _db.execute(
        """SELECT r.id, r.starts_at, r.closes_at, r.ticket_price, r.fee_bps,
                  COUNT(t.id),
                  COALESCE(SUM(CASE WHEN t.tg_id = ? THEN 1 ELSE 0 END), 0),
                  COALESCE(SUM(t.paid_amount), 0),
                  p.zbucks
           FROM lottery_rounds r
           JOIN profiles p ON p.tg_id = ?
           LEFT JOIN lottery_tickets t ON t.round_id = r.id
           WHERE r.status = 'open' AND r.active_slot = 1
           GROUP BY r.id, p.zbucks
           ORDER BY r.id DESC LIMIT 1""",
        (tg_id, tg_id),
    )
    row = await cur.fetchone()
    if not row:
        return None
    gross_pool = row[7]
    return LotteryRoundView(
        round_id=row[0],
        starts_at=row[1],
        closes_at=row[2],
        ticket_price=row[3],
        fee_bps=row[4],
        total_tickets=row[5],
        own_tickets=row[6],
        gross_pool=gross_pool,
        prize_amount=_lottery_prize(gross_pool, row[4]),
        balance=row[8],
    )


async def get_lottery_ticket_counts(tg_id: int) -> LotteryTicketCounts:
    """Количество активных и навсегда сохранённых протухших билетов."""
    cur = await _db.execute(
        """SELECT
               COALESCE(SUM(CASE WHEN r.status = 'open' THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN r.status = 'settled' THEN 1 ELSE 0 END), 0)
           FROM lottery_tickets t
           JOIN lottery_rounds r ON r.id = t.round_id
           WHERE t.tg_id = ?""",
        (tg_id,),
    )
    row = await cur.fetchone()
    return LotteryTicketCounts(active_tickets=row[0], expired_tickets=row[1])


async def _lottery_purchase_snapshot(
    connection: aiosqlite.Connection,
    *,
    status: LotteryPurchaseStatus,
    round_id: int | None,
    tg_id: int,
    ticket_id: int | None = None,
    ticket_number: int | None = None,
) -> LotteryPurchaseResult:
    total_tickets = own_tickets = gross_pool = prize_amount = 0
    if round_id is not None:
        cur = await connection.execute(
            """SELECT COUNT(t.id),
                      COALESCE(SUM(CASE WHEN t.tg_id = ? THEN 1 ELSE 0 END), 0),
                      COALESCE(SUM(t.paid_amount), 0),
                      r.fee_bps
               FROM lottery_rounds r
               LEFT JOIN lottery_tickets t ON t.round_id = r.id
               WHERE r.id = ?
               GROUP BY r.id""",
            (tg_id, round_id),
        )
        aggregate = await cur.fetchone()
        if aggregate:
            total_tickets, own_tickets, gross_pool, fee_bps = aggregate
            prize_amount = _lottery_prize(gross_pool, fee_bps)

    cur = await connection.execute(
        "SELECT zbucks FROM profiles WHERE tg_id = ?", (tg_id,)
    )
    profile = await cur.fetchone()
    return LotteryPurchaseResult(
        status=status,
        ticket_id=ticket_id,
        ticket_number=ticket_number,
        round_id=round_id,
        total_tickets=total_tickets,
        own_tickets=own_tickets,
        gross_pool=gross_pool,
        prize_amount=prize_amount,
        balance=profile[0] if profile else 0,
    )


async def buy_lottery_ticket(
    round_id: int,
    tg_id: int,
    request_key: str,
    now_iso: str | None = None,
) -> LotteryPurchaseResult:
    """Атомарно списать цену и выпустить ровно один билет."""
    if not request_key:
        raise ValueError("request_key must not be empty")
    current_iso = now_iso or datetime.now().isoformat()
    current = datetime.fromisoformat(current_iso)

    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT id, ticket_number, round_id, tg_id
                   FROM lottery_tickets WHERE request_key = ?""",
                (request_key,),
            )
            replay = await cur.fetchone()
            if replay:
                result = await _lottery_purchase_snapshot(
                    connection,
                    status="duplicate",
                    round_id=replay[2],
                    tg_id=tg_id,
                    ticket_id=replay[0] if replay[3] == tg_id else None,
                    ticket_number=replay[1] if replay[3] == tg_id else None,
                )
                await connection.commit()
                return result

            cur = await connection.execute(
                """SELECT starts_at, closes_at, status, active_slot, ticket_price
                   FROM lottery_rounds WHERE id = ?""",
                (round_id,),
            )
            lottery_round = await cur.fetchone()
            if (
                not lottery_round
                or lottery_round[2] != "open"
                or lottery_round[3] != 1
                or current < datetime.fromisoformat(lottery_round[0])
                or current >= datetime.fromisoformat(lottery_round[1])
            ):
                result = await _lottery_purchase_snapshot(
                    connection, status="closed", round_id=round_id, tg_id=tg_id
                )
                await connection.rollback()
                return result

            cur = await connection.execute(
                "SELECT zbucks, dirty FROM profiles WHERE tg_id = ?", (tg_id,)
            )
            profile = await cur.fetchone()
            if not profile:
                result = await _lottery_purchase_snapshot(
                    connection, status="no_profile", round_id=round_id, tg_id=tg_id
                )
                await connection.rollback()
                return result

            balance, dirty = profile[0], profile[1] or 0
            price = lottery_round[4]
            hidden = await _hidden_amount_on(connection, tg_id, current)
            if balance - hidden < price:
                result = await _lottery_purchase_snapshot(
                    connection, status="insufficient", round_id=round_id, tg_id=tg_id
                )
                await connection.rollback()
                return result

            dirty_spend = min(price, max(0, dirty - hidden))
            cur = await connection.execute(
                """SELECT COALESCE(MAX(ticket_number), 0) + 1
                   FROM lottery_tickets WHERE round_id = ?""",
                (round_id,),
            )
            ticket_number = (await cur.fetchone())[0]
            await connection.execute(
                """UPDATE profiles
                   SET zbucks = zbucks - ?, dirty = dirty - ?
                   WHERE tg_id = ?""",
                (price, dirty_spend, tg_id),
            )
            cur = await connection.execute(
                """INSERT INTO lottery_tickets
                   (round_id, ticket_number, tg_id, purchased_at,
                    paid_amount, dirty_amount, request_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    round_id,
                    ticket_number,
                    tg_id,
                    current_iso,
                    price,
                    dirty_spend,
                    request_key,
                ),
            )
            ticket_id = cur.lastrowid
            result = await _lottery_purchase_snapshot(
                connection,
                status="ok",
                round_id=round_id,
                tg_id=tg_id,
                ticket_id=ticket_id,
                ticket_number=ticket_number,
            )
            await connection.commit()
            return result
        except BaseException:
            await connection.rollback()
            raise


async def due_lottery_round_ids(now_iso: str | None = None) -> list[int]:
    current_iso = now_iso or datetime.now().isoformat()
    cur = await _db.execute(
        """SELECT id FROM lottery_rounds
           WHERE status = 'open' AND active_slot = 1 AND closes_at <= ?
           ORDER BY id""",
        (current_iso,),
    )
    return [row[0] for row in await cur.fetchall()]


async def settle_lottery_round(
    round_id: int,
    now_iso: str,
    next_closes_at: str,
    next_ticket_price: int = 50,
    next_fee_bps: int = 1_000,
    randbelow: Callable[[int], int] = secrets.randbelow,
) -> LotterySettlement | None:
    """Exactly-once завершить тираж, выплатить приз и открыть следующий."""
    if next_ticket_price <= 0:
        raise ValueError("next_ticket_price must be positive")
    if not 0 <= next_fee_bps <= 10_000:
        raise ValueError("next_fee_bps must be between 0 and 10000")
    if datetime.fromisoformat(next_closes_at) <= datetime.fromisoformat(now_iso):
        raise ValueError("next_closes_at must be after now_iso")

    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT fee_bps FROM lottery_rounds
                   WHERE id = ? AND status = 'open' AND active_slot = 1
                     AND closes_at <= ?""",
                (round_id, now_iso),
            )
            round_row = await cur.fetchone()
            if not round_row:
                await connection.rollback()
                return None

            cur = await connection.execute(
                """SELECT COUNT(*), COALESCE(SUM(paid_amount), 0)
                   FROM lottery_tickets WHERE round_id = ?""",
                (round_id,),
            )
            ticket_count, gross_pool = await cur.fetchone()
            prize_amount = _lottery_prize(gross_pool, round_row[0])
            house_cut = gross_pool - prize_amount
            winner_ticket_id = winner_ticket_number = winner_tg_id = None
            winner_balance_before = winner_balance_after = None

            if ticket_count:
                offset = randbelow(ticket_count)
                if not 0 <= offset < ticket_count:
                    raise ValueError("randbelow returned an invalid lottery offset")
                cur = await connection.execute(
                    """SELECT id, ticket_number, tg_id
                       FROM lottery_tickets WHERE round_id = ?
                       ORDER BY id LIMIT 1 OFFSET ?""",
                    (round_id, offset),
                )
                winner = await cur.fetchone()
                if not winner:
                    raise RuntimeError("lottery winner ticket disappeared")
                winner_ticket_id, winner_ticket_number, winner_tg_id = winner
                cur = await connection.execute(
                    "SELECT zbucks FROM profiles WHERE tg_id = ?", (winner_tg_id,)
                )
                profile = await cur.fetchone()
                if not profile:
                    raise RuntimeError("lottery winner profile disappeared")
                winner_balance_before = profile[0]
                winner_balance_after = winner_balance_before + prize_amount
                await connection.execute(
                    "UPDATE profiles SET zbucks = zbucks + ? WHERE tg_id = ?",
                    (prize_amount, winner_tg_id),
                )

            cur = await connection.execute(
                """UPDATE lottery_rounds
                   SET status = 'settled', active_slot = NULL,
                       ticket_count = ?, gross_pool = ?, house_cut = ?,
                       winner_ticket_id = ?, winner_tg_id = ?, prize_amount = ?,
                       winner_balance_before = ?, winner_balance_after = ?,
                       settled_at = ?,
                       tax_processed_at = CASE WHEN ? IS NULL THEN ? ELSE NULL END
                   WHERE id = ? AND status = 'open' AND active_slot = 1""",
                (
                    ticket_count,
                    gross_pool,
                    house_cut,
                    winner_ticket_id,
                    winner_tg_id,
                    prize_amount,
                    winner_balance_before,
                    winner_balance_after,
                    now_iso,
                    winner_tg_id,
                    now_iso,
                    round_id,
                ),
            )
            if cur.rowcount != 1:
                raise RuntimeError("lottery round was settled concurrently")

            await connection.execute(
                """INSERT INTO lottery_rounds
                   (starts_at, closes_at, status, active_slot, ticket_price, fee_bps)
                   VALUES (?, ?, 'open', 1, ?, ?)""",
                (now_iso, next_closes_at, next_ticket_price, next_fee_bps),
            )
            if winner_tg_id is not None:
                await connection.executemany(
                    """INSERT INTO lottery_notifications
                       (round_id, kind, recipient_tg_id, next_attempt_at, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        (round_id, "winner_private", winner_tg_id, now_iso, now_iso),
                        (round_id, "result_public", None, now_iso, now_iso),
                    ),
                )

            result = LotterySettlement(
                round_id=round_id,
                winner_ticket_id=winner_ticket_id,
                winner_ticket_number=winner_ticket_number,
                winner_tg_id=winner_tg_id,
                ticket_count=ticket_count,
                gross_pool=gross_pool,
                house_cut=house_cut,
                prize_amount=prize_amount,
                winner_balance_before=winner_balance_before,
                winner_balance_after=winner_balance_after,
            )
            await connection.commit()
            return result
        except BaseException:
            await connection.rollback()
            raise


async def settle_due_lottery(
    now_iso: str,
    next_closes_at: str,
    next_ticket_price: int = 50,
    next_fee_bps: int = 1_000,
    randbelow: Callable[[int], int] = secrets.randbelow,
) -> LotterySettlement | None:
    due = await due_lottery_round_ids(now_iso)
    if not due:
        return None
    return await settle_lottery_round(
        due[0],
        now_iso,
        next_closes_at,
        next_ticket_price=next_ticket_price,
        next_fee_bps=next_fee_bps,
        randbelow=randbelow,
    )


def _lottery_settlement_from_row(
    row, claim_token: str | None = None
) -> LotterySettlement:
    return LotterySettlement(
        round_id=row[0],
        winner_ticket_id=row[1],
        winner_ticket_number=row[2],
        winner_tg_id=row[3],
        ticket_count=row[4] or 0,
        gross_pool=row[5] or 0,
        house_cut=row[6] or 0,
        prize_amount=row[7] or 0,
        winner_balance_before=row[8],
        winner_balance_after=row[9],
        claim_token=claim_token,
    )


async def get_lottery_settlement(round_id: int) -> LotterySettlement | None:
    cur = await _db.execute(
        """SELECT r.id, r.winner_ticket_id, t.ticket_number, r.winner_tg_id,
                  r.ticket_count, r.gross_pool, r.house_cut, r.prize_amount,
                  r.winner_balance_before, r.winner_balance_after
           FROM lottery_rounds r
           LEFT JOIN lottery_tickets t ON t.id = r.winner_ticket_id
           WHERE r.id = ? AND r.status = 'settled'""",
        (round_id,),
    )
    row = await cur.fetchone()
    return _lottery_settlement_from_row(row) if row else None


async def pending_lottery_tax() -> list[LotterySettlement]:
    cur = await _db.execute(
        """SELECT r.id, r.winner_ticket_id, t.ticket_number, r.winner_tg_id,
                  r.ticket_count, r.gross_pool, r.house_cut, r.prize_amount,
                  r.winner_balance_before, r.winner_balance_after
           FROM lottery_rounds r
           LEFT JOIN lottery_tickets t ON t.id = r.winner_ticket_id
           WHERE r.status = 'settled' AND r.winner_tg_id IS NOT NULL
             AND r.tax_processed_at IS NULL
           ORDER BY r.id"""
    )
    return [_lottery_settlement_from_row(row) for row in await cur.fetchall()]


async def claim_pending_lottery_tax(
    claim_token: str,
    now_iso: str,
    claim_until: str,
    limit: int = 20,
) -> list[LotterySettlement]:
    """Атомарно арендовать необработанные post-commit задания Густава."""
    if not claim_token:
        raise ValueError("claim_token must not be empty")
    if datetime.fromisoformat(claim_until) <= datetime.fromisoformat(now_iso):
        raise ValueError("claim_until must be after now_iso")

    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT id FROM lottery_rounds
                   WHERE status = 'settled' AND winner_tg_id IS NOT NULL
                     AND tax_processed_at IS NULL
                     AND (tax_claim_until IS NULL OR tax_claim_until <= ?)
                   ORDER BY id LIMIT ?""",
                (now_iso, max(1, limit)),
            )
            round_ids = [row[0] for row in await cur.fetchall()]
            if not round_ids:
                await connection.rollback()
                return []

            placeholders = ", ".join("?" for _ in round_ids)
            await connection.execute(
                f"""UPDATE lottery_rounds
                    SET tax_claim_token = ?, tax_claim_until = ?
                    WHERE id IN ({placeholders})
                      AND tax_processed_at IS NULL
                      AND (tax_claim_until IS NULL OR tax_claim_until <= ?)""",
                (claim_token, claim_until, *round_ids, now_iso),
            )
            cur = await connection.execute(
                f"""SELECT r.id, r.winner_ticket_id, t.ticket_number,
                            r.winner_tg_id, r.ticket_count, r.gross_pool,
                            r.house_cut, r.prize_amount,
                            r.winner_balance_before, r.winner_balance_after
                     FROM lottery_rounds r
                     LEFT JOIN lottery_tickets t ON t.id = r.winner_ticket_id
                     WHERE r.id IN ({placeholders}) AND r.tax_claim_token = ?
                     ORDER BY r.id""",
                (*round_ids, claim_token),
            )
            jobs = [
                _lottery_settlement_from_row(row, claim_token)
                for row in await cur.fetchall()
            ]
            await connection.commit()
            return jobs
        except BaseException:
            await connection.rollback()
            raise


async def mark_lottery_tax_processed(
    round_id: int,
    claim_token: str,
    processed_at: str | None = None,
) -> bool:
    """Завершить только принадлежащий вызывающему lease."""
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """UPDATE lottery_rounds
                   SET tax_processed_at = ?, tax_claim_token = NULL,
                       tax_claim_until = NULL
                   WHERE id = ? AND status = 'settled'
                     AND tax_processed_at IS NULL AND tax_claim_token = ?""",
                (
                    processed_at or datetime.now().isoformat(),
                    round_id,
                    claim_token,
                ),
            )
            await connection.commit()
            return cur.rowcount == 1
        except BaseException:
            await connection.rollback()
            raise


async def release_lottery_tax_claim(round_id: int, claim_token: str) -> bool:
    """Освободить lease после ошибки Густава, чтобы следующий tick повторил."""
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """UPDATE lottery_rounds
                   SET tax_claim_token = NULL, tax_claim_until = NULL
                   WHERE id = ? AND tax_processed_at IS NULL
                     AND tax_claim_token = ?""",
                (round_id, claim_token),
            )
            await connection.commit()
            return cur.rowcount == 1
        except BaseException:
            await connection.rollback()
            raise


async def pending_lottery_notifications(
    now_iso: str | None = None, limit: int = 20
) -> list[LotteryNotification]:
    current_iso = now_iso or datetime.now().isoformat()
    cur = await _db.execute(
        """SELECT n.id, n.round_id, n.kind, n.recipient_tg_id, n.attempts,
                  n.next_attempt_at, r.winner_ticket_id, t.ticket_number,
                  r.winner_tg_id, COALESCE(p.nick, 'Игрок'), r.ticket_count,
                  r.gross_pool, r.house_cut, r.prize_amount
           FROM lottery_notifications n
           JOIN lottery_rounds r ON r.id = n.round_id
           JOIN lottery_tickets t ON t.id = r.winner_ticket_id
           LEFT JOIN profiles p ON p.tg_id = r.winner_tg_id
           WHERE n.sent_at IS NULL AND n.next_attempt_at <= ?
             AND (n.claim_until IS NULL OR n.claim_until <= ?)
           ORDER BY n.next_attempt_at, n.id
           LIMIT ?""",
        (current_iso, current_iso, max(1, limit)),
    )
    return [LotteryNotification(*row) for row in await cur.fetchall()]


async def claim_lottery_notifications(
    claim_token: str,
    now_iso: str,
    claim_until: str,
    limit: int = 20,
) -> list[LotteryNotification]:
    """Атомарно арендовать due outbox-строки для одного worker."""
    if not claim_token:
        raise ValueError("claim_token must not be empty")
    if datetime.fromisoformat(claim_until) <= datetime.fromisoformat(now_iso):
        raise ValueError("claim_until must be after now_iso")

    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT id FROM lottery_notifications
                   WHERE sent_at IS NULL AND next_attempt_at <= ?
                     AND (claim_until IS NULL OR claim_until <= ?)
                   ORDER BY next_attempt_at, id LIMIT ?""",
                (now_iso, now_iso, max(1, limit)),
            )
            notification_ids = [row[0] for row in await cur.fetchall()]
            if not notification_ids:
                await connection.rollback()
                return []

            placeholders = ", ".join("?" for _ in notification_ids)
            await connection.execute(
                f"""UPDATE lottery_notifications
                    SET claim_token = ?, claim_until = ?
                    WHERE id IN ({placeholders}) AND sent_at IS NULL
                      AND next_attempt_at <= ?
                      AND (claim_until IS NULL OR claim_until <= ?)""",
                (
                    claim_token,
                    claim_until,
                    *notification_ids,
                    now_iso,
                    now_iso,
                ),
            )
            cur = await connection.execute(
                f"""SELECT n.id, n.round_id, n.kind, n.recipient_tg_id,
                            n.attempts, n.next_attempt_at, r.winner_ticket_id,
                            t.ticket_number, r.winner_tg_id,
                            COALESCE(p.nick, 'Игрок'), r.ticket_count,
                            r.gross_pool, r.house_cut, r.prize_amount,
                            n.claim_token
                     FROM lottery_notifications n
                     JOIN lottery_rounds r ON r.id = n.round_id
                     JOIN lottery_tickets t ON t.id = r.winner_ticket_id
                     LEFT JOIN profiles p ON p.tg_id = r.winner_tg_id
                     WHERE n.id IN ({placeholders}) AND n.claim_token = ?
                     ORDER BY n.next_attempt_at, n.id""",
                (*notification_ids, claim_token),
            )
            jobs = [LotteryNotification(*row) for row in await cur.fetchall()]
            await connection.commit()
            return jobs
        except BaseException:
            await connection.rollback()
            raise


async def mark_lottery_notification_sent(
    notification_id: int,
    claim_token: str,
    sent_at: str | None = None,
) -> bool:
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """UPDATE lottery_notifications
                   SET sent_at = ?, last_error = NULL,
                       claim_token = NULL, claim_until = NULL
                   WHERE id = ? AND sent_at IS NULL AND claim_token = ?""",
                (
                    sent_at or datetime.now().isoformat(),
                    notification_id,
                    claim_token,
                ),
            )
            await connection.commit()
            return cur.rowcount == 1
        except BaseException:
            await connection.rollback()
            raise


async def mark_lottery_notification_retry(
    notification_id: int,
    claim_token: str,
    next_attempt_at: str,
    last_error: str,
) -> bool:
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """UPDATE lottery_notifications
                   SET attempts = attempts + 1, next_attempt_at = ?, last_error = ?,
                       claim_token = NULL, claim_until = NULL
                   WHERE id = ? AND sent_at IS NULL AND claim_token = ?""",
                (
                    next_attempt_at,
                    last_error[:1000],
                    notification_id,
                    claim_token,
                ),
            )
            await connection.commit()
            return cur.rowcount == 1
        except BaseException:
            await connection.rollback()
            raise


# --- рынок ---

async def add_listing(tg_id: int, item: str, price: int, sell_at: str, qty: int = 1) -> None:
    await _db.execute(
        "INSERT INTO market (tg_id, item, price, sell_at, qty) VALUES (?, ?, ?, ?, ?)",
        (tg_id, item, price, sell_at, qty),
    )
    await _db.commit()


async def get_listings(tg_id: int) -> list[tuple]:
    """Активные продажи игрока: (item, price, sell_at, qty)."""
    cur = await _db.execute(
        "SELECT item, price, sell_at, qty FROM market WHERE tg_id = ? ORDER BY sell_at",
        (tg_id,),
    )
    return await cur.fetchall()


async def due_listings(now_iso: str) -> list[tuple]:
    """Продажи, у которых вышел срок: (id, tg_id, item, price, qty)."""
    cur = await _db.execute(
        "SELECT id, tg_id, item, price, qty FROM market WHERE sell_at <= ?", (now_iso,)
    )
    return await cur.fetchall()


async def remove_listing(listing_id: int) -> None:
    await _db.execute("DELETE FROM market WHERE id = ?", (listing_id,))
    await _db.commit()


async def active_listing_qty(tg_id: int) -> int:
    """Сколько штук у игрока сейчас в активной продаже (лимит 20)."""
    cur = await _db.execute(
        "SELECT COALESCE(SUM(qty), 0) FROM market WHERE tg_id = ?", (tg_id,)
    )
    return (await cur.fetchone())[0]


# --- рыночный сток («стакан» покупки) ---

async def add_stock(item: str, price: int, qty: int) -> None:
    await _db.execute(
        """INSERT INTO market_stock (item, price, qty) VALUES (?, ?, ?)
           ON CONFLICT (item, price) DO UPDATE SET qty = qty + excluded.qty""",
        (item, price, qty),
    )
    await _db.commit()


async def get_stock() -> list[tuple]:
    """Весь стакан: (item, price, qty), qty > 0."""
    cur = await _db.execute(
        "SELECT item, price, qty FROM market_stock WHERE qty > 0 ORDER BY item, price"
    )
    return await cur.fetchall()


async def take_stock(item: str, price: int, n: int) -> int:
    """Снять со стока до n штук. Вернуть, сколько реально сняли."""
    cur = await _db.execute(
        "SELECT qty FROM market_stock WHERE item = ? AND price = ?", (item, price)
    )
    row = await cur.fetchone()
    have = row[0] if row else 0
    taken = min(have, n)
    if taken <= 0:
        return 0
    if taken == have:
        await _db.execute(
            "DELETE FROM market_stock WHERE item = ? AND price = ?", (item, price)
        )
    else:
        await _db.execute(
            "UPDATE market_stock SET qty = qty - ? WHERE item = ? AND price = ?",
            (taken, item, price),
        )
    await _db.commit()
    return taken


# --- ставки ---

async def count_active_events() -> int:
    cur = await _db.execute("SELECT COUNT(*) FROM bets_events WHERE status != 'resolved'")
    return (await cur.fetchone())[0]


async def create_event(creator_id, creator_name, description, hours, bet_close_at, resolve_at) -> int:
    cur = await _db.execute(
        """INSERT INTO bets_events
           (creator_id, creator_name, description, duration_hours, bet_close_at, resolve_at, status)
           VALUES (?, ?, ?, ?, ?, ?, 'betting')""",
        (creator_id, creator_name, description, hours, bet_close_at, resolve_at),
    )
    await _db.commit()
    return cur.lastrowid


async def get_event(eid: int) -> tuple | None:
    cur = await _db.execute(
        """SELECT id, creator_id, creator_name, description, duration_hours,
                  bet_close_at, resolve_at, status, outcome
           FROM bets_events WHERE id = ?""",
        (eid,),
    )
    return await cur.fetchone()


async def list_active_events() -> list[tuple]:
    cur = await _db.execute(
        """SELECT id, description, duration_hours, bet_close_at, status
           FROM bets_events WHERE status != 'resolved' ORDER BY id"""
    )
    return await cur.fetchall()


async def set_event_status(eid: int, status: str) -> None:
    await _db.execute("UPDATE bets_events SET status = ? WHERE id = ?", (status, eid))
    await _db.commit()


async def resolve_event_db(eid: int, outcome: str) -> None:
    await _db.execute(
        "UPDATE bets_events SET status = 'resolved', outcome = ? WHERE id = ?", (outcome, eid)
    )
    await _db.commit()


async def events_due_close(now_iso: str) -> list[int]:
    cur = await _db.execute(
        "SELECT id FROM bets_events WHERE status = 'betting' AND bet_close_at <= ?", (now_iso,)
    )
    return [r[0] for r in await cur.fetchall()]


async def events_due_resolve(now_iso: str) -> list[int]:
    cur = await _db.execute(
        "SELECT id FROM bets_events WHERE status = 'closed' AND resolve_at <= ?", (now_iso,)
    )
    return [r[0] for r in await cur.fetchall()]


async def add_stake(eid: int, tg_id: int, side: str, amount: int) -> None:
    await _db.execute(
        "INSERT INTO bets_stakes (event_id, tg_id, side, amount) VALUES (?, ?, ?, ?)",
        (eid, tg_id, side, amount),
    )
    await _db.commit()


async def get_stake(eid: int, tg_id: int) -> tuple | None:
    cur = await _db.execute(
        "SELECT side, amount FROM bets_stakes WHERE event_id = ? AND tg_id = ?", (eid, tg_id)
    )
    return await cur.fetchone()


async def event_stakes(eid: int) -> list[tuple]:
    cur = await _db.execute(
        "SELECT tg_id, side, amount FROM bets_stakes WHERE event_id = ?", (eid,)
    )
    return await cur.fetchall()


async def event_pools(eid: int) -> tuple[int, int]:
    cur = await _db.execute(
        "SELECT side, COALESCE(SUM(amount), 0) FROM bets_stakes WHERE event_id = ? GROUP BY side",
        (eid,),
    )
    d = {s: a for s, a in await cur.fetchall()}
    return d.get("yes", 0), d.get("no", 0)


# --- долги ---

async def add_debt(borrower_id, lender_id, lender_nick, amount, created_at) -> None:
    await _db.execute(
        "INSERT INTO debts (borrower_id, lender_id, lender_nick, amount, created_at) VALUES (?, ?, ?, ?, ?)",
        (borrower_id, lender_id, lender_nick, amount, created_at),
    )
    await _db.commit()


async def get_debts(borrower_id: int) -> list[tuple]:
    cur = await _db.execute(
        "SELECT id, lender_id, lender_nick, amount, defaulted FROM debts WHERE borrower_id = ? ORDER BY id",
        (borrower_id,),
    )
    return await cur.fetchall()


async def get_debt(did: int) -> tuple | None:
    cur = await _db.execute(
        "SELECT id, borrower_id, lender_id, lender_nick, amount FROM debts WHERE id = ?", (did,)
    )
    return await cur.fetchone()


async def remove_debt(did: int) -> None:
    await _db.execute("DELETE FROM debts WHERE id = ?", (did,))
    await _db.commit()


async def total_debt(borrower_id: int) -> int:
    cur = await _db.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM debts WHERE borrower_id = ?", (borrower_id,)
    )
    return (await cur.fetchone())[0]


async def distinct_debtors() -> list[int]:
    cur = await _db.execute("SELECT DISTINCT borrower_id FROM debts")
    return [r[0] for r in await cur.fetchall()]


async def debts_to_default(cutoff_iso: str) -> list[tuple]:
    cur = await _db.execute(
        "SELECT id, borrower_id, lender_nick, amount FROM debts WHERE created_at <= ? AND defaulted = 0",
        (cutoff_iso,),
    )
    return await cur.fetchall()


async def mark_debt_defaulted(did: int) -> None:
    await _db.execute("UPDATE debts SET defaulted = 1 WHERE id = ?", (did,))
    await _db.commit()


# --- статусы/кулдауны по ключу (срок хранится в cooldowns.used_at) ---

async def set_cooldown_until(tg_id: int, key: str, until_iso: str) -> None:
    await _db.execute(
        """INSERT INTO cooldowns (tg_id, game, used_at) VALUES (?, ?, ?)
           ON CONFLICT (tg_id, game) DO UPDATE SET used_at = excluded.used_at""",
        (tg_id, key, until_iso),
    )
    await _db.commit()


async def cooldown_left_secs(tg_id: int, key: str) -> int:
    cur = await _db.execute(
        "SELECT used_at FROM cooldowns WHERE tg_id = ? AND game = ?", (tg_id, key)
    )
    row = await cur.fetchone()
    if not row:
        return 0
    return max(0, int((datetime.fromisoformat(row[0]) - datetime.now()).total_seconds()))


async def clear_status(tg_id: int, key: str) -> None:
    await _db.execute("DELETE FROM cooldowns WHERE tg_id = ? AND game = ?", (tg_id, key))
    await _db.commit()


async def set_honest(tg_id: int, val: bool) -> None:
    await _db.execute("UPDATE profiles SET honest = ? WHERE tg_id = ?", (1 if val else 0, tg_id))
    await _db.commit()


async def is_honest(tg_id: int) -> bool:
    cur = await _db.execute("SELECT honest FROM profiles WHERE tg_id = ?", (tg_id,))
    row = await cur.fetchone()
    return bool(row and row[0])


async def expired_statuses(key: str, now_iso: str) -> list[int]:
    """Кому пора снять статус `key` (срок вышел, но запись ещё есть)."""
    cur = await _db.execute(
        "SELECT tg_id FROM cooldowns WHERE game = ? AND used_at <= ?", (key, now_iso)
    )
    return [r[0] for r in await cur.fetchall()]


# --- статистика ---

async def bump(tg_id: int, key: str, amount: int = 1) -> None:
    await _db.execute(
        """INSERT INTO stats (tg_id, key, value) VALUES (?, ?, ?)
           ON CONFLICT (tg_id, key) DO UPDATE SET value = value + excluded.value""",
        (tg_id, key, amount),
    )
    await _db.commit()


async def stat_sum(key: str) -> int:
    cur = await _db.execute("SELECT COALESCE(SUM(value), 0) FROM stats WHERE key = ?", (key,))
    return (await cur.fetchone())[0]


async def stat_top(key: str) -> tuple | None:
    """Лидер по ключу: (nick, value) или None."""
    cur = await _db.execute(
        """SELECT p.nick, s.value FROM stats s JOIN profiles p ON p.tg_id = s.tg_id
           WHERE s.key = ? AND s.value > 0 ORDER BY s.value DESC LIMIT 1""",
        (key,),
    )
    return await cur.fetchone()


async def player_stat(tg_id: int, key: str) -> int:
    cur = await _db.execute(
        "SELECT value FROM stats WHERE tg_id = ? AND key = ?", (tg_id, key)
    )
    row = await cur.fetchone()
    return row[0] if row else 0


# --- мета / богатейший ---

async def get_meta(key: str) -> str | None:
    cur = await _db.execute("SELECT value FROM meta WHERE key = ?", (key,))
    row = await cur.fetchone()
    return row[0] if row else None


async def set_meta(key: str, value: str) -> None:
    await _db.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await _db.commit()


async def richest_player() -> tuple | None:
    """(tg_id, nick, zbucks) с наибольшим балансом."""
    cur = await _db.execute(
        "SELECT tg_id, nick, zbucks FROM profiles ORDER BY zbucks DESC, tg_id ASC LIMIT 1"
    )
    return await cur.fetchone()


async def item_owners(item: str, exclude_tg_id: int) -> list[tuple]:
    """Другие игроки, у кого есть предмет: [(tg_id, nick)]."""
    cur = await _db.execute(
        """SELECT i.tg_id, p.nick FROM inventory i JOIN profiles p ON p.tg_id = i.tg_id
           WHERE i.item = ? AND i.qty > 0 AND i.tg_id != ? ORDER BY p.nick""",
        (item, exclude_tg_id),
    )
    return await cur.fetchall()


# --- рыбалка ---

async def cast_rod(tg_id: int, bait_tier: int, catch_at: str) -> None:
    await _db.execute(
        "INSERT INTO fishing (tg_id, bait_tier, catch_at) VALUES (?, ?, ?)",
        (tg_id, bait_tier, catch_at),
    )
    await _db.commit()


async def active_cast(tg_id: int) -> tuple | None:
    """(bait_tier, catch_at) активной удочки или None."""
    cur = await _db.execute(
        "SELECT bait_tier, catch_at FROM fishing WHERE tg_id = ? ORDER BY id LIMIT 1", (tg_id,)
    )
    return await cur.fetchone()


async def due_casts(now_iso: str) -> list[tuple]:
    cur = await _db.execute(
        "SELECT id, tg_id, bait_tier FROM fishing WHERE catch_at <= ?", (now_iso,)
    )
    return await cur.fetchall()


async def remove_cast(cast_id: int) -> None:
    await _db.execute("DELETE FROM fishing WHERE id = ?", (cast_id,))
    await _db.commit()


async def get_cooldown(tg_id: int, game: str) -> str | None:
    cur = await _db.execute(
        "SELECT used_at FROM cooldowns WHERE tg_id = ? AND game = ?", (tg_id, game)
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def set_cooldown(tg_id: int, game: str) -> None:
    now = datetime.now().isoformat()
    await _db.execute(
        """
        INSERT INTO cooldowns (tg_id, game, used_at) VALUES (?, ?, ?)
        ON CONFLICT (tg_id, game) DO UPDATE SET used_at = excluded.used_at
        """,
        (tg_id, game, now),
    )
    await _db.commit()


async def reset_all_cooldowns() -> int:
    """Сбросить кулдауны по играм у всех. Вернуть число удалённых записей."""
    cur = await _db.execute("DELETE FROM cooldowns")
    await _db.commit()
    return cur.rowcount


async def clear_inventory(tg_id: int) -> int:
    """Удалить все предметы игрока. Вернуть число удалённых записей."""
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                "DELETE FROM inventory WHERE tg_id = ?", (tg_id,)
            )
            await connection.commit()
            return cur.rowcount
        except BaseException:
            await connection.rollback()
            raise


# --- самозанятость и бизнесы ---

async def is_self_employed(tg_id: int) -> bool:
    cur = await _db.execute("SELECT self_employed FROM profiles WHERE tg_id = ?", (tg_id,))
    row = await cur.fetchone()
    return bool(row and row[0])


async def set_self_employed(tg_id: int) -> None:
    await _db.execute("UPDATE profiles SET self_employed = 1 WHERE tg_id = ?", (tg_id,))
    await _db.commit()


async def self_employed_ids() -> list[int]:
    cur = await _db.execute("SELECT tg_id FROM profiles WHERE self_employed = 1")
    return [r[0] for r in await cur.fetchall()]


async def create_business(tg_id: int, biz: str, tier: str,
                          produce_at: str, upkeep_at: str) -> bool:
    """Создать бизнес. False — такой у игрока уже есть."""
    cur = await _db.execute(
        """INSERT OR IGNORE INTO businesses
           (tg_id, biz, tier, produce_at, upkeep_at)
           VALUES (?, ?, ?, ?, ?)""",
        (tg_id, biz, tier, produce_at, upkeep_at),
    )
    await _db.commit()
    return cur.rowcount == 1


async def get_business(tg_id: int, biz: str) -> tuple | None:
    """(tier, level, custom_name, paused) или None."""
    cur = await _db.execute(
        "SELECT tier, level, custom_name, paused FROM businesses WHERE tg_id = ? AND biz = ?",
        (tg_id, biz),
    )
    return await cur.fetchone()


async def set_business_name(tg_id: int, biz: str, name: str) -> None:
    await _db.execute(
        "UPDATE businesses SET custom_name = ? WHERE tg_id = ? AND biz = ?",
        (name, tg_id, biz),
    )
    await _db.commit()


async def set_business_level(tg_id: int, biz: str, level: int) -> None:
    await _db.execute(
        "UPDATE businesses SET level = ? WHERE tg_id = ? AND biz = ?",
        (level, tg_id, biz),
    )
    await _db.commit()


async def set_business_paused(tg_id: int, biz: str, paused: bool) -> None:
    await _db.execute(
        "UPDATE businesses SET paused = ? WHERE tg_id = ? AND biz = ?",
        (1 if paused else 0, tg_id, biz),
    )
    await _db.commit()


async def due_production(now_iso: str) -> list[tuple]:
    """Бизнесы, которым пора выдать продукцию: (tg_id, biz, level, custom_name)."""
    cur = await _db.execute(
        """SELECT tg_id, biz, level, custom_name FROM businesses
           WHERE produce_at <= ? AND paused = 0""",
        (now_iso,),
    )
    return await cur.fetchall()


async def set_produce_at(tg_id: int, biz: str, next_iso: str) -> None:
    await _db.execute(
        "UPDATE businesses SET produce_at = ? WHERE tg_id = ? AND biz = ?",
        (next_iso, tg_id, biz),
    )
    await _db.commit()


async def due_upkeep(now_iso: str) -> list[tuple]:
    """Бизнесы, которым пора списать содержание: (tg_id, biz, level, custom_name, paused)."""
    cur = await _db.execute(
        """SELECT tg_id, biz, level, custom_name, paused FROM businesses
           WHERE upkeep_at <= ?""",
        (now_iso,),
    )
    return await cur.fetchall()


async def set_upkeep_at(tg_id: int, biz: str, next_iso: str) -> None:
    await _db.execute(
        "UPDATE businesses SET upkeep_at = ? WHERE tg_id = ? AND biz = ?",
        (next_iso, tg_id, biz),
    )
    await _db.commit()


# --- отмыв грязных денег ---

async def add_laundering(tg_id: int, amount: int, ready_at: str) -> None:
    await _db.execute(
        "INSERT INTO laundering (tg_id, amount, ready_at) VALUES (?, ?, ?)",
        (tg_id, amount, ready_at),
    )
    await _db.commit()


async def laundering_active_sum(tg_id: int) -> int:
    """Сколько Z сейчас в стирке у игрока."""
    cur = await _db.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM laundering WHERE tg_id = ?", (tg_id,)
    )
    return (await cur.fetchone())[0]


async def get_launderings(tg_id: int) -> list[tuple]:
    """Активные закладки игрока: (amount, ready_at)."""
    cur = await _db.execute(
        "SELECT amount, ready_at FROM laundering WHERE tg_id = ? ORDER BY ready_at", (tg_id,)
    )
    return await cur.fetchall()


async def due_laundering(now_iso: str) -> list[tuple]:
    """Закладки, которые пора вернуть чистыми: (id, tg_id, amount)."""
    cur = await _db.execute(
        "SELECT id, tg_id, amount FROM laundering WHERE ready_at <= ?", (now_iso,)
    )
    return await cur.fetchall()


async def remove_laundering(lid: int) -> None:
    await _db.execute("DELETE FROM laundering WHERE id = ?", (lid,))
    await _db.commit()


# --- воровство ---

async def get_thefts(tg_id: int) -> int:
    cur = await _db.execute("SELECT thefts FROM profiles WHERE tg_id = ?", (tg_id,))
    row = await cur.fetchone()
    return row[0] if row and row[0] is not None else 0


async def add_theft(tg_id: int) -> None:
    await _db.execute("UPDATE profiles SET thefts = thefts + 1 WHERE tg_id = ?", (tg_id,))
    await _db.commit()


async def random_target(exclude_tg_id: int) -> tuple | None:
    """Случайный другой игрок: (tg_id, nick, zbucks) или None."""
    cur = await _db.execute(
        "SELECT tg_id, nick, zbucks FROM profiles WHERE tg_id != ? ORDER BY RANDOM() LIMIT 1",
        (exclude_tg_id,),
    )
    return await cur.fetchone()


async def list_other_profiles(exclude_tg_id: int) -> list[tuple]:
    """Все другие игроки: [(tg_id, nick, zbucks)]."""
    cur = await _db.execute(
        "SELECT tg_id, nick, zbucks FROM profiles WHERE tg_id != ? ORDER BY nick",
        (exclude_tg_id,),
    )
    return await cur.fetchall()


async def set_theft_cooldown(tg_id: int, hours: float) -> None:
    """Положить кулдаун воровства: хранит время готовности (expiry)."""
    from datetime import timedelta
    until = (datetime.now() + timedelta(hours=hours)).isoformat()
    await _db.execute(
        """
        INSERT INTO cooldowns (tg_id, game, used_at) VALUES (?, 'theft', ?)
        ON CONFLICT (tg_id, game) DO UPDATE SET used_at = excluded.used_at
        """,
        (tg_id, until),
    )
    await _db.commit()


async def theft_cooldown_left(tg_id: int) -> int:
    """Сколько секунд до готовности воровства (0 — готов)."""
    cur = await _db.execute(
        "SELECT used_at FROM cooldowns WHERE tg_id = ? AND game = 'theft'", (tg_id,)
    )
    row = await cur.fetchone()
    if not row:
        return 0
    left = (datetime.fromisoformat(row[0]) - datetime.now()).total_seconds()
    return max(0, int(left))


# --- глобальный текстовый лабиринт «Куб» ---

_CUBE_DIRECTIONS = ("n", "e", "s", "w")
_CUBE_DIRECTION_DELTAS = {
    "n": (-1, 0),
    "e": (0, 1),
    "s": (1, 0),
    "w": (0, -1),
}


def _cube_effective_now(clock: Callable[[], datetime] | None) -> datetime:
    """Снять clock внутри writer-lock; это часть concurrency-контракта Куба."""
    value = clock() if clock is not None else datetime.utcnow()
    if not isinstance(value, datetime):
        raise TypeError("cube clock must return datetime")
    return value


def _cube_settings() -> tuple[int, int, int, int, int]:
    return (
        config.cube_reset_minutes,
        config.cube_lobby_seconds,
        config.cube_entry_cost,
        config.cube_prize_per_participant,
        config.cube_max_participants,
    )


def _cube_room_attr(room: object, name: str, default=None):
    if isinstance(room, dict):
        return room.get(name, default)
    return getattr(room, name, default)


async def _insert_cube_generation_on(
    connection: aiosqlite.Connection,
    spec: object,
    current: datetime,
) -> int:
    """Сохранить полностью materialized duck-typed CubeSpec."""
    reset_minutes, lobby_seconds, entry_cost, prize_per, max_players = (
        _cube_settings()
    )
    if reset_minutes <= 0 or lobby_seconds <= 0 or entry_cost <= 0 or prize_per <= 0:
        raise ValueError("cube settings must be positive")
    if lobby_seconds >= reset_minutes * 60:
        raise ValueError("cube lobby must be shorter than the generation lifetime")
    if not 1 <= max_players <= 16:
        raise ValueError("cube max participants must be between 1 and 16")

    rooms = tuple(_cube_room_attr(spec, "rooms", ()))
    passages = tuple(_cube_room_attr(spec, "passages", ()))
    size = int(_cube_room_attr(spec, "size", 4))
    if size <= 0 or len(rooms) != size * size:
        raise ValueError("cube spec must contain size squared rooms")
    room_ids = {int(_cube_room_attr(room, "room_id")) for room in rooms}
    start_room_id = int(_cube_room_attr(spec, "start_room_id"))
    prize_room_id = int(_cube_room_attr(spec, "prize_room_id"))
    mandatory_room_id = int(_cube_room_attr(spec, "mandatory_room_id"))
    if not {start_room_id, prize_room_id, mandatory_room_id} <= room_ids:
        raise ValueError("cube spec references an unknown special room")

    now_iso = current.isoformat()
    idle_expires_at = (current + timedelta(minutes=reset_minutes)).isoformat()
    cur = await connection.execute(
        """INSERT INTO cube_generations
           (created_at, idle_expires_at, status, active_slot, seed,
            layout_version, size, start_room_id, prize_room_id,
            mandatory_room_id, reset_minutes, lobby_seconds, entry_cost,
            prize_per_participant, max_participants)
           VALUES (?, ?, 'waiting', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            now_iso,
            idle_expires_at,
            int(_cube_room_attr(spec, "seed")),
            int(_cube_room_attr(spec, "layout_version", 1)),
            size,
            start_room_id,
            prize_room_id,
            mandatory_room_id,
            reset_minutes,
            lobby_seconds,
            entry_cost,
            prize_per,
            max_players,
        ),
    )
    generation_id = cur.lastrowid
    await connection.executemany(
        """INSERT INTO cube_rooms
           (generation_id, room_id, row_no, column_no, code, kind,
            description_key, hazard_kind, required_item_key, consume_qty,
            is_required, effect_kind, effect_target_room_id, effect_arg)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        tuple(
            (
                generation_id,
                int(_cube_room_attr(room, "room_id")),
                int(_cube_room_attr(room, "row")),
                int(_cube_room_attr(room, "column")),
                str(_cube_room_attr(room, "code")),
                str(_cube_room_attr(room, "kind")),
                str(_cube_room_attr(room, "description_key")),
                _cube_room_attr(room, "hazard_kind"),
                _cube_room_attr(room, "required_item_key"),
                int(_cube_room_attr(room, "consume_qty", 0) or 0),
                int(bool(_cube_room_attr(room, "is_required", False))),
                _cube_room_attr(room, "effect_kind"),
                _cube_room_attr(room, "effect_target_room_id"),
                (
                    None
                    if _cube_room_attr(room, "effect_arg") is None
                    else str(_cube_room_attr(room, "effect_arg"))
                ),
            )
            for room in rooms
        ),
    )
    passage_rows = []
    for passage in passages:
        room_a = int(_cube_room_attr(passage, "room_a"))
        room_b = int(_cube_room_attr(passage, "room_b"))
        if room_a > room_b:
            room_a, room_b = room_b, room_a
        if room_a == room_b or room_a not in room_ids or room_b not in room_ids:
            raise ValueError("cube passage references invalid rooms")
        passage_rows.append(
            (
                generation_id,
                room_a,
                room_b,
                int(bool(_cube_room_attr(passage, "is_extra", False))),
            )
        )
    await connection.executemany(
        """INSERT INTO cube_passages
           (generation_id, room_a, room_b, is_extra) VALUES (?, ?, ?, ?)""",
        tuple(passage_rows),
    )

    # Новый waiting-Куб порождает durable invite, но подписка удалится только
    # после подтверждённой отправки worker-ом.
    await connection.execute(
        """INSERT OR IGNORE INTO cube_notifications
           (generation_id, kind, recipient_tg_id, subscription_id,
            next_attempt_at, created_at)
           SELECT ?, 'lobby_private', tg_id, id, ?, ?
           FROM cube_waitlist WHERE requested_after_generation_id < ?""",
        (generation_id, now_iso, now_iso, generation_id),
    )
    return generation_id


async def _lock_cube_roster_on(
    connection: aiosqlite.Connection, generation_id: int, now_iso: str
) -> tuple[int, int]:
    cur = await connection.execute(
        """SELECT COUNT(*) FROM cube_runs
           WHERE generation_id = ? AND status = 'active'""",
        (generation_id,),
    )
    participant_count = (await cur.fetchone())[0]
    cur = await connection.execute(
        """SELECT prize_per_participant FROM cube_generations WHERE id = ?""",
        (generation_id,),
    )
    row = await cur.fetchone()
    if not row:
        raise RuntimeError("cube generation disappeared")
    prize_amount = participant_count * row[0]
    await connection.execute(
        """UPDATE cube_generations
           SET status = CASE WHEN status = 'lobby' THEN 'active' ELSE status END,
               roster_locked_at = COALESCE(roster_locked_at, ?),
               participant_count = COALESCE(participant_count, ?),
               prize_amount = COALESCE(prize_amount, ?)
           WHERE id = ?""",
        (now_iso, participant_count, prize_amount, generation_id),
    )
    return participant_count, prize_amount


async def _advance_cube_lifecycle_on(
    connection: aiosqlite.Connection,
    current: datetime,
    next_spec: object,
) -> CubeLifecycleResult:
    now_iso = current.isoformat()
    cur = await connection.execute(
        """SELECT id, status, idle_expires_at, lobby_closes_at, closes_at
           FROM cube_generations WHERE active_slot = 1
           ORDER BY id DESC LIMIT 1"""
    )
    row = await cur.fetchone()
    if not row:
        generation_id = await _insert_cube_generation_on(connection, next_spec, current)
        return CubeLifecycleResult(generation_id, "waiting", True, None)

    generation_id, status, idle_expires_at, lobby_closes_at, closes_at = row
    due = (
        status == "waiting"
        and datetime.fromisoformat(idle_expires_at) <= current
    ) or (
        status in ("lobby", "active")
        and closes_at is not None
        and datetime.fromisoformat(closes_at) <= current
    )
    if due:
        reason = "idle_expired" if status == "waiting" else "timeout"
        if status in ("lobby", "active"):
            # A long downtime may skip the normal lobby-lock tick entirely.
            # Preserve the paid roster/jackpot snapshot before expiring runs.
            await _lock_cube_roster_on(connection, generation_id, now_iso)
        await connection.execute(
            """UPDATE cube_generations
               SET status = 'expired', active_slot = NULL, finished_at = ?,
                   finish_reason = ?, tax_processed_at = ?
               WHERE id = ? AND active_slot = 1""",
            (now_iso, reason, now_iso, generation_id),
        )
        await connection.execute(
            """UPDATE cube_runs SET status = 'expired', updated_at = ?
               WHERE generation_id = ? AND status = 'active'""",
            (now_iso, generation_id),
        )
        new_id = await _insert_cube_generation_on(connection, next_spec, current)
        return CubeLifecycleResult(new_id, "waiting", True, generation_id)

    if (
        status == "lobby"
        and lobby_closes_at is not None
        and datetime.fromisoformat(lobby_closes_at) <= current
    ):
        await _lock_cube_roster_on(connection, generation_id, now_iso)
        return CubeLifecycleResult(generation_id, "active", True, None)

    return CubeLifecycleResult(generation_id, status, False, None)


async def advance_cube_lifecycle(
    next_spec: object, *, clock: Callable[[], datetime] | None = None
) -> CubeLifecycleResult:
    """Закрыть due-поколение/набор и гарантировать одно текущее поколение."""
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            current = _cube_effective_now(clock)
            result = await _advance_cube_lifecycle_on(connection, current, next_spec)
            await connection.commit()
            return result
        except BaseException:
            await connection.rollback()
            raise


async def bootstrap_cube(
    next_spec: object, *, clock: Callable[[], datetime] | None = None
) -> CubeLifecycleResult:
    """Startup-вариант lifecycle; сохраняет тот же атомарный контракт."""
    return await advance_cube_lifecycle(next_spec, clock=clock)


async def get_current_cube_generation_id() -> int | None:
    cur = await _db.execute(
        "SELECT id FROM cube_generations WHERE active_slot = 1 ORDER BY id DESC LIMIT 1"
    )
    row = await cur.fetchone()
    return row[0] if row else None


def _cube_category(kind: str, effect_kind: str | None = None) -> str:
    if kind == "prize":
        # Looking must never identify the winning room.
        return "unreadable"
    if kind == "hazard":
        return "hazard"
    if kind == "anomaly" or effect_kind:
        return "anomaly"
    return "quiet"


async def _cube_target_on(
    connection: aiosqlite.Connection,
    generation_id: int,
    source_room_id: int,
    direction: str,
):
    if direction not in _CUBE_DIRECTION_DELTAS:
        return None
    cur = await connection.execute(
        """SELECT room_id, row_no, column_no FROM cube_rooms
           WHERE generation_id = ? AND room_id = ?""",
        (generation_id, source_room_id),
    )
    source = await cur.fetchone()
    if not source:
        return None
    delta_row, delta_column = _CUBE_DIRECTION_DELTAS[direction]
    target_row = source[1] + delta_row
    target_column = source[2] + delta_column
    cur = await connection.execute(
        """SELECT r.room_id, r.code, r.kind, r.description_key,
                  r.hazard_kind, r.required_item_key, r.consume_qty,
                  r.effect_kind, r.effect_target_room_id, r.effect_arg,
                  r.revealed_at, r.resolved_at
           FROM cube_rooms r
           JOIN cube_passages p
             ON p.generation_id = r.generation_id
            AND ((p.room_a = ? AND p.room_b = r.room_id)
              OR (p.room_b = ? AND p.room_a = r.room_id))
           WHERE r.generation_id = ? AND r.row_no = ? AND r.column_no = ?""",
        (
            source_room_id,
            source_room_id,
            generation_id,
            target_row,
            target_column,
        ),
    )
    return await cur.fetchone()


async def get_cube_view(
    tg_id: int, generation_id: int | None = None
) -> CubeView | None:
    """Read-only снимок поколения и личной позиции; lifecycle не продвигает."""
    params: tuple = ()
    where = "active_slot = 1"
    if generation_id is not None:
        where = "id = ?"
        params = (generation_id,)
    cur = await _db.execute(
        f"""SELECT id, status, created_at, idle_expires_at, lobby_closes_at,
                   closes_at, roster_locked_at, entry_cost,
                   prize_per_participant, max_participants,
                   participant_count, prize_amount
            FROM cube_generations WHERE {where}
            ORDER BY id DESC LIMIT 1""",
        params,
    )
    generation = await cur.fetchone()
    if not generation:
        return None
    gen_id = generation[0]
    cur = await _db.execute(
        "SELECT zbucks FROM profiles WHERE tg_id = ?", (tg_id,)
    )
    profile = await cur.fetchone()
    cur = await _db.execute(
        """SELECT id, status, version, current_room_id, pending_hazard_room_id
           FROM cube_runs WHERE generation_id = ? AND tg_id = ?""",
        (gen_id, tg_id),
    )
    run = await cur.fetchone()
    cur = await _db.execute(
        """SELECT COUNT(*) FROM cube_runs
           WHERE generation_id = ? AND status IN ('active','won','lost')""",
        (gen_id,),
    )
    live_count = (await cur.fetchone())[0]
    participant_count = generation[10] if generation[10] is not None else live_count
    prize_amount = (
        generation[11]
        if generation[11] is not None
        else participant_count * generation[8]
    )
    cur = await _db.execute(
        "SELECT id, requested_after_generation_id FROM cube_waitlist WHERE tg_id = ?",
        (tg_id,),
    )
    subscription = await cur.fetchone()

    room = pending = None
    directions: list[CubeDirectionView] = []
    explored_count = 0
    if run:
        cur = await _db.execute(
            """SELECT r.room_id, r.code, r.kind, r.description_key,
                      r.effect_kind, r.effect_arg, r.hazard_kind, r.resolved_at,
                      p.nick
               FROM cube_rooms r
               LEFT JOIN profiles p ON p.tg_id = r.resolved_by
               WHERE r.generation_id = ? AND r.room_id = ?""",
            (gen_id, run[3]),
        )
        room = await cur.fetchone()
        if run[4] is not None:
            cur = await _db.execute(
                """SELECT room_id, hazard_kind, required_item_key, consume_qty,
                          resolved_at
                   FROM cube_rooms WHERE generation_id = ? AND room_id = ?""",
                (gen_id, run[4]),
            )
            pending = await cur.fetchone()
            if pending and pending[4] is not None:
                pending = None
        cur = await _db.execute(
            """SELECT COUNT(*) FROM cube_rooms
               WHERE generation_id = ? AND revealed_at IS NOT NULL""",
            (gen_id,),
        )
        explored_count = (await cur.fetchone())[0]
        for direction in _CUBE_DIRECTIONS:
            target = await _cube_target_on(_db, gen_id, run[3], direction)
            if not target:
                directions.append(CubeDirectionView(direction, False))
                continue
            observation = None
            if target[10] is None:
                cur = await _db.execute(
                    """SELECT category FROM cube_observations
                       WHERE generation_id = ? AND tg_id = ?
                         AND source_room_id = ? AND direction = ?""",
                    (gen_id, tg_id, run[3], direction),
                )
                observation = await cur.fetchone()
            # Тёмная камера оставляет сами двери доступными, но глушит коды и
            # категории соседей на текущем экране.
            dark_room = bool(room and room[4] == "dark")
            known = target[10] is not None and not dark_room
            category = (
                _cube_category(target[2], target[7])
                if known
                else observation[0] if observation and not dark_room else None
            )
            directions.append(
                CubeDirectionView(
                    direction=direction,
                    exists=True,
                    room_id=target[0],
                    room_code=target[1] if known else None,
                    category=category,
                    hazard_active=bool(
                        category == "hazard" and target[11] is None
                    ),
                )
            )

    return CubeView(
        generation_id=gen_id,
        generation_status=generation[1],
        created_at=generation[2],
        idle_expires_at=generation[3],
        lobby_closes_at=generation[4],
        closes_at=generation[5],
        roster_locked=generation[6] is not None,
        participant_count=participant_count,
        prize_amount=prize_amount,
        entry_cost=generation[7],
        prize_per_participant=generation[8],
        max_participants=generation[9],
        balance=profile[0] if profile else None,
        run_id=run[0] if run else None,
        run_status=run[1] if run else None,
        run_version=run[2] if run else None,
        current_room_id=run[3] if run else None,
        room_code=room[1] if room else None,
        room_kind=room[2] if room else None,
        room_description_key=room[3] if room else None,
        room_effect_kind=room[4] if room else None,
        room_effect_arg=room[5] if room else None,
        room_hazard_kind=room[6] if room else None,
        room_hazard_resolved=bool(
            room and room[6] is not None and room[7] is not None
        ),
        room_resolved_by_nick=(room[8] if room and room[6] is not None else None),
        subscription_id=subscription[0] if subscription else None,
        subscription_generation_id=subscription[1] if subscription else None,
        pending_hazard_room_id=pending[0] if pending else None,
        pending_hazard_kind=pending[1] if pending else None,
        pending_required_item_key=pending[2] if pending else None,
        pending_consume_qty=pending[3] if pending else 0,
        explored_count=explored_count,
        directions=tuple(directions),
    )


async def _cube_enter_snapshot_on(
    connection: aiosqlite.Connection,
    *,
    status: CubeEnterStatus,
    generation_id: int,
    tg_id: int,
    run_id: int | None = None,
) -> CubeEnterResult:
    version = None
    if run_id is not None:
        cur = await connection.execute(
            "SELECT version FROM cube_runs WHERE id = ?", (run_id,)
        )
        row = await cur.fetchone()
        version = row[0] if row else None
    cur = await connection.execute(
        """SELECT participant_count, prize_amount, prize_per_participant
           FROM cube_generations WHERE id = ?""",
        (generation_id,),
    )
    generation = await cur.fetchone()
    participant_count = 0
    prize_amount = 0
    if generation:
        cur = await connection.execute(
            "SELECT COUNT(*) FROM cube_runs WHERE generation_id = ?",
            (generation_id,),
        )
        live_count = (await cur.fetchone())[0]
        participant_count = (
            generation[0] if generation[0] is not None else live_count
        )
        prize_amount = (
            generation[1]
            if generation[1] is not None
            else participant_count * generation[2]
        )
    cur = await connection.execute(
        "SELECT zbucks FROM profiles WHERE tg_id = ?", (tg_id,)
    )
    profile = await cur.fetchone()
    return CubeEnterResult(
        status=status,
        generation_id=generation_id,
        run_id=run_id,
        version=version,
        participant_count=participant_count,
        prize_amount=prize_amount,
        balance=profile[0] if profile else 0,
    )


async def enter_cube(
    generation_id: int,
    tg_id: int,
    request_key: str,
    next_spec: object,
    *,
    clock: Callable[[], datetime] | None = None,
) -> CubeEnterResult:
    """Идемпотентно принять взнос и открыть active-run в стартовой комнате."""
    if not request_key:
        raise ValueError("request_key must not be empty")
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT generation_id, tg_id, status, run_id
                   FROM cube_entry_requests WHERE request_key = ?""",
                (request_key,),
            )
            replay = await cur.fetchone()
            if replay:
                if replay[0] != generation_id or replay[1] != tg_id:
                    result = await _cube_enter_snapshot_on(
                        connection,
                        status="invalid",
                        generation_id=generation_id,
                        tg_id=tg_id,
                    )
                else:
                    result = await _cube_enter_snapshot_on(
                        connection,
                        status=replay[2],
                        generation_id=generation_id,
                        tg_id=tg_id,
                        run_id=replay[3],
                    )
                await connection.commit()
                return result

            current = _cube_effective_now(clock)
            now_iso = current.isoformat()
            await _advance_cube_lifecycle_on(connection, current, next_spec)
            cur = await connection.execute(
                """SELECT status, active_slot, start_room_id, reset_minutes,
                          lobby_seconds, entry_cost, max_participants
                   FROM cube_generations WHERE id = ?""",
                (generation_id,),
            )
            generation = await cur.fetchone()
            if not generation or generation[1] != 1 or generation[0] in ("won", "expired"):
                status: CubeEnterStatus = "closed"
                run_id = None
            else:
                cur = await connection.execute(
                    """SELECT id FROM cube_runs
                       WHERE generation_id = ? AND tg_id = ? AND status = 'active'""",
                    (generation_id, tg_id),
                )
                existing_run = await cur.fetchone()
                if existing_run:
                    status = "resumed"
                    run_id = existing_run[0]
                elif generation[0] not in ("waiting", "lobby"):
                    status = "not_recruiting"
                    run_id = None
                else:
                    cur = await connection.execute(
                        "SELECT zbucks, dirty FROM profiles WHERE tg_id = ?", (tg_id,)
                    )
                    profile = await cur.fetchone()
                    if not profile:
                        status = "no_profile"
                        run_id = None
                    else:
                        cur = await connection.execute(
                            "SELECT COUNT(*) FROM cube_runs WHERE generation_id = ?",
                            (generation_id,),
                        )
                        participants = (await cur.fetchone())[0]
                        if participants >= generation[6]:
                            status = "full"
                            run_id = None
                        else:
                            balance, dirty = profile[0], profile[1] or 0
                            # Cube lifecycle timestamps are UTC, while the
                            # existing hide-money cooldown contract stores
                            # naive local ``datetime.now()`` values. Keep the
                            # two clocks separate so a timezone offset cannot
                            # prolong or prematurely end an active hiding.
                            hidden = await _hidden_amount_on(
                                connection, tg_id, datetime.now()
                            )
                            if balance - hidden < generation[5]:
                                status = "insufficient"
                                run_id = None
                            else:
                                dirty_spend = min(
                                    generation[5], max(0, dirty - hidden)
                                )
                                await connection.execute(
                                    """UPDATE profiles
                                       SET zbucks = zbucks - ?, dirty = dirty - ?
                                       WHERE tg_id = ?""",
                                    (generation[5], dirty_spend, tg_id),
                                )
                                cur = await connection.execute(
                                    """INSERT INTO cube_runs
                                       (generation_id, tg_id, entry_request_key,
                                        status, current_room_id, version, steps,
                                        paid_amount, dirty_amount, entered_at,
                                        updated_at)
                                       VALUES (?, ?, ?, 'active', ?, 0, 0, ?, ?, ?, ?)""",
                                    (
                                        generation_id,
                                        tg_id,
                                        request_key,
                                        generation[2],
                                        generation[5],
                                        dirty_spend,
                                        now_iso,
                                        now_iso,
                                    ),
                                )
                                run_id = cur.lastrowid
                                await connection.execute(
                                    """UPDATE cube_rooms
                                       SET revealed_at = COALESCE(revealed_at, ?),
                                           revealed_by = COALESCE(revealed_by, ?)
                                       WHERE generation_id = ? AND room_id = ?""",
                                    (now_iso, tg_id, generation_id, generation[2]),
                                )
                                participants += 1
                                if generation[0] == "waiting":
                                    lobby_closes_at = (
                                        current + timedelta(seconds=generation[4])
                                    ).isoformat()
                                    closes_at = (
                                        current + timedelta(minutes=generation[3])
                                    ).isoformat()
                                    await connection.execute(
                                        """UPDATE cube_generations
                                           SET status = 'lobby',
                                               recruitment_started_at = ?,
                                               lobby_closes_at = ?, closes_at = ?
                                           WHERE id = ? AND status = 'waiting'""",
                                        (
                                            now_iso,
                                            lobby_closes_at,
                                            closes_at,
                                            generation_id,
                                        ),
                                    )
                                if participants >= generation[6]:
                                    await _lock_cube_roster_on(
                                        connection, generation_id, now_iso
                                    )
                                status = "entered"

            await connection.execute(
                """INSERT INTO cube_entry_requests
                   (request_key, generation_id, tg_id, status, run_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (request_key, generation_id, tg_id, status, run_id, now_iso),
            )
            result = await _cube_enter_snapshot_on(
                connection,
                status=status,
                generation_id=generation_id,
                tg_id=tg_id,
                run_id=run_id,
            )
            await connection.commit()
            return result
        except BaseException:
            await connection.rollback()
            raise


async def _cube_active_run_on(
    connection: aiosqlite.Connection, generation_id: int, tg_id: int
):
    cur = await connection.execute(
        """SELECT g.status, g.active_slot, g.prize_room_id,
                  r.id, r.status, r.current_room_id, r.previous_room_id,
                  r.pending_hazard_room_id, r.version
           FROM cube_generations g
           LEFT JOIN cube_runs r
             ON r.generation_id = g.id AND r.tg_id = ?
           WHERE g.id = ?""",
        (tg_id, generation_id),
    )
    return await cur.fetchone()


async def observe_cube(
    generation_id: int,
    tg_id: int,
    version: int,
    direction: str,
    next_spec: object,
    *,
    clock: Callable[[], datetime] | None = None,
) -> CubeObserveResult:
    """Сохранить личный снимок соседней комнаты без изменения run-version."""
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            current = _cube_effective_now(clock)
            await _advance_cube_lifecycle_on(connection, current, next_spec)
            state = await _cube_active_run_on(connection, generation_id, tg_id)
            if not state or state[1] != 1 or state[0] not in ("lobby", "active"):
                result = CubeObserveResult("closed", generation_id, None)
            elif state[3] is None or state[4] != "active":
                result = CubeObserveResult("no_run", generation_id, None)
            elif state[8] != version:
                result = CubeObserveResult("stale", generation_id, state[8])
            else:
                target = await _cube_target_on(
                    connection, generation_id, state[5], direction
                )
                if not target:
                    result = CubeObserveResult(
                        "wall", generation_id, state[8]
                    )
                else:
                    cur = await connection.execute(
                        """SELECT effect_kind FROM cube_rooms
                           WHERE generation_id = ? AND room_id = ?""",
                        (generation_id, state[5]),
                    )
                    source_room = await cur.fetchone()
                    category = (
                        "unreadable"
                        if source_room and source_room[0] == "dark"
                        else _cube_category(target[2], target[7])
                    )
                    await connection.execute(
                        """INSERT INTO cube_observations
                           (generation_id, tg_id, source_room_id, direction,
                            target_room_id, category, observed_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT (generation_id, tg_id, source_room_id, direction)
                           DO NOTHING""",
                        (
                            generation_id,
                            tg_id,
                            state[5],
                            direction,
                            target[0],
                            category,
                            current.isoformat(),
                        ),
                    )
                    cur = await connection.execute(
                        """SELECT target_room_id, category FROM cube_observations
                           WHERE generation_id = ? AND tg_id = ?
                             AND source_room_id = ? AND direction = ?""",
                        (generation_id, tg_id, state[5], direction),
                    )
                    saved = await cur.fetchone()
                    result = CubeObserveResult(
                        "observed", generation_id, state[8], saved[0], saved[1]
                    )
            await connection.commit()
            return result
        except BaseException:
            await connection.rollback()
            raise


async def _enter_cube_room_on(
    connection: aiosqlite.Connection,
    *,
    generation_id: int,
    tg_id: int,
    run_id: int,
    source_room_id: int,
    target,
    current: datetime,
) -> tuple[str, int, str | None, str | None, int]:
    """Раскрыть комнату, применить максимум один эффект, обновить run."""
    now_iso = current.isoformat()
    target_room_id = target[0]
    await connection.execute(
        """UPDATE cube_rooms
           SET revealed_at = COALESCE(revealed_at, ?),
               revealed_by = COALESCE(revealed_by, ?)
           WHERE generation_id = ? AND room_id = ?""",
        (now_iso, tg_id, generation_id, target_room_id),
    )
    effect_kind = target[7]
    final_room_id = target_room_id
    move_status = "moved"
    if effect_kind in ("echo", "echo_bounce") and target[11] is None:
        await connection.execute(
            """UPDATE cube_rooms SET resolved_at = ?, resolved_by = ?
               WHERE generation_id = ? AND room_id = ? AND resolved_at IS NULL""",
            (now_iso, tg_id, generation_id, target_room_id),
        )
        final_room_id = source_room_id
        move_status = "bounced"
    elif effect_kind in ("echo", "echo_bounce"):
        # The globally spent echo behaves like an ordinary room. Returning
        # the effect here would make the UI claim that a bounce still happened.
        effect_kind = None
    elif effect_kind == "archive" and target[8] is not None and target[9] in _CUBE_DIRECTIONS:
        cur = await connection.execute(
            """SELECT kind, effect_kind FROM cube_rooms
               WHERE generation_id = ? AND room_id = ?""",
            (generation_id, target[8]),
        )
        hinted_room = await cur.fetchone()
        if hinted_room:
            await connection.execute(
                """INSERT INTO cube_observations
                   (generation_id, tg_id, source_room_id, direction,
                    target_room_id, category, observed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (generation_id, tg_id, source_room_id, direction)
                   DO NOTHING""",
                (
                    generation_id,
                    tg_id,
                    target_room_id,
                    target[9],
                    target[8],
                    _cube_category(hinted_room[0], hinted_room[1]),
                    now_iso,
                ),
            )
    elif effect_kind in ("vector", "tunnel") and target[8] is not None:
        final_room_id = target[8]
        await connection.execute(
            """UPDATE cube_rooms
               SET revealed_at = COALESCE(revealed_at, ?),
                   revealed_by = COALESCE(revealed_by, ?)
               WHERE generation_id = ? AND room_id = ?""",
            (now_iso, tg_id, generation_id, final_room_id),
        )
    await connection.execute(
        """UPDATE cube_runs
           SET previous_room_id = current_room_id, current_room_id = ?,
               pending_hazard_room_id = NULL, version = version + 1,
               steps = steps + 1, updated_at = ?
           WHERE id = ?""",
        (final_room_id, now_iso, run_id),
    )
    cur = await connection.execute(
        "SELECT version FROM cube_runs WHERE id = ?", (run_id,)
    )
    new_version = (await cur.fetchone())[0]
    return move_status, final_room_id, effect_kind, target[9], new_version


async def _settle_cube_win_on(
    connection: aiosqlite.Connection,
    *,
    generation_id: int,
    tg_id: int,
    run_id: int,
    prize_room_id: int,
    current: datetime,
    next_spec: object,
) -> tuple[int, int, int]:
    now_iso = current.isoformat()
    participant_count, prize_amount = await _lock_cube_roster_on(
        connection, generation_id, now_iso
    )
    cur = await connection.execute(
        "SELECT zbucks FROM profiles WHERE tg_id = ?", (tg_id,)
    )
    profile = await cur.fetchone()
    if not profile:
        raise RuntimeError("cube winner profile disappeared")
    balance_before = profile[0]
    balance_after = balance_before + prize_amount
    await connection.execute(
        "UPDATE profiles SET zbucks = zbucks + ? WHERE tg_id = ?",
        (prize_amount, tg_id),
    )
    cur = await connection.execute(
        """UPDATE cube_generations
           SET status = 'won', active_slot = NULL,
               participant_count = ?, prize_amount = ?, winner_tg_id = ?,
               winner_balance_before = ?, winner_balance_after = ?,
               finished_at = ?, finish_reason = 'prize_found'
           WHERE id = ? AND active_slot = 1 AND status IN ('lobby','active')""",
        (
            participant_count,
            prize_amount,
            tg_id,
            balance_before,
            balance_after,
            now_iso,
            generation_id,
        ),
    )
    if cur.rowcount != 1:
        raise RuntimeError("cube generation was won concurrently")
    await connection.execute(
        """UPDATE cube_runs
           SET status = 'lost', updated_at = ?
           WHERE generation_id = ? AND status = 'active' AND id != ?""",
        (now_iso, generation_id, run_id),
    )
    await connection.execute(
        """UPDATE cube_runs
           SET status = 'won', previous_room_id = current_room_id,
               current_room_id = ?, pending_hazard_room_id = NULL,
               version = version + 1, steps = steps + 1,
               updated_at = ?, won_at = ?
           WHERE id = ? AND status = 'active'""",
        (prize_room_id, now_iso, now_iso, run_id),
    )
    await connection.execute(
        """UPDATE cube_rooms
           SET revealed_at = COALESCE(revealed_at, ?),
               revealed_by = COALESCE(revealed_by, ?)
           WHERE generation_id = ? AND room_id = ?""",
        (now_iso, tg_id, generation_id, prize_room_id),
    )
    await connection.execute(
        """INSERT OR IGNORE INTO cube_notifications
           (generation_id, kind, recipient_tg_id, subscription_id,
            next_attempt_at, created_at)
           VALUES (?, 'winner_public', NULL, NULL, ?, ?)""",
        (generation_id, now_iso, now_iso),
    )
    next_generation_id = await _insert_cube_generation_on(
        connection, next_spec, current
    )
    return prize_amount, balance_after, next_generation_id


async def move_cube(
    generation_id: int,
    tg_id: int,
    version: int,
    direction: str,
    next_spec: object,
    *,
    clock: Callable[[], datetime] | None = None,
) -> CubeMoveResult:
    """Атомарно выполнить ровно один переход либо оформить победу."""
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            current = _cube_effective_now(clock)
            await _advance_cube_lifecycle_on(connection, current, next_spec)
            state = await _cube_active_run_on(connection, generation_id, tg_id)
            if not state or state[1] != 1 or state[0] not in ("lobby", "active"):
                result = CubeMoveResult("closed", generation_id, None)
            elif state[3] is None or state[4] != "active":
                result = CubeMoveResult("no_run", generation_id, None)
            elif state[8] != version:
                result = CubeMoveResult("stale", generation_id, state[8])
            else:
                target = await _cube_target_on(
                    connection, generation_id, state[5], direction
                )
                if not target:
                    result = CubeMoveResult("wall", generation_id, state[8])
                elif target[2] == "hazard" and target[11] is None:
                    now_iso = current.isoformat()
                    await connection.execute(
                        """UPDATE cube_rooms
                           SET revealed_at = COALESCE(revealed_at, ?),
                               revealed_by = COALESCE(revealed_by, ?)
                           WHERE generation_id = ? AND room_id = ?""",
                        (now_iso, tg_id, generation_id, target[0]),
                    )
                    await connection.execute(
                        """UPDATE cube_runs
                           SET pending_hazard_room_id = ?, version = version + 1,
                               updated_at = ? WHERE id = ?""",
                        (target[0], now_iso, state[3]),
                    )
                    cur = await connection.execute(
                        "SELECT version FROM cube_runs WHERE id = ?", (state[3],)
                    )
                    new_version = (await cur.fetchone())[0]
                    result = CubeMoveResult(
                        "hazard",
                        generation_id,
                        new_version,
                        entered_room_id=target[0],
                        final_room_id=state[5],
                        target_room_id=target[0],
                    )
                elif target[0] == state[2] or target[2] == "prize":
                    prize, _balance, next_generation_id = await _settle_cube_win_on(
                        connection,
                        generation_id=generation_id,
                        tg_id=tg_id,
                        run_id=state[3],
                        prize_room_id=target[0],
                        current=current,
                        next_spec=next_spec,
                    )
                    cur = await connection.execute(
                        "SELECT version FROM cube_runs WHERE id = ?", (state[3],)
                    )
                    new_version = (await cur.fetchone())[0]
                    result = CubeMoveResult(
                        "won",
                        generation_id,
                        new_version,
                        entered_room_id=target[0],
                        final_room_id=target[0],
                        prize_amount=prize,
                        next_generation_id=next_generation_id,
                    )
                else:
                    status, final_room, effect, effect_arg, new_version = (
                        await _enter_cube_room_on(
                            connection,
                            generation_id=generation_id,
                            tg_id=tg_id,
                            run_id=state[3],
                            source_room_id=state[5],
                            target=target,
                            current=current,
                        )
                    )
                    result = CubeMoveResult(
                        status,
                        generation_id,
                        new_version,
                        entered_room_id=target[0],
                        final_room_id=final_room,
                        effect_kind=effect,
                        effect_arg=effect_arg,
                    )
            await connection.commit()
            return result
        except BaseException:
            await connection.rollback()
            raise


async def resolve_cube_hazard_and_enter(
    generation_id: int,
    tg_id: int,
    version: int,
    target_room_id: int,
    next_spec: object,
    *,
    clock: Callable[[], datetime] | None = None,
) -> CubeActionResult:
    """Обезвредить ловушку и войти одним commit, условно сняв расходник."""
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            current = _cube_effective_now(clock)
            await _advance_cube_lifecycle_on(connection, current, next_spec)
            state = await _cube_active_run_on(connection, generation_id, tg_id)
            if not state or state[1] != 1 or state[0] not in ("lobby", "active"):
                result = CubeActionResult("closed", generation_id, None)
            elif state[3] is None or state[4] != "active":
                result = CubeActionResult("no_run", generation_id, None)
            elif state[8] != version:
                result = CubeActionResult("stale", generation_id, state[8])
            elif state[7] != target_room_id:
                result = CubeActionResult(
                    "invalid", generation_id, state[8], target_room_id
                )
            else:
                target = None
                for direction in _CUBE_DIRECTIONS:
                    candidate = await _cube_target_on(
                        connection, generation_id, state[5], direction
                    )
                    if candidate and candidate[0] == target_room_id:
                        target = candidate
                        break
                if not target or target[2] != "hazard":
                    result = CubeActionResult(
                        "invalid", generation_id, state[8], target_room_id
                    )
                elif target[11] is not None:
                    result = CubeActionResult(
                        "already_resolved",
                        generation_id,
                        state[8],
                        target_room_id,
                        required_item_key=target[5],
                        consume_qty=target[6],
                        hazard_kind=target[4],
                    )
                else:
                    required_item = target[5]
                    consume_qty = target[6]
                    has_item = bool(required_item) and await _has_item_on(
                        connection, tg_id, required_item, max(1, consume_qty)
                    )
                    if not has_item:
                        await connection.execute(
                            """UPDATE cube_runs
                               SET version = version + 1, updated_at = ?
                               WHERE id = ?""",
                            (current.isoformat(), state[3]),
                        )
                        cur = await connection.execute(
                            "SELECT version FROM cube_runs WHERE id = ?", (state[3],)
                        )
                        new_version = (await cur.fetchone())[0]
                        result = CubeActionResult(
                            "missing_item",
                            generation_id,
                            new_version,
                            target_room_id,
                            required_item_key=required_item,
                            consume_qty=consume_qty,
                            hazard_kind=target[4],
                        )
                    else:
                        cur = await connection.execute(
                            """UPDATE cube_rooms
                               SET resolved_at = ?, resolved_by = ?,
                                   revealed_at = COALESCE(revealed_at, ?),
                                   revealed_by = COALESCE(revealed_by, ?)
                               WHERE generation_id = ? AND room_id = ?
                                 AND resolved_at IS NULL""",
                            (
                                current.isoformat(),
                                tg_id,
                                current.isoformat(),
                                tg_id,
                                generation_id,
                                target_room_id,
                            ),
                        )
                        if cur.rowcount != 1:
                            result = CubeActionResult(
                                "already_resolved",
                                generation_id,
                                state[8],
                                target_room_id,
                                required_item_key=required_item,
                                consume_qty=consume_qty,
                                hazard_kind=target[4],
                            )
                        else:
                            if consume_qty and not await _take_item_on(
                                connection,
                                tg_id,
                                required_item,
                                consume_qty,
                            ):
                                raise RuntimeError(
                                    "cube inventory changed inside writer transaction"
                                )
                            _status, final_room, effect, _effect_arg, new_version = (
                                await _enter_cube_room_on(
                                    connection,
                                    generation_id=generation_id,
                                    tg_id=tg_id,
                                    run_id=state[3],
                                    source_room_id=state[5],
                                    target=target,
                                    current=current,
                                )
                            )
                            result = CubeActionResult(
                                "resolved_and_moved",
                                generation_id,
                                new_version,
                                target_room_id,
                                final_room,
                                effect,
                                required_item,
                                consume_qty,
                                target[4],
                            )
            await connection.commit()
            return result
        except BaseException:
            await connection.rollback()
            raise


async def subscribe_cube(
    generation_id: int,
    tg_id: int,
    request_key: str,
    next_spec: object,
    *,
    clock: Callable[[], datetime] | None = None,
) -> CubeNotifyResult:
    """Идемпотентно подписать игрока на первое следующее поколение."""
    if not request_key:
        raise ValueError("request_key must not be empty")
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT generation_id, tg_id, subscription_id, status
                   FROM cube_subscription_requests WHERE request_key = ?""",
                (request_key,),
            )
            replay = await cur.fetchone()
            if replay:
                if replay[0] != generation_id or replay[1] != tg_id:
                    result = CubeNotifyResult("invalid", generation_id, None)
                elif replay[3] == "active":
                    result = CubeNotifyResult(
                        "already_subscribed", generation_id, replay[2]
                    )
                else:
                    result = CubeNotifyResult("stale", generation_id, replay[2])
                await connection.commit()
                return result

            current = _cube_effective_now(clock)
            now_iso = current.isoformat()
            await _advance_cube_lifecycle_on(connection, current, next_spec)
            cur = await connection.execute(
                """SELECT status, active_slot FROM cube_generations
                   WHERE id = ?""",
                (generation_id,),
            )
            source_generation = await cur.fetchone()
            cur = await connection.execute(
                "SELECT 1 FROM profiles WHERE tg_id = ?", (tg_id,)
            )
            profile = await cur.fetchone()
            if not profile:
                result = CubeNotifyResult("invalid", generation_id, None)
                await connection.commit()
                return result
            if (
                not source_generation
                or source_generation[0] != "active"
                or source_generation[1] != 1
            ):
                result = CubeNotifyResult("stale", generation_id, None)
                await connection.commit()
                return result
            cur = await connection.execute(
                """SELECT 1 FROM cube_runs
                   WHERE generation_id = ? AND tg_id = ? AND status = 'active'""",
                (generation_id, tg_id),
            )
            if await cur.fetchone():
                result = CubeNotifyResult("invalid", generation_id, None)
                await connection.commit()
                return result

            cur = await connection.execute(
                """SELECT id, requested_after_generation_id
                   FROM cube_waitlist WHERE tg_id = ?""",
                (tg_id,),
            )
            existing = await cur.fetchone()
            if existing:
                subscription_id = existing[0]
                notify_status: CubeNotifyStatus = "already_subscribed"
            else:
                cur = await connection.execute(
                    """INSERT INTO cube_waitlist
                       (tg_id, requested_after_generation_id, request_key, requested_at)
                       VALUES (?, ?, ?, ?)""",
                    (tg_id, generation_id, request_key, now_iso),
                )
                subscription_id = cur.lastrowid
                notify_status = "subscribed"

            await connection.execute(
                """INSERT INTO cube_subscription_requests
                   (request_key, generation_id, tg_id, subscription_id, status,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'active', ?, ?)""",
                (
                    request_key,
                    generation_id,
                    tg_id,
                    subscription_id,
                    now_iso,
                    now_iso,
                ),
            )
            # Если следующее waiting/lobby уже успело появиться, подписка не
            # ждёт ещё одно поколение: сразу материализуем durable invite.
            cur = await connection.execute(
                """SELECT id FROM cube_generations
                   WHERE active_slot = 1 AND status IN ('waiting','lobby')
                     AND id > ? ORDER BY id DESC LIMIT 1""",
                (generation_id,),
            )
            current_generation = await cur.fetchone()
            if current_generation:
                await connection.execute(
                    """INSERT OR IGNORE INTO cube_notifications
                       (generation_id, kind, recipient_tg_id, subscription_id,
                        next_attempt_at, created_at)
                       VALUES (?, 'lobby_private', ?, ?, ?, ?)""",
                    (
                        current_generation[0],
                        tg_id,
                        subscription_id,
                        now_iso,
                        now_iso,
                    ),
                )
            await connection.commit()
            return CubeNotifyResult(
                notify_status, generation_id, subscription_id
            )
        except BaseException:
            await connection.rollback()
            raise


async def cancel_cube_subscription(
    generation_id: int,
    tg_id: int,
    subscription_id: int,
    next_spec: object,
    *,
    clock: Callable[[], datetime] | None = None,
) -> CubeNotifyResult:
    """Снять только точную версию подписки из callback, не более новую."""
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            current = _cube_effective_now(clock)
            now_iso = current.isoformat()
            await _advance_cube_lifecycle_on(connection, current, next_spec)
            cur = await connection.execute(
                """SELECT id FROM cube_waitlist
                   WHERE id = ? AND tg_id = ?
                     AND requested_after_generation_id = ?""",
                (subscription_id, tg_id, generation_id),
            )
            waitlist = await cur.fetchone()
            if waitlist:
                await connection.execute(
                    "DELETE FROM cube_waitlist WHERE id = ?", (subscription_id,)
                )
                await connection.execute(
                    """UPDATE cube_subscription_requests
                       SET status = 'cancelled', updated_at = ?
                       WHERE subscription_id = ? AND tg_id = ? AND status = 'active'""",
                    (now_iso, subscription_id, tg_id),
                )
                await connection.execute(
                    """UPDATE cube_notifications
                       SET status = 'cancelled', claim_token = NULL,
                           claim_until = NULL
                       WHERE subscription_id = ? AND status = 'pending'""",
                    (subscription_id,),
                )
                result = CubeNotifyResult(
                    "cancelled", generation_id, subscription_id
                )
            else:
                cur = await connection.execute(
                    """SELECT status FROM cube_subscription_requests
                       WHERE subscription_id = ? AND tg_id = ?
                         AND generation_id = ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (subscription_id, tg_id, generation_id),
                )
                request = await cur.fetchone()
                if request and request[0] == "cancelled":
                    result = CubeNotifyResult(
                        "cancelled", generation_id, subscription_id
                    )
                elif request:
                    result = CubeNotifyResult(
                        "stale", generation_id, subscription_id
                    )
                else:
                    result = CubeNotifyResult("invalid", generation_id, None)
            await connection.commit()
            return result
        except BaseException:
            await connection.rollback()
            raise


def _cube_winner_claim_from_row(
    row, claim_token: str | None = None
) -> CubeWinnerClaim:
    return CubeWinnerClaim(
        generation_id=row[0],
        winner_tg_id=row[1],
        winner_nick=row[2],
        participant_count=row[3],
        prize_amount=row[4],
        winner_balance_before=row[5],
        winner_balance_after=row[6],
        claim_token=claim_token,
    )


async def get_cube_winner(generation_id: int) -> CubeWinnerClaim | None:
    cur = await _db.execute(
        """SELECT g.id, g.winner_tg_id, p.nick, g.participant_count,
                  g.prize_amount, g.winner_balance_before,
                  g.winner_balance_after
           FROM cube_generations g
           JOIN profiles p ON p.tg_id = g.winner_tg_id
           WHERE g.id = ? AND g.status = 'won'""",
        (generation_id,),
    )
    row = await cur.fetchone()
    return _cube_winner_claim_from_row(row) if row else None


async def pending_cube_tax() -> list[CubeWinnerClaim]:
    cur = await _db.execute(
        """SELECT g.id, g.winner_tg_id, p.nick, g.participant_count,
                  g.prize_amount, g.winner_balance_before,
                  g.winner_balance_after
           FROM cube_generations g
           JOIN profiles p ON p.tg_id = g.winner_tg_id
           WHERE g.status = 'won' AND g.tax_processed_at IS NULL
           ORDER BY g.id"""
    )
    return [_cube_winner_claim_from_row(row) for row in await cur.fetchall()]


async def claim_pending_cube_tax(
    claim_token: str,
    now_iso: str,
    claim_until: str,
    limit: int = 20,
) -> list[CubeWinnerClaim]:
    """Арендовать post-commit проверки Густава по выигрышам Куба."""
    if not claim_token:
        raise ValueError("claim_token must not be empty")
    if datetime.fromisoformat(claim_until) <= datetime.fromisoformat(now_iso):
        raise ValueError("claim_until must be after now_iso")
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT id FROM cube_generations
                   WHERE status = 'won' AND winner_tg_id IS NOT NULL
                     AND tax_processed_at IS NULL
                     AND (tax_claim_until IS NULL OR tax_claim_until <= ?)
                   ORDER BY id LIMIT ?""",
                (now_iso, max(1, limit)),
            )
            generation_ids = [row[0] for row in await cur.fetchall()]
            if not generation_ids:
                await connection.rollback()
                return []
            placeholders = ", ".join("?" for _ in generation_ids)
            await connection.execute(
                f"""UPDATE cube_generations
                    SET tax_claim_token = ?, tax_claim_until = ?
                    WHERE id IN ({placeholders}) AND tax_processed_at IS NULL
                      AND (tax_claim_until IS NULL OR tax_claim_until <= ?)""",
                (claim_token, claim_until, *generation_ids, now_iso),
            )
            cur = await connection.execute(
                f"""SELECT g.id, g.winner_tg_id, p.nick,
                            g.participant_count, g.prize_amount,
                            g.winner_balance_before, g.winner_balance_after
                     FROM cube_generations g
                     JOIN profiles p ON p.tg_id = g.winner_tg_id
                     WHERE g.id IN ({placeholders}) AND g.tax_claim_token = ?
                     ORDER BY g.id""",
                (*generation_ids, claim_token),
            )
            jobs = [
                _cube_winner_claim_from_row(row, claim_token)
                for row in await cur.fetchall()
            ]
            await connection.commit()
            return jobs
        except BaseException:
            await connection.rollback()
            raise


async def cube_tax_claim_is_current(
    generation_id: int,
    claim_token: str,
    now_iso: str,
) -> bool:
    """Recheck Gustav lease immediately before its post-commit side effect."""
    if not claim_token:
        return False
    current = datetime.fromisoformat(now_iso)
    cur = await _db.execute(
        """SELECT tax_claim_token, tax_claim_until
           FROM cube_generations
           WHERE id = ? AND status = 'won' AND tax_processed_at IS NULL""",
        (generation_id,),
    )
    row = await cur.fetchone()
    return bool(
        row
        and row[0] == claim_token
        and row[1] is not None
        and datetime.fromisoformat(row[1]) > current
    )


async def mark_cube_tax_processed(
    generation_id: int,
    claim_token: str,
    processed_at: str | None = None,
) -> bool:
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """UPDATE cube_generations
                   SET tax_processed_at = ?, tax_claim_token = NULL,
                       tax_claim_until = NULL
                   WHERE id = ? AND status = 'won'
                     AND tax_processed_at IS NULL AND tax_claim_token = ?""",
                (
                    processed_at or datetime.utcnow().isoformat(),
                    generation_id,
                    claim_token,
                ),
            )
            await connection.commit()
            return cur.rowcount == 1
        except BaseException:
            await connection.rollback()
            raise


async def release_cube_tax_claim(
    generation_id: int, claim_token: str
) -> bool:
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """UPDATE cube_generations
                   SET tax_claim_token = NULL, tax_claim_until = NULL
                   WHERE id = ? AND tax_processed_at IS NULL
                     AND tax_claim_token = ?""",
                (generation_id, claim_token),
            )
            await connection.commit()
            return cur.rowcount == 1
        except BaseException:
            await connection.rollback()
            raise


def _cube_notification_from_row(
    row, claim_token: str | None = None
) -> CubeNotification:
    return CubeNotification(
        notification_id=row[0],
        generation_id=row[1],
        kind=row[2],
        recipient_tg_id=row[3],
        subscription_id=row[4],
        attempts=row[5],
        next_attempt_at=row[6],
        winner_tg_id=row[7],
        winner_nick=row[8],
        participant_count=row[9],
        prize_amount=row[10],
        claim_token=claim_token,
    )


async def cube_notification_claim_is_current(
    notification_id: int,
    claim_token: str,
    now_iso: str,
) -> bool:
    """Recheck notification/subscription lease immediately before Telegram."""
    if not claim_token:
        return False
    current = datetime.fromisoformat(now_iso)
    cur = await _db.execute(
        """SELECT n.kind, n.subscription_id, n.claim_token, n.claim_until,
                  w.id, w.claim_token, w.claim_until
           FROM cube_notifications n
           LEFT JOIN cube_waitlist w ON w.id = n.subscription_id
           WHERE n.id = ? AND n.status = 'pending'""",
        (notification_id,),
    )
    row = await cur.fetchone()
    if (
        not row
        or row[2] != claim_token
        or row[3] is None
        or datetime.fromisoformat(row[3]) <= current
    ):
        return False
    if row[0] != "lobby_private":
        return True
    return bool(
        row[1] is not None
        and row[4] == row[1]
        and row[5] == claim_token
        and row[6] is not None
        and datetime.fromisoformat(row[6]) > current
    )


async def claim_cube_notifications(
    claim_token: str,
    now_iso: str,
    claim_until: str,
    limit: int = 20,
) -> list[CubeNotification]:
    """Claim outbox records; private invite also leases its subscription."""
    if not claim_token:
        raise ValueError("claim_token must not be empty")
    if datetime.fromisoformat(claim_until) <= datetime.fromisoformat(now_iso):
        raise ValueError("claim_until must be after now_iso")
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT n.id, n.kind, n.generation_id, n.recipient_tg_id,
                          n.subscription_id, g.status,
                          w.id, w.requested_after_generation_id,
                          w.claim_until
                   FROM cube_notifications n
                   JOIN cube_generations g ON g.id = n.generation_id
                   LEFT JOIN cube_waitlist w ON w.id = n.subscription_id
                   WHERE n.status = 'pending' AND n.next_attempt_at <= ?
                     AND (n.claim_until IS NULL OR n.claim_until <= ?)
                   ORDER BY n.generation_id DESC, n.id
                   LIMIT ?""",
                (now_iso, now_iso, max(1, limit) * 4),
            )
            rows = await cur.fetchall()
            claimed_ids: list[int] = []
            for row in rows:
                if len(claimed_ids) >= max(1, limit):
                    break
                notification_id, kind, target_generation = row[0], row[1], row[2]
                if kind == "lobby_private":
                    valid = (
                        row[5] in ("waiting", "lobby")
                        and row[6] == row[4]
                        and row[7] < target_generation
                    )
                    if not valid:
                        await connection.execute(
                            """UPDATE cube_notifications
                               SET status = 'stale', claim_token = NULL,
                                   claim_until = NULL WHERE id = ?""",
                            (notification_id,),
                        )
                        continue
                    if row[8] is not None and row[8] > now_iso:
                        continue
                    cur = await connection.execute(
                        """UPDATE cube_waitlist
                           SET claim_token = ?, claim_until = ?
                           WHERE id = ?
                             AND (claim_until IS NULL OR claim_until <= ?)""",
                        (claim_token, claim_until, row[4], now_iso),
                    )
                    if cur.rowcount != 1:
                        continue
                cur = await connection.execute(
                    """UPDATE cube_notifications
                       SET claim_token = ?, claim_until = ?
                       WHERE id = ? AND status = 'pending'
                         AND (claim_until IS NULL OR claim_until <= ?)""",
                    (claim_token, claim_until, notification_id, now_iso),
                )
                if cur.rowcount == 1:
                    claimed_ids.append(notification_id)

            if not claimed_ids:
                await connection.commit()
                return []
            placeholders = ", ".join("?" for _ in claimed_ids)
            cur = await connection.execute(
                f"""SELECT n.id, n.generation_id, n.kind,
                            n.recipient_tg_id, n.subscription_id, n.attempts,
                            n.next_attempt_at, g.winner_tg_id, p.nick,
                            g.participant_count, g.prize_amount
                     FROM cube_notifications n
                     JOIN cube_generations g ON g.id = n.generation_id
                     LEFT JOIN profiles p ON p.tg_id = g.winner_tg_id
                     WHERE n.id IN ({placeholders}) AND n.claim_token = ?
                     ORDER BY n.id""",
                (*claimed_ids, claim_token),
            )
            notifications = [
                _cube_notification_from_row(row, claim_token)
                for row in await cur.fetchall()
            ]
            await connection.commit()
            return notifications
        except BaseException:
            await connection.rollback()
            raise


async def mark_cube_notification_sent(
    notification_id: int,
    claim_token: str,
    sent_at: str | None = None,
) -> bool:
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT kind, subscription_id, recipient_tg_id
                   FROM cube_notifications
                   WHERE id = ? AND status = 'pending' AND claim_token = ?""",
                (notification_id, claim_token),
            )
            notification = await cur.fetchone()
            if not notification:
                await connection.rollback()
                return False
            completed_at = sent_at or datetime.utcnow().isoformat()
            await connection.execute(
                """UPDATE cube_notifications
                   SET status = 'sent', sent_at = ?, attempts = attempts + 1,
                       claim_token = NULL, claim_until = NULL
                   WHERE id = ? AND status = 'pending' AND claim_token = ?""",
                (completed_at, notification_id, claim_token),
            )
            if notification[0] == "lobby_private":
                await connection.execute(
                    """DELETE FROM cube_waitlist
                       WHERE id = ? AND tg_id = ? AND claim_token = ?""",
                    (notification[1], notification[2], claim_token),
                )
                await connection.execute(
                    """UPDATE cube_subscription_requests
                       SET status = 'delivered', updated_at = ?
                       WHERE subscription_id = ? AND tg_id = ?
                         AND status = 'active'""",
                    (completed_at, notification[1], notification[2]),
                )
                await connection.execute(
                    """UPDATE cube_notifications SET status = 'stale'
                       WHERE subscription_id = ? AND id != ?
                         AND status = 'pending'""",
                    (notification[1], notification_id),
                )
            await connection.commit()
            return True
        except BaseException:
            await connection.rollback()
            raise


async def mark_cube_notification_retry(
    notification_id: int,
    claim_token: str,
    next_attempt_at: str,
    error: str,
) -> bool:
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT subscription_id FROM cube_notifications
                   WHERE id = ? AND status = 'pending' AND claim_token = ?""",
                (notification_id, claim_token),
            )
            row = await cur.fetchone()
            if not row:
                await connection.rollback()
                return False
            cur = await connection.execute(
                """UPDATE cube_notifications
                   SET attempts = attempts + 1, next_attempt_at = ?,
                       last_error = ?, claim_token = NULL, claim_until = NULL
                   WHERE id = ? AND status = 'pending' AND claim_token = ?""",
                (next_attempt_at, error[:1000], notification_id, claim_token),
            )
            if row[0] is not None:
                await connection.execute(
                    """UPDATE cube_waitlist
                       SET claim_token = NULL, claim_until = NULL
                       WHERE id = ? AND claim_token = ?""",
                    (row[0], claim_token),
                )
            await connection.commit()
            return cur.rowcount == 1
        except BaseException:
            await connection.rollback()
            raise


async def mark_cube_notification_stale(
    notification_id: int, claim_token: str
) -> bool:
    """Закрыть invite, который после claim перестал вести в открытый набор."""
    async with _economy_lock:
        connection = _economy_connection()
        await connection.execute("BEGIN IMMEDIATE")
        try:
            cur = await connection.execute(
                """SELECT subscription_id FROM cube_notifications
                   WHERE id = ? AND status = 'pending' AND claim_token = ?""",
                (notification_id, claim_token),
            )
            row = await cur.fetchone()
            if not row:
                await connection.rollback()
                return False
            cur = await connection.execute(
                """UPDATE cube_notifications
                   SET status = 'stale', claim_token = NULL, claim_until = NULL
                   WHERE id = ? AND status = 'pending' AND claim_token = ?""",
                (notification_id, claim_token),
            )
            if row[0] is not None:
                await connection.execute(
                    """UPDATE cube_waitlist
                       SET claim_token = NULL, claim_until = NULL
                       WHERE id = ? AND claim_token = ?""",
                    (row[0], claim_token),
                )
            await connection.commit()
            return cur.rowcount == 1
        except BaseException:
            await connection.rollback()
            raise
