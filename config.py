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

    # Куб
    cube_reset_minutes: int = _int("CUBE_RESET_MINUTES", 60)
    cube_lobby_seconds: int = _int("CUBE_LOBBY_SECONDS", 180)
    cube_entry_cost: int = _int("CUBE_ENTRY_COST", 500)
    cube_prize_per_participant: int = _int("CUBE_PRIZE_PER_PARTICIPANT", 1000)
    cube_max_participants: int = _int("CUBE_MAX_PARTICIPANTS", 16)

    def __post_init__(self) -> None:
        positive = {
            "CUBE_RESET_MINUTES": self.cube_reset_minutes,
            "CUBE_LOBBY_SECONDS": self.cube_lobby_seconds,
            "CUBE_ENTRY_COST": self.cube_entry_cost,
            "CUBE_PRIZE_PER_PARTICIPANT": self.cube_prize_per_participant,
        }
        invalid = [name for name, value in positive.items() if value <= 0]
        if invalid:
            raise ValueError(f"{', '.join(invalid)} должны быть положительными")
        if self.cube_lobby_seconds >= self.cube_reset_minutes * 60:
            raise ValueError(
                "CUBE_LOBBY_SECONDS должен быть меньше общего срока CUBE_RESET_MINUTES"
            )
        if not 1 <= self.cube_max_participants <= 16:
            raise ValueError("CUBE_MAX_PARTICIPANTS должен быть в диапазоне 1..16")


config = Config()
