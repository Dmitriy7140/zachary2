"""Математика работы «Вор»."""
import random

# Сколько успешных краж нужно для уровней 1..5
THEFT_THRESHOLDS = [0, 5, 15, 30, 50]

QUALITIES = ["КУ", "ВУ", "НОУ", "СБ"]          # от лучшей к худшей
PROFIT_PCT = {"КУ": 90, "ВУ": 70, "НОУ": 50, "СБ": 30}  # % от состояния цели
MIN_TARGET_WEALTH = 20


def max_steal(level: int) -> int:
    """Потолок кражи растёт с уровнем: 400/600/800/1000/1200."""
    return 200 + 200 * level


def thief_level(thefts: int) -> int:
    lvl = 1
    for i, need in enumerate(THEFT_THRESHOLDS):
        if thefts >= need:
            lvl = i + 1
    return lvl


def fail_chance(level: int, reduction: int = 0) -> int:
    return max(0, 50 - 10 * (level - 1) - reduction)


def is_fail(level: int, reduction: int = 0) -> bool:
    return random.random() * 100 < fail_chance(level, reduction)


def roll_quality(level: int) -> str:
    bonus = 3 * (level - 1)
    weights = [12 + bonus, 16 + bonus, 23 + bonus, 49 + bonus]
    return random.choices(QUALITIES, weights=weights)[0]


def steal_amount(quality: str, target_wealth: int, level: int) -> int:
    return min(int(target_wealth * PROFIT_PCT[quality] / 100), max_steal(level))
