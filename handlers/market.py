"""Рынок: выставить товар на продажу. Цена ↑ → время продажи ↑."""
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from content.zhmyzhko import proletarian
from db import storage
from game.items import ITEMS, sellable_items
from game.taxman import grant
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
        # каждая штука — отдельная продажа; для витрины группируем по товару и цене
        groups: dict[tuple, list] = {}
        for item, price, sell_at, _qty in listings:
            groups.setdefault((item, price), []).append(sell_at)
        for (item, price), sell_ats in groups.items():
            it = ITEMS.get(item)
            label = f"{it.emoji} {it.name}" if it else item
            first = max(0, int((datetime.fromisoformat(sell_ats[0]) - datetime.now()).total_seconds()))
            if len(sell_ats) == 1:
                lines.append(f"• {label} — {price} Z "
                             f"(осталось {first // 3600}ч {first % 3600 // 60}м)")
            else:
                last = max(0, int((datetime.fromisoformat(sell_ats[-1]) - datetime.now()).total_seconds()))
                lines.append(f"• {label} ×{len(sell_ats)} — {price} Z/шт "
                             f"(ближайший через {first // 3600}ч {first % 3600 // 60}м, "
                             f"последний через {last // 3600}ч {last % 3600 // 60}м)")
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
    have = await storage.get_item_qty(cb.from_user.id, key)
    if have < 1:
        return await cb.answer("Нечего продавать", show_alert=True)

    if have == 1:
        return await _ask_price(cb, state, it, 1)

    # сколько штук в лот: один / половина / все (по одной цене за штуку)
    rows = [[InlineKeyboardButton(text="1️⃣ Один", callback_data=f"market:qty:{key}:1")]]
    half = have // 2
    if half > 1 and half != have:
        rows.append([InlineKeyboardButton(text=f"➗ Половину (×{half})",
                                          callback_data=f"market:qty:{key}:{half}")])
    rows.append([InlineKeyboardButton(text=f"💯 Все (×{have})",
                                      callback_data=f"market:qty:{key}:{have}")])
    rows.append([InlineKeyboardButton(text="⬅️ К рынку", callback_data="menu:market")])
    await cb.message.edit_text(
        f"{it.emoji} <b>{it.name}</b> (у тебя ×{have})\nСколько выставляем в лот?",
        reply_markup=_kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("market:qty:"))
async def market_qty(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    _, _, key, qty_raw = cb.data.split(":")
    qty = int(qty_raw)
    it = ITEMS.get(key)
    if not it or it.sell_minutes_per_z <= 0:
        return await cb.answer("Это не продаётся", show_alert=True)
    if qty < 1 or await storage.get_item_qty(cb.from_user.id, key) < qty:
        return await cb.answer("Столько уже нет", show_alert=True)
    await _ask_price(cb, state, it, qty)


async def _ask_price(cb: CallbackQuery, state: FSMContext, it, qty: int) -> None:
    await state.set_state(MarketStates.pricing)
    await state.update_data(item=it.key, qty=qty,
                            chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    max_min = (it.sell_max - it.sell_min) * it.sell_minutes_per_z
    cnt = f" ×{qty}" if qty > 1 else ""
    await cb.message.edit_text(
        f"{it.emoji} <b>{it.name}</b>{cnt}\n"
        f"Цена ЗА ШТУКУ {it.sell_min}–{it.sell_max} Z: {it.sell_min} = моментально, "
        f"каждый +1 Z = +{it.sell_minutes_per_z} мин (до ~{max_min // 60}ч при {it.sell_max} Z).\n"
        "Напиши цену за штуку:"
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
    qty = data.get("qty", 1)
    raw = (msg.text or "").strip()
    if not raw.isdigit():
        return await finish("❌ Это не число — отменено.")
    price = int(raw)
    if price < it.sell_min or price > it.sell_max:
        return await finish(f"❌ Цена должна быть {it.sell_min}–{it.sell_max} Z — отменено.")
    if not await storage.remove_item(tg_id, it.key, qty):
        return await finish("❌ Столько предметов уже нет — отменено.")

    cnt = f" ×{qty}" if qty > 1 else ""
    total = price * qty
    minutes = (price - it.sell_min) * it.sell_minutes_per_z
    if minutes <= 0:
        await grant(bot, tg_id, total)  # продажа на рынке — легальна
        await storage.bump(tg_id, f"sold_{it.key}", qty)
        nick = (await storage.get_profile(tg_id))[2]
        await announce(bot, f"🏪 {hlink(nick, f'tg://user?id={tg_id}')} продал {it.emoji} "
                            f"{it.name}{cnt} за {total} Z.\n{proletarian()}")
        return await finish(f"🏪 {it.emoji} {it.name}{cnt} продан моментально за <b>{total} Z</b>!")

    # рынок переваривает по одной штуке: таймеры складываются (1×M, 2×M, ... N×M).
    # Большая партия по дорогой цене — надолго; дёшево — быстрый оборот.
    now = datetime.now()
    for i in range(qty):
        sell_at = (now + timedelta(minutes=minutes * (i + 1))).isoformat()
        await storage.add_listing(tg_id, it.key, price, sell_at)
    last_min = minutes * qty
    tail = (f"Первый уйдёт через ~{minutes // 60}ч {minutes % 60}м, "
            f"последний — через ~{last_min // 60}ч {last_min % 60}м."
            if qty > 1 else
            f"Продастся через ~{minutes // 60}ч {minutes % 60}м.")
    await finish(
        f"🏪 {it.emoji} {it.name}{cnt} выставлен по <b>{price} Z/шт</b> (итого {total} Z).\n"
        f"Продаются по очереди: {tail} Товар убран из инвентаря."
    )
