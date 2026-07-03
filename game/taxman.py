"""Густав Налоговик: грязные деньги, тайные проверки и рейды с предупреждением.

Грязные источники дохода: Вор, Телефонный мошенник, выигрыш в рулетке, взятый
долг. Всё остальное (кассир, курьер, рынок, коза, Вовка, ставки, опыт) — легально.

Механика: на каждой новой тысяче выше 5000 Густав ТАЙНО проверяет игрока.
Чисто — молчит. Есть грязные — публично объявляет в тред, что выезжает с
проверкой, и через RAID_MINUTES приходит рейд:
  • грязные ещё есть → взятка 50% от них, остаток легализуется;
  • успел избавиться (траты списывают сначала грязные) → ушёл ни с чем.

Весь ДОХОД должен идти через grant(). Срок рейда хранится в cooldowns
(ключ RAID_KEY), так что рестарт бота проверку не отменяет.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.utils.markdown import hlink

from content.gustav import (bribe_personal, bribe_thread, evaded_thread, warn_personal,
                            warn_thread)
from db import storage
from utils.notify import announce

log = logging.getLogger(__name__)

THRESHOLD = 5000     # с этого баланса Густав начинает ходить
STEP = 1000          # тайная проверка на каждой новой тысяче
BRIBE_PCT = 50       # % от грязных денег в виде взятки
RAID_KEY = "gustav_raid"
RAID_MINUTES = 10    # сколько даём на «избавиться от грязного»


async def grant(bot: Bot, tg_id: int, amount: int, *, dirty: bool = False) -> None:
    """Начислить доход. dirty=True — нелегальный источник."""
    if amount <= 0:
        return
    profile = await storage.get_profile(tg_id)
    if not profile:
        await storage.add_zbucks(tg_id, amount)
        return
    old = profile[3]
    await storage.add_zbucks(tg_id, amount)
    if dirty:
        await storage.add_dirty(tg_id, amount)
    await maybe_gustav(bot, tg_id, old, old + amount)


async def maybe_gustav(bot: Bot, tg_id: int, old: int, new: int) -> None:
    """Тайная проверка, если доход пересёк новую тысячу выше THRESHOLD."""
    if new // STEP <= old // STEP:
        return  # тысячу не пересекли
    if (new // STEP) * STEP <= THRESHOLD:
        return  # пересечённая тысяча ещё не выше 5000
    if await storage.cooldown_left_secs(tg_id, RAID_KEY) > 0:
        return  # рейд уже назначен — второй раз не предупреждаем

    dirty = await storage.get_dirty(tg_id)
    if dirty <= 0:
        return  # проверка тайная: чисто — молчим

    until = (datetime.now() + timedelta(minutes=RAID_MINUTES)).isoformat()
    await storage.set_cooldown_until(tg_id, RAID_KEY, until)
    log.info("Густав заприметил %s: %d Z грязных, рейд через %d мин", tg_id, dirty, RAID_MINUTES)

    profile = await storage.get_profile(tg_id)
    who = hlink(profile[2] if profile else "Игрок", f"tg://user?id={tg_id}")
    await announce(bot, warn_thread(who, RAID_MINUTES))
    try:
        await bot.send_message(tg_id, warn_personal(RAID_MINUTES))
    except Exception:
        pass


async def run_gustav_scheduler(bot: Bot) -> None:
    """Фоновый цикл: добивает рейды, у которых вышли 10 минут."""
    try:
        while True:
            try:
                await _tick(bot)
            except Exception as e:
                log.exception("Густав: ошибка планировщика: %s", e)
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        log.info("Планировщик Густава остановлен")
        raise


async def _tick(bot: Bot) -> None:
    for tg_id in await storage.expired_statuses(RAID_KEY, datetime.now().isoformat()):
        await storage.clear_status(tg_id, RAID_KEY)
        await _raid(bot, tg_id)


async def _raid(bot: Bot, tg_id: int) -> None:
    """Рейд по истечении срока: взятка или «ушёл ни с чем»."""
    dirty = await storage.get_dirty(tg_id)
    profile = await storage.get_profile(tg_id)
    who = hlink(profile[2] if profile else "Игрок", f"tg://user?id={tg_id}")

    if dirty <= 0:
        # успел избавиться — публичная развязка, раз предупреждение было публичным
        await storage.bump(tg_id, "gustav_evaded")
        await announce(bot, evaded_thread(who))
        return

    bribe = dirty * BRIBE_PCT // 100
    if bribe > 0:
        await storage.spend_zbucks(tg_id, bribe)
    await storage.set_dirty(tg_id, 0)  # всё оставшееся легализовано
    await storage.bump(tg_id, "gustav_paid", bribe)
    log.info("Густав взял у %s взятку %d Z (грязных было %d)", tg_id, bribe, dirty)

    try:
        await bot.send_message(tg_id, bribe_personal(bribe, dirty))
    except Exception:
        pass
    await announce(bot, bribe_thread(who, bribe))
