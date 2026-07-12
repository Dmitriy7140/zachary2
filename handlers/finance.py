"""Меню «Финансы»: Долг и Ставки под одной крышей (только в личке)."""
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db import storage
from utils.guards import ensure_private, with_owner
from utils.photo import show_text_menu

router = Router()


@router.callback_query(F.data == "menu:finance")
async def finance_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    owner = cb.from_user.id
    rows = [
        [InlineKeyboardButton(text="🕶 Махинации", callback_data="menu:shady")],
        [InlineKeyboardButton(text="🤲 Долг", callback_data="menu:loan")],
        [InlineKeyboardButton(text="🤝 Ставки", callback_data="menu:bets")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", owner))],
    ]
    await show_text_menu(
        cb.message,
        "💳 <b>Финансы</b>\nЗаймы, азарт и тёмные делишки — всё, что делает бедных беднее:",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()
