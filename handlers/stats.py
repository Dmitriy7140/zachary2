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
    bets_total = await storage.stat_sum("bets_won") + await storage.stat_sum("bets_lost")
    rich = await storage.richest_player()
    rich_str = f"{rich[1]} ({rich[2]} Z)" if rich else "—"
    lines = [
        "📊 <b>Статистика сервера</b>",
        "",
        f"👑 Самый богатый: <b>{rich_str}</b>",
        f"🦹 Самая частая жертва краж: <b>{_top(await storage.stat_top('robbed'), ' раз')}</b>",
        f"🎰 Просажено в казино: <b>{lost} Z</b> (отыграно {won} Z)",
        f"🥊 Заработано на «Бей Вовку»: <b>{await storage.stat_sum('vovka_won')} Z</b>",
        f"😡 Чаще всех получал по щам от Вовки: <b>{_top(await storage.stat_top('vovka_revenge'), ' раз')}</b>",
        f"🥛 Продано молока: <b>{await storage.stat_sum('sold_milk_can')}</b> шт",
        f"🐐 Раз подоили козу: <b>{await storage.stat_sum('goat_milked')}</b>",
        f"🎣 Больше всех наловил рыбы: <b>{_top(await storage.stat_top('fish_caught'), ' шт')}</b>",
        f"🍑 Чаще всех совал айфон куда не надо: <b>{_top(await storage.stat_top('iphone_butt'), ' раз')}</b>",
        f"📞 Больше всех наварил телефоном: <b>{_top(await storage.stat_top('scam_won'), ' Z')}</b>",
        f"🛵 Больше всех наездил курьером: <b>{_top(await storage.stat_top('courier_won'), ' Z')}</b>",
        f"🛒 Больше всего пикнул товаров: <b>{_top(await storage.stat_top('cashier_picks'), ' шт')}</b>",
        f"🤝 Сыграно ставок: <b>{bets_total}</b> "
        f"(больше всех выиграл: {_top(await storage.stat_top('bets_won'))})",
        f"🤲 Чаще всего брал в долг: <b>{_top(await storage.stat_top('borrowed'), ' раз')}</b>",
        f"🤡 Главный чепушила: <b>{_top(await storage.stat_top('defaulted'), ' раз')}</b>",
        f"🧾 Занесено Густаву Налоговику: <b>{await storage.stat_sum('gustav_paid')} Z</b> "
        f"(щедрее всех: {_top(await storage.stat_top('gustav_paid'), ' Z')})",
        f"🕵️ Чаще всех уходил от проверки Густава: "
        f"<b>{_top(await storage.stat_top('gustav_evaded'), ' раз')}</b>",
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

    b_won, b_lost = await st("bets_won"), await st("bets_lost")
    b_total = b_won + b_lost
    b_pct = round(b_won / b_total * 100) if b_total else 0

    lines = [
        f"📊 <b>Статистика — {nick}</b>",
        f"⭐ Уровень {level} ({rank(level)}) · 💰 {zbucks} Z",
        "",
        f"🦹 Удачных краж: <b>{thefts}</b> · обворовали тебя: <b>{await st('robbed')}</b>",
        f"📞 Наварил телефоном: <b>{await st('scam_won')} Z</b>",
        f"🛵 Курьером заработано: <b>{await st('courier_won')} Z</b>",
        f"🎰 Казино: проиграно <b>{await st('casino_lost')} Z</b>, в плюс <b>{await st('casino_won')} Z</b>",
        f"🤝 Ставки: <b>{b_won}</b> побед / <b>{b_lost}</b> поражений (<b>{b_pct}%</b> выигрыша)",
        f"🥊 «Бей Вовку»: заработано <b>{await st('vovka_won')} Z</b> · 😡 месть словил <b>{await st('vovka_revenge')}</b> раз",
        f"🛒 Кассир: смен <b>{await st('cashier_games')}</b>, пикнуто <b>{await st('cashier_picks')}</b> шт, "
        f"заработано <b>{await st('cashier_won')} Z</b>",
        f"🎣 Рыбы поймано: <b>{await st('fish_caught')}</b> · 🍑 айфон в жопу: <b>{await st('iphone_butt')}</b> раз",
        f"🥛 Продано молока: <b>{await st('sold_milk_can')}</b> шт",
        f"🐐 Доил козу: <b>{await st('goat_milked')}</b> раз",
        f"🤲 Брал в долг: <b>{await st('borrowed')}</b> раз",
        f"🤡 Был чепушилой: <b>{await st('defaulted')}</b> раз",
        f"🧾 Грязных денег сейчас: <b>{await storage.get_dirty(tg_id)} Z</b> · "
        f"занесено Густаву: <b>{await st('gustav_paid')} Z</b>",
    ]
    await msg.answer("\n".join(lines))
