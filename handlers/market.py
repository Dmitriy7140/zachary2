"""Рынок: выставить товар на продажу. Цена ↑ → время продажи ↑."""
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from db import storage
from game.items import ITEMS, sellable_items
from utils.guards import ensure_private, with_owner
from utils.notify import announce

router = Router()


class MarketStates(StatesGroup):
    pricing = State()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back(owner: int):
    return _kb([[
        InlineKeyboardButton(text="⬅️ К рынку", callback_data="menu:market"),
        InlineKeyboardButton(text="🏠 В меню", callback_data=with_owner("menu:main", owner)),
    ]])


async def _render(message, tg_id: int) -> None:
    lines = ["🏪 <b>Рынок</b>", ""]
    listings = await storage.get_listings(tg_id)
    if listings:
        lines.append("<b>Твои продажи:</b>")
        for item, price, sell_at in listings:
            it = ITEMS.get(item)
            label = f"{it.emoji} {it.name}" if it else item
            secs = max(0, int((datetime.fromisoformat(sell_at) - datetime.now()).total_seconds()))
            lines.append(f"• {label} — {price} Z (осталось {secs // 3600}ч {secs % 3600 // 60}м)")
        lines.append("")

    rows = []
    inv = await storage.get_inventory(tg_id)
    sellable = [it for it in sellable_items() if inv.get(it.key, 0) > 0]
    if sellable:
        lines.append("<b>Выставить на продажу:</b>")
        for it in sellable:
            rows.append([InlineKeyboardButton(
                text=f"{it.emoji} {it.name} (×{inv[it.key]})",
                callback_data=f"market:sell:{it.key}")])
    else:
        lines.append("Продавать пока нечего — сходи на дойку 🐐")

    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", tg_id))])
    await message.edit_text("\n".join(lines), reply_markup=_kb(rows))


@router.callback_query(F.data == "menu:market")
async def market_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data.startswith("market:sell:"))
async def market_sell(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    key = cb.data.split(":")[2]
    it = ITEMS.get(key)
    if not it or it.sell_minutes_per_z <= 0:
        return await cb.answer("Это не продаётся", show_alert=True)
    if await storage.get_item_qty(cb.from_user.id, key) < 1:
        return await cb.answer("Нечего продавать", show_alert=True)

    await state.set_state(MarketStates.pricing)
    await state.update_data(item=key, chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    max_min = (it.sell_max - it.sell_min) * it.sell_minutes_per_z
    await cb.message.edit_text(
        f"{it.emoji} <b>{it.name}</b>\n"
        f"Цена {it.sell_min}–{it.sell_max} Z: {it.sell_min} = моментально, "
        f"каждый +1 Z = +{it.sell_minutes_per_z} мин (до ~{max_min // 60}ч при {it.sell_max} Z).\n"
        "Напиши цену:"
    )
    await cb.answer()


@router.message(MarketStates.pricing)
async def market_price(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    tg_id = msg.from_user.id
    it = ITEMS.get(data["item"])

    async def finish(text: str):
        try:
            await bot.edit_message_text(text, chat_id=data["chat_id"], message_id=data["msg_id"],
                                        reply_markup=_back(tg_id))
        except Exception:
            await msg.answer(text, reply_markup=_back(tg_id))

    if it is None:
        return await finish("❌ Ошибка товара — отменено.")
    raw = (msg.text or "").strip()
    if not raw.isdigit():
        return await finish("❌ Это не число — отменено.")
    price = int(raw)
    if price < it.sell_min or price > it.sell_max:
        return await finish(f"❌ Цена должна быть {it.sell_min}–{it.sell_max} Z — отменено.")
    if not await storage.remove_item(tg_id, it.key, 1):
        return await finish("❌ Предмета уже нет — отменено.")

    minutes = (price - it.sell_min) * it.sell_minutes_per_z
    if minutes <= 0:
        await storage.add_zbucks(tg_id, price)
        nick = (await storage.get_profile(tg_id))[2]
        await announce(bot, f"🏪 {hlink(nick, f'tg://user?id={tg_id}')} продал {it.emoji} {it.name} за {price} Z.")
        return await finish(f"🏪 {it.emoji} {it.name} продан моментально за <b>{price} Z</b>!")

    sell_at = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    await storage.add_listing(tg_id, it.key, price, sell_at)
    await finish(
        f"🏪 {it.emoji} {it.name} выставлен за <b>{price} Z</b>.\n"
        f"Продастся через ~{minutes // 60}ч {minutes % 60}м. Предмет убран из инвентаря."
    )
