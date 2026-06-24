"""Чистая математика опыта и уровней.

Цена уровня растёт: уровень N стоит N×step опыта.
=> суммарный опыт, чтобы достичь уровня N, треугольный:
   xp_for_level(N) = step × N(N+1)/2
Zbucks за достижение уровня N = N × (step/10)  («отбрасываем последний ноль»).
"""
from config import config


def xp_for_level(n: int) -> int:
    """Суммарный опыт, необходимый, чтобы достичь уровня n (level 0 = 0)."""
    if n <= 0:
        return 0
    return config.xp_level_step * n * (n + 1) // 2


def level_from_xp(xp: int) -> int:
    """Текущий уровень по суммарному опыту."""
    n = 0
    while xp_for_level(n + 1) <= xp:
        n += 1
    return n


def zbucks_for_level(n: int) -> int:
    """Награда Zbucks за достижение уровня n."""
    return n * (config.xp_level_step // 10)


def daily_xp(minutes: int) -> int:
    """Сколько опыта начислить за день при `minutes` минутах на сервере."""
    if minutes <= 0:
        return config.xp_daily_quota * config.xp_noplay_multiplier
    earned = config.xp_daily_quota - minutes * config.xp_decay_per_minute
    return max(config.xp_min, earned)
