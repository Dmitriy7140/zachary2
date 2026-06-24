"""Ежесуточный пересчёт опыта в 00:00 по локальному времени сервера."""
import asyncio
import logging
from datetime import datetime, time, timedelta

from aiogram import Bot
from aiogram.utils.markdown import hlink

from config import config
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

    blocks = []
    for tg_id, nick, xp, level in profiles:
        minutes = playtime.get(nick, 0) // 60
        gained = daily_xp(minutes)
        new_xp = xp + gained
        new_level = level_from_xp(new_xp)
        zbucks_gain = sum(
            zbucks_for_level(lvl) for lvl in range(level + 1, new_level + 1)
        )
        await storage.apply_daily_xp(tg_id, new_xp, new_level, zbucks_gain)
        blocks.append(
            _report_block(tg_id, nick, minutes, gained, level, new_level, new_xp, zbucks_gain)
        )

    await storage.clear_playtime(day)

    if blocks:
        text = f"📊 <b>Итоги дня {day}</b>\n\n" + "\n\n".join(blocks)
        await bot.send_message(
            chat_id=config.channel_id,
            message_thread_id=config.thread_id or None,
            text=text,
        )


def _report_block(tg_id, nick, minutes, gained, old_level, new_level, new_xp, zbucks_gain) -> str:
    name = hlink(nick, f"tg://user?id={tg_id}")
    to_next = xp_for_level(new_level + 1) - new_xp
    block = f"{rank(new_level)} {name} — ⏱ {minutes}м, ✨ +{gained}"
    if new_level > old_level:
        block += f"\n   🎉 уровень {old_level} → {new_level}, 💰 +{zbucks_gain} Z"
    block += f"\n   🎯 до ур.{new_level + 1}: {to_next} опыта"
    return block
