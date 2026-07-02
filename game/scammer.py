"""Константы и награда «Телефонного мошенника»."""

ROUNDS = 5
ATTEMPTS = 3          # попыток на персонажа (макс 15 попыток за игру)
COOLDOWN_MIN = 30
MAX_REWARD = 80       # награда за раунд при diff=1
MIN_REWARD = 30       # награда при diff=WINDOW
WINDOW = 3            # допуск: |слова - цель| <= WINDOW даёт деньги


def reward(diff: int) -> int:
    """Награда по отклонению числа слов от цели."""
    if diff == 0:
        return MAX_REWARD * 2          # точное попадание — X2 (160)
    if diff > WINDOW:
        return 0
    # линейно от MAX (diff=1) до MIN (diff=WINDOW)
    return MAX_REWARD - (diff - 1) * (MAX_REWARD - MIN_REWARD) // (WINDOW - 1)
