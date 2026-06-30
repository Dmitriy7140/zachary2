"""Следим за самым богатым игроком: при смене лидера — оповещение в тред."""
import asyncio
import logging

from aiogram import Bot
from aiogram.utils.markdown import hlink

from db import storage
from utils.notify import announce

log = logging.getLogger(__name__)

META_KEY = "richest"


async def run_richest_watcher(bot: Bot) -> None:
    try:
        while True:
            try:
                await _check(bot)
            except Exception as e:
                log.exception("Богач: ошибка: %s", e)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("Наблюдатель богача остановлен")
        raise


async def _check(bot: Bot) -> None:
    r = await storage.richest_player()
    if not r:
        return
    tg_id, nick, zbucks = r
    if zbucks <= 0:
        return
    if str(tg_id) == await storage.get_meta(META_KEY):
        return  # лидер не сменился
    await storage.set_meta(META_KEY, str(tg_id))
    who = hlink(nick, f"tg://user?id={tg_id}")
    await announce(bot, f"👑 {who} теперь самый богатый игрок — <b>{zbucks} Z</b>!")
