"""Планировщик рынка: добивает продажи, у которых вышел срок."""
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
        total = price * (qty or 1)
        await grant(bot, tg_id, total)  # продажа на рынке — легальна
        await storage.bump(tg_id, f"sold_{item}", qty or 1)
        it = ITEMS.get(item)
        label = f"{it.emoji} {it.name}" if it else item
        cnt = f" ×{qty}" if (qty or 1) > 1 else ""

        try:
            await bot.send_message(tg_id, f"🏪 Продано: {label}{cnt} за <b>{total} Z</b>!")
        except Exception:
            pass

        profile = await storage.get_profile(tg_id)
        nick = profile[2] if profile else "Игрок"
        seller = hlink(nick, f"tg://user?id={tg_id}")
        await announce(bot, f"🏪 {seller} продал {label}{cnt} за {total} Z на рынке.\n{proletarian()}")
