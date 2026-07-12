"""Фарцовщик: чёрный рынок запрещённых товаров для нелегального заработка."""
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content.zhmyzhko import proletarian
from db import storage
from game.items import ITEMS, blackmarket_items
from utils.guards import ensure_owner, with_owner
from utils.notify import announce
from utils.photo import show_text_menu

router = Router()

DESCR = {
    "lockpicks": "🗝 <b>Отмычки</b> — навсегда −5% к шансу провала кражи",
    "cross": "✝️ <b>Православный крест</b> — навсегда +2 к погрешности в телефонном мошеннике "
             "(слова 4 и 5 засчитываются как 3-е)",
}


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render(message, owner: int) -> None:
    profile = await storage.get_profile(owner)
    lines = ["🃏 <b>Фарцовщик</b>", "Запрещёнка для тех, кто в теме 🤫",
             f"Баланс: <b>{profile[3]} Z</b>", ""]
    rows = []
    for it in blackmarket_items():
        lines.append(DESCR.get(it.key, f"{it.emoji} {it.name}"))
        if await storage.get_item_qty(owner, it.key) >= it.max_qty:
            rows.append([InlineKeyboardButton(text=f"{it.emoji} {it.name} — уже есть ✅",
                                              callback_data="noop")])
        else:
            rows.append([InlineKeyboardButton(text=f"{it.emoji} {it.name} — {it.price} Z",
                                              callback_data=with_owner(f"farca:buy:{it.key}", owner))])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", owner))])
    await show_text_menu(message, "\n".join(lines), _kb(rows))


@router.callback_query(F.data.startswith("menu:farca:"))
async def farca_menu(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data.startswith("farca:buy:"))
async def farca_buy(cb: CallbackQuery, bot: Bot):
    if not await ensure_owner(cb):
        return
    tg_id = cb.from_user.id
    key = cb.data.split(":")[2]
    item = ITEMS.get(key)
    if not item or not item.blackmarket:
        return await cb.answer("Нет такого товара", show_alert=True)
    if await storage.get_item_qty(tg_id, key) >= item.max_qty:
        return await cb.answer("Уже куплено 😉", show_alert=True)
    if not await storage.spend_zbucks(tg_id, item.price):
        return await cb.answer("Не хватает Z 💸", show_alert=True)
    await storage.add_item(tg_id, key, 1, item.max_qty)
    await cb.answer(f"Куплено: {item.emoji} {item.name}!", show_alert=True)
    buyer = hlink(cb.from_user.full_name, f"tg://user?id={tg_id}")
    await announce(bot, f"🃏 {buyer} прикупил у фарцовщика {item.emoji} {item.name} за {item.price} Z.\n{proletarian()}")
    await _render(cb.message, tg_id)
