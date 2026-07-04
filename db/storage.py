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

# --- прятки от Густава (ключи живут тут, чтобы spend_zbucks их видел) ---
HIDE_KEY = "gustav_hide"
HIDE_CD_KEY = "gustav_hide_cd"


def hidden_meta_key(tg_id: int) -> str:
    return f"gustav_hidden:{tg_id}"


async def hidden_now(tg_id: int) -> int:
    """Сколько Z сейчас спрятано от Густава (0 — прятка не активна)."""
    cur = await _db.execute(
        "SELECT used_at FROM cooldowns WHERE tg_id = ? AND game = ?", (tg_id, HIDE_KEY)
    )
    row = await cur.fetchone()
    if not row or datetime.fromisoformat(row[0]) <= datetime.now():
        return 0
    val = await get_meta(hidden_meta_key(tg_id))
    try:
        return int(val or 0)
    except ValueError:
        return 0


async def spend_zbucks_traced(tg_id: int, amount: int) -> int | None:
    """Списать Zbucks и вернуть, СКОЛЬКО из списанного было грязными.

    None — денег не хватает (ничего не списано).
    Спрятанные от Густава деньги потратить нельзя — они заняты в носках.
    Из доступного первыми тратятся ГРЯЗНЫЕ (не спрятанные) — так от них
    можно избавиться, пока Густав едет с проверкой.
    """
    cur = await _db.execute(
        "SELECT zbucks, dirty FROM profiles WHERE tg_id = ?", (tg_id,)
    )
    row = await cur.fetchone()
    if not row:
        return None
    balance, dirty = row[0], row[1] or 0
    hidden = await hidden_now(tg_id)
    if balance - hidden < amount:
        return None
    dirty_spend = min(amount, max(0, dirty - hidden))
    await _db.execute(
        "UPDATE profiles SET zbucks = zbucks - ?, dirty = dirty - ? WHERE tg_id = ?",
        (amount, dirty_spend, tg_id),
    )
    await _db.commit()
    return dirty_spend


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
    cur = await _db.execute("DELETE FROM inventory WHERE tg_id = ?", (tg_id,))
    await _db.commit()
    return cur.rowcount


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
    try:
        await _db.execute(
            """INSERT INTO businesses (tg_id, biz, tier, produce_at, upkeep_at)
               VALUES (?, ?, ?, ?, ?)""",
            (tg_id, biz, tier, produce_at, upkeep_at),
        )
        await _db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


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
