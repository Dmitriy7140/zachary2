"""Ставки: фоновый планировщик и расчёт выплат по букмекерским правилам."""
import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import config
from db import storage
from utils.notify import announce

log = logging.getLogger(__name__)

SIDE_NAMES = {"yes": "Сыграет", "no": "Не сыграет"}
BET_WINDOW_HOURS = 2  # приём ставок


async def run_bets_scheduler(bot: Bot) -> None:
    try:
        while True:
            try:
                await _tick(bot)
            except Exception as e:
                log.exception("Ставки: ошибка планировщика: %s", e)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("Планировщик ставок остановлен")
        raise


async def _tick(bot: Bot) -> None:
    now = datetime.now().isoformat()
    for eid in await storage.events_due_close(now):
        await storage.set_event_status(eid, "closed")
        ev = await storage.get_event(eid)
        await announce(bot, f"🎲 Приём ставок по «{ev[3]}» закрыт. Ждём результат.")
    for eid in await storage.events_due_resolve(now):
        await storage.set_event_status(eid, "pending")
        await _ask_admin(bot, eid)


async def _ask_admin(bot: Bot, eid: int) -> None:
    ev = await storage.get_event(eid)
    yes_pool, no_pool = await storage.event_pools(eid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Сыграла", callback_data=f"bets:resolve:{eid}:yes"),
        InlineKeyboardButton(text="❌ Не сыграла", callback_data=f"bets:resolve:{eid}:no"),
    ]])
    try:
        sent = await bot.send_message(
            config.admin_id,
            f"❓ <b>Сыграла ли ставка #{eid}?</b>\n«{ev[3]}»\n"
            f"Банк: ✅ {yes_pool} Z / ❌ {no_pool} Z",
            reply_markup=kb,
        )
        try:
            await bot.pin_chat_message(config.admin_id, sent.message_id)
        except Exception:
            pass
    except Exception as e:
        log.warning("Не смог спросить админа по ставке %s: %s", eid, e)


async def resolve_event(bot: Bot, eid: int, outcome: str) -> bool:
    """Развязка события: выплаты + объявление. False, если уже разрешено."""
    ev = await storage.get_event(eid)
    if not ev or ev[7] == "resolved":
        return False

    stakes = await storage.event_stakes(eid)
    winners = [(t, a) for t, s, a in stakes if s == outcome]
    losers_pool = sum(a for t, s, a in stakes if s != outcome)
    await storage.resolve_event_db(eid, outcome)

    if not winners:
        # никто не угадал — возвращаем ставки всем
        for t, s, a in stakes:
            await storage.add_zbucks(t, a)
        detail = "Никто не угадал — ставки вернулись игрокам."
    else:
        share = losers_pool // len(winners)
        for tg_id, amount in winners:
            await storage.add_zbucks(tg_id, amount + share)  # своя ставка + доля банка
        detail = (f"Победителей: {len(winners)}. Банк проигравших {losers_pool} Z "
                  f"разделён поровну — по +{share} Z сверх своей ставки.")

    await announce(bot, f"🎲 Итог «{ev[3]}»: <b>{SIDE_NAMES[outcome]}</b>!\n{detail}")
    return True
