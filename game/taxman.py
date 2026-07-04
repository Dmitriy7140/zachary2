"""Густав Налоговик: грязные деньги, тайные проверки и рейды с предупреждением.

Грязные источники дохода: Вор, Телефонный мошенник, выигрыш в рулетке.
Займы наследуют статус денег кредитора/должника (dirty_part в grant):
сколько грязных ушло у одного — столько грязных пришло другому.
Всё остальное (кассир, курьер, рынок, коза, Вовка, ставки, опыт) — легально.

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

from content.gustav import (bribe_personal, bribe_thread, evaded_hidden, evaded_thread,
                            warn_personal, warn_thread)
from db import storage
from db.storage import HIDE_CD_KEY, HIDE_KEY, hidden_meta_key  # noqa: F401 (ре-экспорт)
from utils.notify import announce

log = logging.getLogger(__name__)

THRESHOLD = 5000     # с этого баланса Густав начинает ходить
STEP = 1000          # тайная проверка на каждой новой тысяче
BRIBE_PCT = 50       # % от грязных денег в виде взятки
RAID_KEY = "gustav_raid"
RAID_MINUTES = 10    # сколько даём на «избавиться от грязного»

# прятки (меню «Махинации»): деньги остаются на счету и остаются грязными,
# просто Густав их не находит, пока прятка активна. Спрятанное нельзя ни
# потратить, ни украсть (проверки в storage.spend_zbucks / handlers.work).
# Ключи и hidden_now живут в storage — отсюда ре-экспортируются для хендлеров.
HIDE_MINUTES = 2     # в этом вся соль — подгадать момент
HIDE_COOLDOWN_MIN = 5   # кд от нажатия до следующей прятки
HIDE_CAP = 5000      # носки + трусы + рот + ноздри/уши + жопа
HIDE_CAP_IPHONE = 4000  # у владельцев айфона очко растянуто — жопа не держит


async def active_hidden(tg_id: int) -> int:
    """Сколько Z сейчас спрятано (0, если прятка не активна)."""
    return await storage.hidden_now(tg_id)


async def grant(bot: Bot, tg_id: int, amount: int, *, dirty: bool = False,
                dirty_part: int | None = None) -> None:
    """Начислить доход.

    dirty=True — вся сумма нелегальная; dirty_part=N — грязная только часть
    (наследование статуса при займах/возвратах долгов).
    """
    if amount <= 0:
        return
    profile = await storage.get_profile(tg_id)
    if not profile:
        await storage.add_zbucks(tg_id, amount)
        return
    old = profile[3]
    await storage.add_zbucks(tg_id, amount)
    dirty_add = amount if dirty else min(dirty_part or 0, amount)
    if dirty_add > 0:
        await storage.add_dirty(tg_id, dirty_add)
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
    """Рейд по истечении срока: взятка с НАЙДЕННОГО или «ушёл ни с чем».

    Спрятанное (прятка активна) Густав не видит: оно не трогается и остаётся
    грязным. Всё найденное после взятки легализуется. Проверка в любом случае
    оканчивается — до следующей заработанной тысячи.
    """
    dirty = await storage.get_dirty(tg_id)
    hidden = min(await active_hidden(tg_id), dirty)
    found = dirty - hidden
    profile = await storage.get_profile(tg_id)
    who = hlink(profile[2] if profile else "Игрок", f"tg://user?id={tg_id}")

    if found <= 0:
        # избавился или спрятал — публичная развязка, раз предупреждение было публичным
        await storage.bump(tg_id, "gustav_evaded")
        await announce(bot, evaded_hidden(who) if hidden > 0 else evaded_thread(who))
        return

    bribe = found * BRIBE_PCT // 100
    if bribe > 0:
        await storage.spend_zbucks(tg_id, bribe)
    await storage.set_dirty(tg_id, hidden)  # найденное легализовано, спрятанное — грязное
    await storage.bump(tg_id, "gustav_paid", bribe)
    log.info("Густав нашёл у %s %d Z грязных (спрятано %d), взятка %d Z",
             tg_id, found, hidden, bribe)

    try:
        await bot.send_message(tg_id, bribe_personal(bribe, found))
    except Exception:
        pass
    await announce(bot, bribe_thread(who, bribe))
