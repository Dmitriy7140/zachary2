"""Меню «Махинации»: спрятать грязные деньги от Густава.

Пока бизнесов нет, прятка — единственный способ уберечь нелегал от рейда.
Деньги не списываются и не возвращаются — они просто невидимы для Густава
на HIDE_MINUTES минут. Прячется сразу максимум: min(грязные, лимит).
Лимит 5000 Z; владельцам айфона — 4000 (пятая тысяча прячется в жопу,
а очко растянуто айфоном).
"""
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content.shady import hide_message
from db import storage
from game.taxman import (HIDE_CAP, HIDE_CAP_IPHONE, HIDE_CD_KEY, HIDE_COOLDOWN_MIN, HIDE_KEY,
                         HIDE_MINUTES, active_hidden)
from utils.guards import ensure_private, with_owner
from utils.notify import announce

router = Router()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render(message, tg_id: int) -> None:
    dirty = await storage.get_dirty(tg_id)
    lines = [
        "🕶 <b>Махинации</b>",
        "Пока у тебя нет бизнеса, единственный способ уберечь нелегал от "
        "холщового еблета — спрятать его на себе.",
        "",
        f"🧾 Грязных денег: <b>{dirty} Z</b>",
        f"Лимит прятки: {HIDE_CAP} Z. Владельцам айфона — {HIDE_CAP_IPHONE}: "
        "пятая тысяча прячется в жопу, а очко растянуто айфоном.",
        f"Прятка держится {HIDE_MINUTES} минуты — вся соль в том, чтобы "
        f"подгадать момент. Кд между прятками — {HIDE_COOLDOWN_MIN} минут.",
    ]
    hidden = await active_hidden(tg_id)
    if hidden > 0:
        left = await storage.cooldown_left_secs(tg_id, HIDE_KEY)
        lines.append(f"\n🧦 Сейчас спрятано: <b>{hidden} Z</b> (ещё {left // 60}м {left % 60}с)")
    else:
        cd = await storage.cooldown_left_secs(tg_id, HIDE_CD_KEY)
        if cd > 0:
            lines.append(f"\n🕐 Снова прятать можно через {cd // 60}м {cd % 60}с")
    rows = [
        [InlineKeyboardButton(text="🧦 Спрятать бабки", callback_data="shady:hide")],
        [InlineKeyboardButton(text="⬅️ К финансам", callback_data="menu:finance"),
         InlineKeyboardButton(text="🏠 В меню", callback_data=with_owner("menu:main", tg_id))],
    ]
    await message.edit_text("\n".join(lines), reply_markup=_kb(rows))


@router.callback_query(F.data == "menu:shady")
async def shady_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "shady:hide")
async def shady_hide(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    if await active_hidden(tg_id) > 0:
        left = await storage.cooldown_left_secs(tg_id, HIDE_KEY)
        return await cb.answer(f"Уже всё спрятано! Держится ещё {left // 60}м {left % 60}с",
                               show_alert=True)

    cd = await storage.cooldown_left_secs(tg_id, HIDE_CD_KEY)
    if cd > 0:
        return await cb.answer(
            f"⏳ Организм ещё не отошёл от прошлой прятки. Жди {cd // 60}м {cd % 60}с",
            show_alert=True)

    dirty = await storage.get_dirty(tg_id)
    if dirty <= 0:
        return await cb.answer("Прятать нечего — грязных денег нет 🤷", show_alert=True)

    has_iphone = await storage.get_item_qty(tg_id, "iphone") > 0
    cap = HIDE_CAP_IPHONE if has_iphone else HIDE_CAP
    now = datetime.now()
    amount = await storage.activate_hidden_money(
        tg_id,
        cap,
        (now + timedelta(minutes=HIDE_MINUTES)).isoformat(),
        (now + timedelta(minutes=HIDE_COOLDOWN_MIN)).isoformat(),
        now.isoformat(),
    )
    if amount <= 0:
        await cb.answer("Состояние уже изменилось — проверь экран ещё раз", show_alert=True)
        await _render(cb.message, tg_id)
        return

    # хотел спрятать пятую тысячу, но очко растянуто айфоном
    iphone_blocked = (
        has_iphone and dirty > HIDE_CAP_IPHONE and amount == HIDE_CAP_IPHONE
    )

    who = hlink(cb.from_user.full_name, f"tg://user?id={tg_id}")
    await announce(bot, hide_message(who, amount, iphone_blocked))
    await cb.answer(f"🧦 Спрятано {amount} Z на {HIDE_MINUTES} мин. Тик-так.", show_alert=True)
    await _render(cb.message, tg_id)
