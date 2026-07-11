"""Рыбалка: уровни, шансы, планировщик улова."""
import asyncio
import logging
import random
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db import storage
from game.items import ITEMS

log = logging.getLogger(__name__)

CAST_MINUTES = 10
ITEM_CHANCE = 0.05  # шанс вместо рыбы выловить случайный ДРУГОЙ предмет (любой)

# рыб для уровня
LEVEL_THRESHOLDS = {2: 50, 3: 100}
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


def fish_to_next_level(fish_caught: int) -> int | None:
    """Сколько рыб до следующего уровня (None — уровень максимальный)."""
    level = fishing_level(fish_caught)
    if level >= 3:
        return None
    return LEVEL_THRESHOLDS[level + 1] - fish_caught


def roll_catch(level: int, bait_tier: int) -> str | None:
    """Вернуть ключ пойманного ('fish_N' или любой другой предмет) или None (пусто).

    5% — из пруда вытаскивается случайный НЕ-рыбный предмет реестра:
    от бидона молока до тачки (кто-то утопил, бывает).
    """
    if random.random() < ITEM_CHANCE:
        return random.choice([k for k in ITEMS if not k.startswith("fish_")])
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
            if await storage.get_item_qty(tg_id, catch) >= it.max_qty:
                text = (f"🎣 Выловил {it.emoji} <b>{it.name}</b>… но такой у тебя "
                        f"уже есть — выбросил обратно в пруд.")
            else:
                await storage.add_item(tg_id, catch, 1, it.max_qty)
                if catch.startswith("fish_"):
                    await storage.bump(tg_id, "fish_caught")
                    text = f"🎣 Есть улов! Поймал {it.emoji} <b>{it.name}</b>."
                else:
                    text = (f"🎣 Охренеть! Вместо рыбы из пруда вытащил "
                            f"{it.emoji} <b>{it.name}</b>! Кто-то утопил, видимо.")

        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🎣 Закинуть снова",
                                 callback_data=f"fish:again:{bait_tier}")
        ]])
        try:
            await bot.send_message(tg_id, text, reply_markup=kb)
        except Exception:
            pass
