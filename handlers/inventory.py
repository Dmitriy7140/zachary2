"""Инвентарь игрока."""
from aiogram import F, Router
from aiogram.types import CallbackQuery

from db import storage
from game.items import ITEMS
from keyboards import back_menu

router = Router()


@router.callback_query(F.data == "menu:inventory")
async def inventory(cb: CallbackQuery):
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    items = await storage.get_inventory(cb.from_user.id)
    lines = []
    for key, qty in items.items():
        it = ITEMS.get(key)
        if not it or qty <= 0:
            continue
        if it.max_qty > 1:
            lines.append(f"{it.emoji} {it.name} ×{qty}")
        else:
            lines.append(f"{it.emoji} {it.name}")

    body = "\n".join(lines) if lines else "пусто 🕸"
    await cb.message.edit_text(f"🎒 <b>Инвентарь</b>\n\n{body}", reply_markup=back_menu())
    await cb.answer()
