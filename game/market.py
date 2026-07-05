"""Планировщик рынка: добивает продажи, у которых вышел срок.

Продажа = поставка на рынок: проданное падает в общий сток (market_stock)
и продаётся другим игрокам с наценкой MARKUP_PCT. Лот продаётся ВЕСЬ разом
по своему таймеру. Одновременно у игрока в продаже не больше SELL_LIMIT штук.
"""
import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.utils.markdown import hlink

from content.zhmyzhko import proletarian
from db import storage
from game.items import ITEMS
from game.taxman import grant
from utils.notify import announce

log = logging.getLogger(__name__)

MARKUP_PCT = 10     # наценка рынка при перепродаже игрокам
SELL_LIMIT = 20     # штук одновременно в продаже у одного игрока


def buy_price(sell_price: int) -> int:
    """Цена в стакане покупки: +10%, округление вверх (80 → 88, 45 → 50)."""
    return (sell_price * (100 + MARKUP_PCT) + 99) // 100


async def run_market_scheduler(bot: Bot) -> None:
    try:
        while True:
            try:
                await _process_due(bot)
            except Exception as e:
                log.exception("Рынок: ошибка обработки: %s", e)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("Планировщик рынка остановлен")
        raise


async def _process_due(bot: Bot) -> None:
    for lid, tg_id, item, price, qty in await storage.due_listings(datetime.now().isoformat()):
        await storage.remove_listing(lid)
        qty = qty or 1
        total = price * qty
        await grant(bot, tg_id, total)  # продажа на рынке — легальна
        await storage.bump(tg_id, f"sold_{item}", qty)
        # проданное уезжает в стакан покупки с наценкой
        await storage.add_stock(item, buy_price(price), qty)
        it = ITEMS.get(item)
        label = f"{it.emoji} {it.name}" if it else item
        cnt = f" ×{qty}" if qty > 1 else ""

        try:
            await bot.send_message(tg_id, f"🏪 Продано: {label}{cnt} за <b>{total} Z</b>!")
        except Exception:
            pass

        profile = await storage.get_profile(tg_id)
        nick = profile[2] if profile else "Игрок"
        seller = hlink(nick, f"tg://user?id={tg_id}")
        await announce(bot, f"🏪 {seller} продал {label}{cnt} за {total} Z на рынке.\n{proletarian()}")
