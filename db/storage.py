"""Хранилище: игроки (для детекта новичков) и профили ZakharCompanion."""
from datetime import datetime

import aiosqlite

from config import config

_db: aiosqlite.Connection | None = None


async def init() -> None:
    global _db
    _db = await aiosqlite.connect(config.db_path)
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
        """
    )
    # миграции для уже существующей БД
    await _ensure_column("profiles", "xp", "INTEGER DEFAULT 0")
    await _ensure_column("profiles", "level", "INTEGER DEFAULT 0")
    await _ensure_column("profiles", "thefts", "INTEGER DEFAULT 0")
    await _db.commit()


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
    try:
        await _db.execute(
            "INSERT INTO profiles (tg_id, username, nick) VALUES (?, ?, ?)",
            (tg_id, username, nick),
        )
        await _db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


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

async def spend_zbucks(tg_id: int, amount: int) -> bool:
    """Списать Zbucks. False, если не хватает."""
    cur = await _db.execute("SELECT zbucks FROM profiles WHERE tg_id = ?", (tg_id,))
    row = await cur.fetchone()
    if not row or row[0] < amount:
        return False
    await _db.execute(
        "UPDATE profiles SET zbucks = zbucks - ? WHERE tg_id = ?", (amount, tg_id)
    )
    await _db.commit()
    return True


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
    new = await get_item_qty(tg_id, item) + qty
    if max_qty is not None:
        new = min(new, max_qty)
    await _db.execute(
        """
        INSERT INTO inventory (tg_id, item, qty) VALUES (?, ?, ?)
        ON CONFLICT (tg_id, item) DO UPDATE SET qty = excluded.qty
        """,
        (tg_id, item, new),
    )
    await _db.commit()
    return new


async def remove_item(tg_id: int, item: str, qty: int = 1) -> bool:
    """Снять qty предметов. False, если столько нет."""
    have = await get_item_qty(tg_id, item)
    if have < qty:
        return False
    new = have - qty
    if new <= 0:
        await _db.execute("DELETE FROM inventory WHERE tg_id = ? AND item = ?", (tg_id, item))
    else:
        await _db.execute(
            "UPDATE inventory SET qty = ? WHERE tg_id = ? AND item = ?", (new, tg_id, item)
        )
    await _db.commit()
    return True


# --- рынок ---

async def add_listing(tg_id: int, item: str, price: int, sell_at: str) -> None:
    await _db.execute(
        "INSERT INTO market (tg_id, item, price, sell_at) VALUES (?, ?, ?, ?)",
        (tg_id, item, price, sell_at),
    )
    await _db.commit()


async def get_listings(tg_id: int) -> list[tuple]:
    """Активные продажи игрока: (item, price, sell_at)."""
    cur = await _db.execute(
        "SELECT item, price, sell_at FROM market WHERE tg_id = ? ORDER BY sell_at", (tg_id,)
    )
    return await cur.fetchall()


async def due_listings(now_iso: str) -> list[tuple]:
    """Продажи, у которых вышел срок: (id, tg_id, item, price)."""
    cur = await _db.execute(
        "SELECT id, tg_id, item, price FROM market WHERE sell_at <= ?", (now_iso,)
    )
    return await cur.fetchall()


async def remove_listing(listing_id: int) -> None:
    await _db.execute("DELETE FROM market WHERE id = ?", (listing_id,))
    await _db.commit()


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
    cur = await _db.execute("DELETE FROM inventory WHERE tg_id = ?", (tg_id,))
    await _db.commit()
    return cur.rowcount


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
