"""Магазин: покупка предметов за Zbucks."""
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content.chef import znak_ominous
from content.zhmyzhko import proletarian
from db import storage
from game.fishing import BAIT_TIER, fishing_level
from game.items import ITEMS, shop_items
from utils.guards import ensure_owner, with_owner
from utils.notify import announce

router = Router()


async def _bait_locked(tg_id: int, key: str) -> int:
    """Если приманка не по уровню — вернуть нужный уровень, иначе 0."""
    tier = BAIT_TIER.get(key)
    if not tier:
        return 0
    lvl = fishing_level(await storage.player_stat(tg_id, "fish_caught"))
    return tier if lvl < tier else 0


async def _render(message, owner: int) -> None:
    profile = await storage.get_profile(owner)
    rows = []
    for it in shop_items():
        owned = await storage.get_item_qty(owner, it.key)
        need = await _bait_locked(owner, it.key)
        if need:
            rows.append([InlineKeyboardButton(text=f"🔒 {it.name} — нужен ур. рыбалки {need}",
                                              callback_data="noop")])
        elif owned >= it.max_qty:
            rows.append([InlineKeyboardButton(text=f"{it.emoji} {it.name} — куплено ✅",
                                              callback_data="noop")])
        else:
            rows.append([InlineKeyboardButton(text=f"{it.emoji} {it.name} — {it.price} Z",
                                              callback_data=with_owner(f"shop:buy:{it.key}", owner))])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", owner))])
    await message.edit_text(
        f"🛒 <b>Магазин</b>\nБаланс: <b>{profile[3]} Z</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("menu:shop:"))
async def shop_menu(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data.startswith("shop:buy:"))
async def shop_buy(cb: CallbackQuery, bot):
    if not await ensure_owner(cb):
        return
    tg_id = cb.from_user.id
    key = cb.data.split(":")[2]
    item = ITEMS.get(key)
    if not item or item.price is None:
        return await cb.answer("Нет такого товара", show_alert=True)
    need = await _bait_locked(tg_id, key)
    if need:
        return await cb.answer(f"🔒 Нужен уровень рыбалки {need} — сначала налови рыбы", show_alert=True)
    if await storage.get_item_qty(tg_id, key) >= item.max_qty:
        return await cb.answer("Уже куплено 😉", show_alert=True)
    if not await storage.spend_zbucks(tg_id, item.price):
        return await cb.answer("Не хватает Z 💸", show_alert=True)
    await storage.add_item(tg_id, key, 1, item.max_qty)
    await cb.answer(f"Куплено: {item.emoji} {item.name}!", show_alert=True)
    buyer = hlink(cb.from_user.full_name, f"tg://user?id={tg_id}")
    if key == "znak":
        # покупка Ъ — событие зловещее, Жмыжко тут не к месту
        await announce(bot, znak_ominous(buyer))
    else:
        await announce(bot, f"🛒 {buyer} купил {item.emoji} {item.name} за {item.price} Z.\n{proletarian()}")
    await _render(cb.message, tg_id)
