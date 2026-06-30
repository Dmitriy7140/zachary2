"""Статистика: /allstats (по серверу) и /mystats (личная)."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from content.ranks import rank
from db import storage

router = Router()


def _top(row, suffix: str = "") -> str:
    if not row:
        return "—"
    nick, val = row
    return f"{nick} ({val}{suffix})"


@router.message(Command("allstats"))
async def allstats(msg: Message):
    lost = await storage.stat_sum("casino_lost")
    won = await storage.stat_sum("casino_won")
    lines = [
        "📊 <b>Статистика сервера</b>",
        "",
        f"🦹 Самая частая жертва краж: <b>{_top(await storage.stat_top('robbed'), ' раз')}</b>",
        f"🎰 Просажено в казино: <b>{lost} Z</b> (отыграно {won} Z)",
        f"🥊 Заработано на «Бей Вовку»: <b>{await storage.stat_sum('vovka_won')} Z</b>",
        f"🥛 Продано молока: <b>{await storage.stat_sum('sold_milk_can')}</b> шт",
        f"🐐 Раз подоили козу: <b>{await storage.stat_sum('goat_milked')}</b>",
        f"🤲 Чаще всего брал в долг: <b>{_top(await storage.stat_top('borrowed'), ' раз')}</b>",
        f"🤡 Главный чепушила: <b>{_top(await storage.stat_top('defaulted'), ' раз')}</b>",
    ]
    await msg.answer("\n".join(lines))


@router.message(Command("mystats"))
async def mystats(msg: Message):
    tg_id = msg.from_user.id
    profile = await storage.get_profile(tg_id)
    if not profile:
        return await msg.answer("Сначала зарегистрируйся 😉")
    _, _, nick, zbucks, xp, level = profile
    thefts = await storage.get_thefts(tg_id)

    async def st(key):
        return await storage.player_stat(tg_id, key)

    lines = [
        f"📊 <b>Статистика — {nick}</b>",
        f"⭐ Уровень {level} ({rank(level)}) · 💰 {zbucks} Z",
        "",
        f"🦹 Удачных краж: <b>{thefts}</b> · обворовали тебя: <b>{await st('robbed')}</b>",
        f"🎰 Казино: проиграно <b>{await st('casino_lost')} Z</b>, в плюс <b>{await st('casino_won')} Z</b>",
        f"🥊 «Бей Вовку»: заработано <b>{await st('vovka_won')} Z</b>",
        f"🥛 Продано молока: <b>{await st('sold_milk_can')}</b> шт",
        f"🐐 Доил козу: <b>{await st('goat_milked')}</b> раз",
        f"🤲 Брал в долг: <b>{await st('borrowed')}</b> раз",
        f"🤡 Был чепушилой: <b>{await st('defaulted')}</b> раз",
    ]
    await msg.answer("\n".join(lines))
