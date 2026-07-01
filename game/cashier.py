"""Константы и ранги работы «Кассир»."""

ROUNDS = 30
COOLDOWN_MIN = 30
OTMENA_CHANCE = 0.12          # шанс события «ОТМЕНА» в раунде
ZHMYZHKO_CHANCE = 0.3         # шанс сценки с Паном Жмыжко при ошибке
SENIOR_GAMES = 20             # смен до повышения в Старшего кассира

GALYA_BONUS = {"junior": 10, "senior": 20}
GALYA_TIME = {"junior": 5, "senior": 10}
LEVEL_NAMES = {"junior": "Младший кассир", "senior": "Старший кассир"}


def level(games: int) -> str:
    return "senior" if games >= SENIOR_GAMES else "junior"


def level_name(games: int) -> str:
    return LEVEL_NAMES[level(games)]
