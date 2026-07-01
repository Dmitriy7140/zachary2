"""Рыбалка: уровни, шансы, планировщик улова."""
import asyncio
import logging
import random
from datetime import datetime

from aiogram import Bot

from db import storage
from game.items import ITEMS

log = logging.getLogger(__name__)

CAST_MINUTES = 10
MILK_CHANCE = 0.05

# рыб для уровня
LEVEL_THRESHOLDS = {2: 200, 3: 500}
# шанс поймать рыбу тира T на уровне L
CHANCE = {
    1: {1: 0.50},
    2: {1: 0.75, 2: 0.50},
    3: {1: 1.00, 2: 0.75, 3: 0.50},
}
BAIT_ITEMS = {1: "bait_1", 2: "bait_2", 3: "bait_3"}
FISH_ITEMS = {1: "fish_1", 2: "fish_2", 3: "fish_3"}
BAIT_TIER = {"bait_1": 1, "bait_2": 2, "bait_3": 3}  # какой уровень нужен, чтобы ловить


def fishing_level(fish_caught: int) -> int:
    if fish_caught >= LEVEL_THRESHOLDS[3]:
        return 3
    if fish_caught >= LEVEL_THRESHOLDS[2]:
        return 2
    return 1


def roll_catch(level: int, bait_tier: int) -> str | None:
    """Вернуть ключ пойманного предмета ('milk_can' / 'fish_N') или None (пусто)."""
    if random.random() < MILK_CHANCE:
        return "milk_can"
    chance = CHANCE.get(level, {}).get(bait_tier, 0)
    if random.random() < chance:
        return FISH_ITEMS[bait_tier]
    return None


async def run_fishing_scheduler(bot: Bot) -> None:
    try:
        while True:
            try:
                await _process_due(bot)
            except Exception as e:
                log.exception("Рыбалка: ошибка: %s", e)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("Планировщик рыбалки остановлен")
        raise


async def _process_due(bot: Bot) -> None:
    for cast_id, tg_id, bait_tier in await storage.due_casts(datetime.now().isoformat()):
        await storage.remove_cast(cast_id)
        level = fishing_level(await storage.player_stat(tg_id, "fish_caught"))
        catch = roll_catch(level, bait_tier)

        if catch is None:
            text = "🎣 Сорвалось! Улов пуст."
        else:
            it = ITEMS[catch]
            await storage.add_item(tg_id, catch, 1, it.max_qty)
            if catch.startswith("fish_"):
                await storage.bump(tg_id, "fish_caught")
            text = f"🎣 Есть улов! Поймал {it.emoji} <b>{it.name}</b>."

        try:
            await bot.send_message(tg_id, text)
        except Exception:
            pass
