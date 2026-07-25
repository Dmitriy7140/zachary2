"""Прогрессия и надбавки нелегальных работ."""
from dataclasses import dataclass


# Для мошенника: 20, затем ещё 25/30/35 удачных обзвонов.
SCAMMER_LEVEL_THRESHOLDS = (0, 20, 45, 75, 110)
# У продавца VPN каждая ступень требует вдвое больше успешных продаж.
VPN_LEVEL_THRESHOLDS = (0, 40, 90, 150, 220)


@dataclass(frozen=True)
class JobRank:
    name: str
    bonus_pct: int


SCAMMER_RANKS = (
    JobRank("Обманщик детей в Роблоксе", 0),
    JobRank("Аферист из магазина косметики", 10),
    JobRank("Мошенник из Бесбанка", 20),
    JobRank("Гроза бабулек", 30),
    JobRank("Человек-созвон", 100),
)

VPN_RANKS = (
    JobRank("Впариватель сомнительных конфигов", 10),
    JobRank("Джун-девопс", 20),
    JobRank("Девопс", 30),
    JobRank("Кибербезопасник", 40),
    JobRank("Хакер инсультов", 100),
)


def rank_for_successes(
    ranks: tuple[JobRank, ...], thresholds: tuple[int, ...], successes: int,
) -> tuple[int, JobRank]:
    """Вернуть 1-based уровень и звание по числу удачных действий."""
    level = 1
    for index, needed in enumerate(thresholds, start=1):
        if successes >= needed:
            level = index
    return level, ranks[level - 1]


def scammer_rank(successes: int) -> tuple[int, JobRank]:
    return rank_for_successes(SCAMMER_RANKS, SCAMMER_LEVEL_THRESHOLDS, successes)


def vpn_rank(successes: int) -> tuple[int, JobRank]:
    return rank_for_successes(VPN_RANKS, VPN_LEVEL_THRESHOLDS, successes)


def successes_to_next_level(thresholds: tuple[int, ...], successes: int) -> int | None:
    """Сколько успешных действий нужно до следующей ступени, либо None на максимуме."""
    for needed in thresholds:
        if successes < needed:
            return needed - successes
    return None


def reward_with_rank_bonus(base_reward: int, bonus_pct: int) -> int:
    """Надбавка всегда округляется вниз до целого Z."""
    return base_reward * (100 + bonus_pct) // 100
