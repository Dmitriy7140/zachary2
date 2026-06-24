import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int = 0) -> int:
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else default


@dataclass
class Config:
    # Telegram
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admin_id: int = _int("ADMIN_ID")
    channel_id: int = _int("CHANNEL_ID")
    thread_id: int = _int("THREAD_ID")

    # Minecraft RCON
    rcon_host: str = os.getenv("RCON_HOST", "127.0.0.1")
    rcon_port: int = _int("RCON_PORT", 25575)
    rcon_password: str = os.getenv("RCON_PASSWORD", "")

    # Прочее
    poll_interval: int = _int("POLL_INTERVAL", 20)
    db_path: str = os.getenv("DB_PATH", "zachary.db")

    # Опыт / уровни
    xp_daily_quota: int = _int("XP_DAILY_QUOTA", 1000)       # базовая квота опыта в день
    xp_min: int = _int("XP_MIN", 200)                        # пол: меньше за день не дадут
    xp_noplay_multiplier: int = _int("XP_NOPLAY_MULT", 2)    # ×N, если не заходил совсем
    xp_decay_per_minute: int = _int("XP_DECAY_PER_MINUTE", 5)  # сколько отнимать за минуту игры
    xp_level_step: int = _int("XP_LEVEL_STEP", 1000)         # уровень N стоит N×step опыта


config = Config()
