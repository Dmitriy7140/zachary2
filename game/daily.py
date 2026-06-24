"""Ежесуточный пересчёт опыта в 00:00 по локальному времени сервера."""
import asyncio
import logging
from datetime import datetime, time, timedelta

from aiogram import Bot

from content.ranks import rank
from db import storage
from game.leveling import daily_xp, level_from_xp, xp_for_level, zbucks_for_level

log = logging.getLogger(__name__)


def _seconds_until_midnight() -> float:
    now = datetime.now()
    nxt = datetime.combine(now.date() + timedelta(days=1), time.min)
    return (nxt - now).total_seconds()


async def run_daily_scheduler(bot: Bot) -> None:
    """Каждую полночь считает опыт за прошедший день.

    Ограничение: если бот выключен в момент полуночи, этот день не
    обсчитывается (чтобы не раздать ×2 всем из-за отсутствия данных).
    """
    try:
        while True:
            await asyncio.sleep(_seconds_until_midnight())
            yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
            try:
                await process_day(bot, yesterday)
            except Exception as e:
                log.exception("Дневной пересчёт опыта упал: %s", e)
    except asyncio.CancelledError:
        log.info("Планировщик опыта остановлен")
        raise


async def process_day(bot: Bot, day: str) -> None:
    playtime = await storage.get_day_playtime(day)
    profiles = await storage.all_profiles()
    log.info("Пересчёт опыта за %s: %d профил(ей)", day, len(profiles))

    for tg_id, nick, xp, level in profiles:
        minutes = playtime.get(nick, 0) // 60
        gained = daily_xp(minutes)
        new_xp = xp + gained
        new_level = level_from_xp(new_xp)
        zbucks_gain = sum(
            zbucks_for_level(lvl) for lvl in range(level + 1, new_level + 1)
        )
        await storage.apply_daily_xp(tg_id, new_xp, new_level, zbucks_gain)
        await _notify(bot, tg_id, nick, minutes, gained, level, new_level, new_xp, zbucks_gain)

    await storage.clear_playtime(day)


async def _notify(bot, tg_id, nick, minutes, gained, old_level, new_level, new_xp, zbucks_gain):
    to_next = xp_for_level(new_level + 1) - new_xp
    lines = [
        f"📊 Итоги дня, <b>{nick}</b>:",
        f"⏱ наиграно: {minutes} мин",
        f"✨ опыт: <b>+{gained}</b> (всего {new_xp})",
    ]
    if new_level > old_level:
        lines.append(f"🎉 уровень <b>{old_level} → {new_level}</b> — {rank(new_level)}!")
        lines.append(f"💰 начислено <b>{zbucks_gain} Z</b>")
    lines.append(f"🎯 до следующего уровня: {to_next} опыта")
    try:
        await bot.send_message(tg_id, "\n".join(lines))
    except Exception:
        pass  # игрок не писал боту
