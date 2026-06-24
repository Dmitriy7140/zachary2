"""Магазин: покупка предметов за Zbucks."""
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db import storage
from game.items import ITEMS, shop_items

router = Router()


async def _render(message, tg_id: int) -> None:
    profile = await storage.get_profile(tg_id)
    rows = []
    for it in shop_items():
        owned = await storage.get_item_qty(tg_id, it.key)
        if owned >= it.max_qty:
            rows.append([InlineKeyboardButton(text=f"{it.emoji} {it.name} — куплено ✅",
                                              callback_data="noop")])
        else:
            rows.append([InlineKeyboardButton(text=f"{it.emoji} {it.name} — {it.price} Z",
                                              callback_data=f"shop:buy:{it.key}")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:main")])
    await message.edit_text(
        f"🛒 <b>Магазин</b>\nБаланс: <b>{profile[3]} Z</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "menu:shop")
async def shop_menu(cb: CallbackQuery):
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data.startswith("shop:buy:"))
async def shop_buy(cb: CallbackQuery):
    tg_id = cb.from_user.id
    key = cb.data.split(":")[2]
    item = ITEMS.get(key)
    if not item or item.price is None:
        return await cb.answer("Нет такого товара", show_alert=True)
    if await storage.get_item_qty(tg_id, key) >= item.max_qty:
        return await cb.answer("Уже куплено 😉", show_alert=True)
    if not await storage.spend_zbucks(tg_id, item.price):
        return await cb.answer("Не хватает Z 💸", show_alert=True)
    await storage.add_item(tg_id, key, 1, item.max_qty)
    await cb.answer(f"Куплено: {item.emoji} {item.name}!", show_alert=True)
    await _render(cb.message, tg_id)
