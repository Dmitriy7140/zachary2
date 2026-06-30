"""Раздел «Работа»: Легальная (заглушка) и Нелегальная → Вор."""
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content import thief as txt
from db import storage
from game.debts import chepushila_days_left, is_chepushila
from game.thief import (MIN_TARGET_WEALTH, THEFT_THRESHOLDS, is_fail, roll_quality,
                        steal_amount, thief_level)
from utils.guards import ensure_owner, with_owner
from utils.notify import announce

router = Router()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back(owner: int, to: str):
    return _kb([[InlineKeyboardButton(text="⬅️ Назад", callback_data=with_owner(to, owner))]])


@router.callback_query(F.data.startswith("menu:work:"))
async def work_menu(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    owner = cb.from_user.id
    if not await storage.get_profile(owner):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    level = thief_level(await storage.get_thefts(owner))
    lines = [
        "💼 <b>Работа</b>",
        "",
        "<b>Текущие ранги:</b>",
        f"🦹 Вор — {txt.LEVEL_NAMES[level - 1]}",
    ]
    rows = [
        [InlineKeyboardButton(text="✅ Легальная", callback_data=with_owner("work:legal", owner))],
        [InlineKeyboardButton(text="🕶 Нелегальная", callback_data=with_owner("work:illegal", owner))],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", owner))],
    ]
    await cb.message.edit_text("\n".join(lines), reply_markup=_kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("work:legal:"))
async def work_legal(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    owner = cb.from_user.id
    if await is_chepushila(owner):
        days = await chepushila_days_left(owner)
        await cb.message.edit_text(
            f"🤡 Ты «Чепушила» — легальная работа закрыта ещё ~{days} дн.\nВозвращай долги вовремя!",
            reply_markup=_back(owner, "menu:work"),
        )
        return await cb.answer()
    await cb.message.edit_text(
        "✅ <b>Легальная работа</b>\nПока вакансий нет — скоро завезём 🛠",
        reply_markup=_back(owner, "menu:work"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("work:illegal:"))
async def work_illegal(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    owner = cb.from_user.id
    thefts = await storage.get_thefts(owner)
    level = thief_level(thefts)
    lines = [
        "🕶 <b>Нелегальная работа</b> · 🦹 Вор",
        f"Ранг: <b>{txt.LEVEL_NAMES[level - 1]}</b> · удачных краж: {thefts}",
        "",
        "<b>Прогрессия:</b>",
    ]
    for i, name in enumerate(txt.LEVEL_NAMES, start=1):
        need = THEFT_THRESHOLDS[i - 1]
        mark = "▶️" if i == level else "▪️"
        req = "" if need == 0 else f" — {need} краж"
        lines.append(f"{mark} {i}. {name}{req}")

    rows = [
        [InlineKeyboardButton(text="🦹 Залезть в карман", callback_data=with_owner("thief:steal", owner))],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=with_owner("menu:work", owner))],
    ]
    await cb.message.edit_text("\n".join(lines), reply_markup=_kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("thief:steal:"))
async def thief_steal(cb: CallbackQuery, bot: Bot):
    if not await ensure_owner(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    left = await storage.theft_cooldown_left(tg_id)
    if left > 0:
        return await cb.answer(f"⏳ Залечь на дно ещё {left // 3600}ч {(left % 3600) // 60}м",
                               show_alert=True)

    target = await storage.random_target(tg_id)
    if not target:
        return await cb.answer("Грабить некого — на районе пусто 🤷", show_alert=True)
    _, t_nick, t_wealth = target
    thief = hlink(cb.from_user.full_name, f"tg://user?id={tg_id}")
    back = _back(tg_id, "menu:work")

    # нищая цель — совесть взыграла
    if t_wealth <= MIN_TARGET_WEALTH:
        await storage.set_theft_cooldown(tg_id, 1)
        await cb.message.edit_text(txt.POOR.format(target=t_nick), reply_markup=back)
        await cb.answer()
        return await announce(bot, txt.poor_chat(thief, t_nick))

    level = thief_level(await storage.get_thefts(tg_id))

    # провал
    if is_fail(level):
        await storage.set_theft_cooldown(tg_id, 1)
        await cb.message.edit_text("🦹 " + txt.fail(t_nick), reply_markup=back)
        await cb.answer()
        return await announce(bot, txt.fail_chat(thief, t_nick))

    # успех
    quality = roll_quality(level)
    amount = steal_amount(quality, t_wealth)
    await storage.add_zbucks(tg_id, amount)
    await storage.add_theft(tg_id)
    await storage.set_theft_cooldown(tg_id, 12)
    await cb.message.edit_text(
        f"<b>{txt.QUALITY_NAMES[quality]}</b>\n\n{txt.success(quality, t_nick, amount)}",
        reply_markup=back,
    )
    await cb.answer()
    await announce(bot, txt.success_chat(quality, thief, t_nick))
