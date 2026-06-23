"""Хранилище: игроки (для детекта новичков) и профили ZakharCompanion."""
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
        """
    )
    await _db.commit()


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
    """Вернуть (tg_id, username, nick, zbucks) или None."""
    cur = await _db.execute(
        "SELECT tg_id, username, nick, zbucks FROM profiles WHERE tg_id = ?", (tg_id,)
    )
    return await cur.fetchone()


async def add_zbucks(tg_id: int, amount: int) -> None:
    await _db.execute(
        "UPDATE profiles SET zbucks = zbucks + ? WHERE tg_id = ?", (amount, tg_id)
    )
    await _db.commit()
