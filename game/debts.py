"""Долги: напоминания каждые 5 мин, дефолт через 2 дня → «Чепушила» на 5 дней."""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.utils.markdown import hlink

from db import storage
from utils.notify import announce

log = logging.getLogger(__name__)

NAG_MINUTES = 5
DEFAULT_DAYS = 2
CHEPUSHILA_DAYS = 5
NAG_KEY = "debt_nag"
CHEPUSHILA_KEY = "chepushila"


async def is_chepushila(tg_id: int) -> bool:
    return await storage.cooldown_left_secs(tg_id, CHEPUSHILA_KEY) > 0


async def chepushila_days_left(tg_id: int) -> int:
    secs = await storage.cooldown_left_secs(tg_id, CHEPUSHILA_KEY)
    return (secs + 86399) // 86400  # округление вверх до дней


async def schedule_first_nag(tg_id: int) -> None:
    """Поставить первое напоминание через NAG_MINUTES от взятия долга."""
    until = (datetime.now() + timedelta(minutes=NAG_MINUTES)).isoformat()
    await storage.set_cooldown_until(tg_id, NAG_KEY, until)


async def run_debts_scheduler(bot: Bot) -> None:
    try:
        while True:
            try:
                await _tick(bot)
            except Exception as e:
                log.exception("Долги: ошибка планировщика: %s", e)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("Планировщик долгов остановлен")
        raise


async def _tick(bot: Bot) -> None:
    now = datetime.now()

    # 1. «А когда вернёшь?» каждые 5 минут
    for borrower_id in await storage.distinct_debtors():
        if await storage.cooldown_left_secs(borrower_id, NAG_KEY) == 0:
            total = await storage.total_debt(borrower_id)
            if total <= 0:
                continue
            try:
                await bot.send_message(borrower_id, f"🤨 А когда вернёшь? За тобой долг <b>{total} Z</b>.")
            except Exception:
                pass
            await storage.set_cooldown_until(
                borrower_id, NAG_KEY, (now + timedelta(minutes=NAG_MINUTES)).isoformat())

    # 2. дефолт: долг старше 2 дней → «Чепушила»
    cutoff = (now - timedelta(days=DEFAULT_DAYS)).isoformat()
    for did, borrower_id, lender_nick, amount in await storage.debts_to_default(cutoff):
        await storage.mark_debt_defaulted(did)
        if not await is_chepushila(borrower_id):
            await storage.bump(borrower_id, "defaulted")
            await storage.set_honest(borrower_id, False)  # чепушила теряет «Честного человека»
            await storage.set_cooldown_until(
                borrower_id, CHEPUSHILA_KEY, (now + timedelta(days=CHEPUSHILA_DAYS)).isoformat())
            who = await _mention(borrower_id)
            await announce(bot, f"🤡 {who} не вернул долг за {DEFAULT_DAYS} дня и получил статус "
                                f"«Чепушила» — {CHEPUSHILA_DAYS} дней без легальной работы!")
            try:
                await bot.send_message(borrower_id, f"🤡 Ты не вернул долг и стал «Чепушилой» на "
                                                    f"{CHEPUSHILA_DAYS} дней. Легальная работа закрыта.")
            except Exception:
                pass

    # 3. снятие статуса по истечении 5 дней
    for tg_id in await storage.expired_statuses(CHEPUSHILA_KEY, now.isoformat()):
        await storage.clear_status(tg_id, CHEPUSHILA_KEY)
        who = await _mention(tg_id)
        await announce(bot, f"😇 С {who} снят статус «Чепушила». Можно снова честно работать.")
        try:
            await bot.send_message(tg_id, "😇 Статус «Чепушила» снят — легальная работа снова открыта!")
        except Exception:
            pass


async def _mention(tg_id: int) -> str:
    profile = await storage.get_profile(tg_id)
    return hlink(profile[2] if profile else "Игрок", f"tg://user?id={tg_id}")
