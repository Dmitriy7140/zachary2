"""Магазин: покупка предметов за Zbucks."""
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content.chef import znak_ominous
from content.shop import shop_vibe
from content.zhmyzhko import proletarian
from db import storage
from game.fishing import BAIT_TIER, fishing_level
from game.items import (INVENTORY_CATEGORIES, INVENTORY_CATEGORY_LABELS, ITEM_CATEGORY, ITEMS,
                        categorized_items, shop_items)
from keyboards import alternating_button_rows
from utils.guards import ensure_owner, with_owner
from utils.notify import announce
from utils.photo import show_photo_menu

router = Router()

SHOP_PHOTO = "static/shop_record_stall.png"
SHOP_PHOTO_META = "shop_record_stall_photo_id"


async def _bait_locked(tg_id: int, key: str) -> int:
    """Если приманка не по уровню — вернуть нужный уровень, иначе 0."""
    tier = BAIT_TIER.get(key)
    if not tier:
        return 0
    lvl = fishing_level(await storage.player_stat(tg_id, "fish_caught"))
    return tier if lvl < tier else 0


async def _render_categories(message, owner: int) -> None:
    profile = await storage.get_profile(owner)
    categories = categorized_items(shop_items())
    buttons = [
        InlineKeyboardButton(
            text=label,
            callback_data=with_owner(f"shop:category:{category}", owner),
        )
        for category, label in INVENTORY_CATEGORIES
        if categories[category]
    ]
    rows = alternating_button_rows(buttons)
    rows.append([InlineKeyboardButton(
        text="🎟 Лотерейные билеты",
        callback_data=with_owner("lot:view", owner),
    )])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", owner))])
    await show_photo_menu(
        message,
        SHOP_PHOTO,
        SHOP_PHOTO_META,
        (f"🛒 <b>Магазин</b>\nБаланс: <b>{profile[3]} Z</b>\n\n"
         f"<i>{shop_vibe()}</i>\n\nВыбери категорию:"),
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _render_category(message, owner: int, category: str) -> None:
    profile = await storage.get_profile(owner)
    buttons = []
    for it in categorized_items(shop_items())[category]:
        owned = await storage.get_item_qty(owner, it.key)
        need = await _bait_locked(owner, it.key)
        if need:
            buttons.append(InlineKeyboardButton(
                text=f"🔒 {it.name} — нужен ур. рыбалки {need}", callback_data="noop",
            ))
        elif owned >= it.max_qty:
            buttons.append(InlineKeyboardButton(
                text=f"{it.emoji} {it.name} — куплено ✅", callback_data="noop",
            ))
        else:
            buttons.append(InlineKeyboardButton(
                text=f"{it.emoji} {it.name} — {it.price} Z",
                callback_data=with_owner(f"shop:buy:{it.key}", owner),
            ))
    rows = alternating_button_rows(buttons)
    rows.append([InlineKeyboardButton(
        text="⬅️ К категориям",
        callback_data=with_owner("menu:shop", owner),
    )])
    await show_photo_menu(
        message,
        SHOP_PHOTO,
        SHOP_PHOTO_META,
        f"🛒 <b>{INVENTORY_CATEGORY_LABELS[category]}</b>\nБаланс: <b>{profile[3]} Z</b>",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("menu:shop:"))
async def shop_menu(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render_categories(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data.startswith("shop:category:"))
async def shop_category(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    parts = (cb.data or "").split(":")
    category = parts[2] if len(parts) >= 4 else ""
    categories = categorized_items(shop_items())
    if category not in INVENTORY_CATEGORY_LABELS or not categories[category]:
        return await cb.answer("В этом разделе пока ничего не продаётся", show_alert=True)
    await _render_category(cb.message, tg_id, category)
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
    await _render_category(cb.message, tg_id, ITEM_CATEGORY[key])
