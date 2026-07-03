"""Константы и награда «Телефонного мошенника»."""

ROUNDS = 5
ATTEMPTS = 3          # попыток на персонажа (макс 15 попыток за игру)
COOLDOWN_MIN = 30
MAX_REWARD = 80       # награда за раунд при diff=1
MIN_REWARD = 30       # награда при diff=3
WINDOW = 3            # базовый допуск: |слова - цель| <= 3 даёт деньги
WINDOW_CROSS = 5      # с православным крестом — допуск до 5


def reward(diff: int, window: int = WINDOW) -> int:
    """Награда по отклонению. window=5 (крест) — слова 4 и 5 платят как 3-е."""
    if diff == 0:
        return MAX_REWARD * 2          # точное попадание — X2 (160)
    if diff > window:
        return 0
    d = min(diff, WINDOW)              # линейная часть только до 3-го слова
    return MAX_REWARD - (d - 1) * (MAX_REWARD - MIN_REWARD) // (WINDOW - 1)
