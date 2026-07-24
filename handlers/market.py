"""Рынок: «Продажа» — поставка товаров в общий сток, «Покупка» — стакан.

Продажа: лот продаётся ВЕСЬ разом через (цена − минимум) × 10 минут
(по минималке — мгновенно). Суммарно в активных лотах не больше вместимости
палеты игрока. Проданное попадает в market_stock с наценкой 10% и доступно другим
игрокам в «Покупке» — игроки сами привозят товары на рынок.
"""
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from content.market import market_vibe
from content.zhmyzhko import proletarian
from db import storage
from game.items import ITEMS, sellable_items
from game.market import (MARKET_PALLET_BASE_LIMIT, MARKET_PALLET_UPGRADE_PRICE,
                         MARKET_PALLET_UPGRADED_LIMIT, buy_price)
from game.taxman import grant
from utils.cleanup import delete_later
from utils.guards import ensure_private, with_owner
from utils.notify import announce
from utils.pagination import nav_row, page_slice
from utils.photo import show_photo_menu

router = Router()

BUY_PAGE_SIZE = 8

# атмосфера базара: все экраны рынка — фото с подписью
MARKET_PHOTO = "static/market.png"
MARKET_PHOTO_META = "market_photo_id"


async def _show(message: Message, text: str, rows=None) -> None:
    await show_photo_menu(message, MARKET_PHOTO, MARKET_PHOTO_META, text,
                          _kb(rows) if rows else None)


class MarketStates(StatesGroup):
    pricing = State()
    buying = State()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back(owner: int):
    return _kb([[
        InlineKeyboardButton(text="⬅️ К рынку", callback_data="menu:market"),
        InlineKeyboardButton(text="🏠 В меню", callback_data=with_owner("menu:main", owner)),
    ]])


# ---------- корневое меню ----------

@router.callback_query(F.data == "menu:market")
async def market_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    rows = [
        [InlineKeyboardButton(text="🛒 Покупка", callback_data="market:buymenu")],
        [InlineKeyboardButton(text="💰 Продажа", callback_data="market:sellmenu")],
        [InlineKeyboardButton(text="⬅️ В меню",
                              callback_data=with_owner("menu:main", cb.from_user.id))],
    ]
    await _show(
        cb.message,
        "🏪 <b>Рынок</b>\n"
        "Игроки сами привозят товары: продал — уехало на прилавок, "
        "покупаешь — из привезённого другими (наценка рынка 10%).",
        rows)
    await cb.answer()


# ---------- ПРОДАЖА ----------

async def _render_sell(message, tg_id: int) -> None:
    in_sale = await storage.active_listing_qty(tg_id)
    sell_limit = await storage.market_sell_limit(tg_id)
    lines = [
        "💰 <b>Продажа</b>",
        f"В продаже: {in_sale}/{sell_limit} шт",
        f"Палета вмещает до {sell_limit} товаров за раз.",
        "",
    ]

    listings = await storage.get_listings(tg_id)
    if listings:
        lines.append("<b>Твои лоты:</b>")
        # Палета может вместить 40 единиц; не превращаем caption Telegram в
        # простыню, если игрок выставил много отдельных лотов.
        for item, price, sell_at, qty in listings[:8]:
            it = ITEMS.get(item)
            label = f"{it.emoji} {it.name}" if it else item
            cnt = f" ×{qty}" if (qty or 1) > 1 else ""
            secs = max(0, int((datetime.fromisoformat(sell_at) - datetime.now()).total_seconds()))
            lines.append(f"• {label}{cnt} — {price} Z/шт "
                         f"(продадутся через {secs // 3600}ч {secs % 3600 // 60}м)")
        if len(listings) > 8:
            lines.append(f"• … и ещё {len(listings) - 8} лотов")
        lines.append("")

    inv = await storage.get_inventory(tg_id)
    sellable = [it for it in sellable_items() if inv.get(it.key, 0) > 0]
    buttons = []
    if sellable:
        lines.append("<b>Выставить на продажу:</b>")
        # на рынке — только эмодзи, в два столбца
        for it in sellable:
            buttons.append(InlineKeyboardButton(text=f"{it.emoji} ×{inv[it.key]}",
                                                callback_data=f"market:sell:{it.key}"))
    else:
        lines.append("Продавать пока нечего — сходи на дойку 🐐")

    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    if sell_limit == MARKET_PALLET_BASE_LIMIT:
        rows.append([
            InlineKeyboardButton(
                text=("📦 Улучшить палету до "
                      f"{MARKET_PALLET_UPGRADED_LIMIT} товаров — "
                      f"{MARKET_PALLET_UPGRADE_PRICE} Z"),
                callback_data="market:pallet:upgrade",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ К рынку", callback_data="menu:market")])
    await _show(message, "\n".join(lines), rows)


@router.callback_query(F.data == "market:sellmenu")
async def market_sellmenu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render_sell(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "market:pallet:upgrade")
async def market_pallet_upgrade(cb: CallbackQuery):
    """Показать подтверждение одноразового расширения палеты."""
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    sell_limit = await storage.market_sell_limit(tg_id)
    if sell_limit >= MARKET_PALLET_UPGRADED_LIMIT:
        return await cb.answer("Палета уже вмещает 40 товаров", show_alert=True)

    rows = [
        [InlineKeyboardButton(
            text=f"💰 Улучшить за {MARKET_PALLET_UPGRADE_PRICE} Z",
            callback_data="market:pallet:confirm",
        )],
        [InlineKeyboardButton(text="⬅️ К продаже", callback_data="market:sellmenu")],
    ]
    await _show(
        cb.message,
        "📦 <b>Улучшение палеты</b>\n\n"
        f"Сейчас она вмещает {sell_limit} товаров в продаже одновременно.\n"
        f"За <b>{MARKET_PALLET_UPGRADE_PRICE} Z</b> грузчики приколотят ещё досок — "
        f"вместимость вырастет до <b>{MARKET_PALLET_UPGRADED_LIMIT} товаров</b>.\n\n"
        "Улучшение одноразовое. Берём?",
        rows,
    )
    await cb.answer()


@router.callback_query(F.data == "market:pallet:confirm")
async def market_pallet_confirm(cb: CallbackQuery):
    """Атомарно купить палету и перерисовать актуальный экран продажи."""
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    status = await storage.upgrade_market_pallet(
        tg_id, price=MARKET_PALLET_UPGRADE_PRICE,
    )
    if status == "upgraded":
        await _render_sell(cb.message, tg_id)
        return await cb.answer("Палета расширена: теперь в продаже до 40 товаров!")
    if status == "already_upgraded":
        await _render_sell(cb.message, tg_id)
        return await cb.answer("Палета уже улучшена", show_alert=True)
    if status == "insufficient_funds":
        return await cb.answer(
            f"Не хватает Z (нужно {MARKET_PALLET_UPGRADE_PRICE})", show_alert=True,
        )
    return await cb.answer("Не удалось улучшить палету — попробуй ещё раз", show_alert=True)


@router.callback_query(F.data.startswith("market:sell:"))
async def market_sell(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    key = cb.data.split(":")[2]
    it = ITEMS.get(key)
    if not it or it.sell_minutes_per_z <= 0:
        return await cb.answer("Это не продаётся", show_alert=True)
    have = await storage.get_item_qty(tg_id, key)
    if have < 1:
        return await cb.answer("Нечего продавать", show_alert=True)

    sell_limit = await storage.market_sell_limit(tg_id)
    free = max(0, sell_limit - await storage.active_listing_qty(tg_id))
    # Продажа по минимальной цене мгновенна и не занимает палету. Поэтому
    # даже с заполненной палетой даём дойти до выбора цены; delayed-лот
    # перепроверяется уже после ввода цены.
    max_sell = min(have, free) if free > 0 else have
    if max_sell == 1:
        return await _ask_price(cb, state, it, 1)

    # сколько штук в лот: один / половина / максимум (по одной цене за штуку)
    rows = [[InlineKeyboardButton(text="1️⃣ Один", callback_data=f"market:qty:{key}:1")]]
    half = max_sell // 2
    if half > 1 and half != max_sell:
        rows.append([InlineKeyboardButton(text=f"➗ Половину (×{half})",
                                          callback_data=f"market:qty:{key}:{half}")])
    all_label = f"💯 Все (×{max_sell})" if max_sell == have else f"💯 Максимум (×{max_sell})"
    rows.append([InlineKeyboardButton(text=all_label,
                                      callback_data=f"market:qty:{key}:{max_sell}")])
    rows.append([InlineKeyboardButton(text="⬅️ К продаже", callback_data="market:sellmenu")])
    pallet_note = (
        "Палета заполнена: доступна только мгновенная продажа по минимальной цене.\n"
        if free <= 0 else ""
    )
    await _show(
        cb.message,
        f"{it.emoji} <b>{it.name}</b> (у тебя ×{have}, свободно в продаже {free})\n"
        f"{pallet_note}Сколько выставляем в лот?",
        rows)
    await cb.answer()


@router.callback_query(F.data.startswith("market:qty:"))
async def market_qty(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    _, _, key, qty_raw = cb.data.split(":")
    qty = int(qty_raw)
    it = ITEMS.get(key)
    if not it or it.sell_minutes_per_z <= 0:
        return await cb.answer("Это не продаётся", show_alert=True)
    if qty < 1 or await storage.get_item_qty(tg_id, key) < qty:
        return await cb.answer("Столько уже нет", show_alert=True)
    await _ask_price(cb, state, it, qty)


async def _ask_price(cb: CallbackQuery, state: FSMContext, it, qty: int) -> None:
    await state.set_state(MarketStates.pricing)
    await state.update_data(item=it.key, qty=qty,
                            chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    max_min = (it.sell_max - it.sell_min) * it.sell_minutes_per_z
    cnt = f" ×{qty}" if qty > 1 else ""
    await _show(
        cb.message,
        f"{it.emoji} <b>{it.name}</b>{cnt}\n"
        f"Цена ЗА ШТУКУ {it.sell_min}–{it.sell_max} Z: {it.sell_min} = моментально, "
        f"каждый +1 Z = +{it.sell_minutes_per_z} мин ожидания "
        f"(до ~{max_min // 60}ч при {it.sell_max} Z). Лот продаётся весь разом.\n"
        "Напиши цену за штуку:")
    await cb.answer()


@router.message(MarketStates.pricing)
async def market_price(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    tg_id = msg.from_user.id
    it = ITEMS.get(data["item"])
    delete_later(bot, msg.chat.id, msg.message_id)

    async def finish(text: str):
        try:
            await bot.edit_message_caption(chat_id=data["chat_id"], message_id=data["msg_id"],
                                           caption=text, reply_markup=_back(tg_id))
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
    cnt = f" ×{qty}" if qty > 1 else ""
    total = price * qty
    minutes = (price - it.sell_min) * it.sell_minutes_per_z
    if minutes <= 0:
        # Мгновенная продажа не занимает палету: предмет сразу уезжает в стакан.
        if not await storage.remove_item(tg_id, it.key, qty):
            return await finish("❌ Столько предметов уже нет — отменено.")
        await grant(bot, tg_id, total)  # продажа на рынке — легальна
        await storage.bump(tg_id, f"sold_{it.key}", qty)
        await storage.add_stock(it.key, buy_price(price), qty)  # уехало на прилавок
        nick = (await storage.get_profile(tg_id))[2]
        await announce(bot, f"🏪 {hlink(nick, f'tg://user?id={tg_id}')} продал {it.emoji} "
                            f"{it.name}{cnt} за {total} Z.\n{proletarian()}")
        return await finish(f"🏪 {it.emoji} {it.name}{cnt} продан моментально за <b>{total} Z</b>!")

    # Весь лот продаётся одновременно — один таймер на всех. Снятие предмета
    # и проверка свободного места палеты происходят в одной economy-транзакции.
    sell_at = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    status = await storage.create_market_listing(tg_id, it.key, price, sell_at, qty)
    if status == "no_item":
        return await finish("❌ Столько предметов уже нет — отменено.")
    if status == "limit":
        return await finish(f"❌ Лимит {await storage.market_sell_limit(tg_id)} шт в продаже разом — отменено.")
    if status != "ok":
        return await finish("❌ Не удалось выставить лот — отменено.")
    await finish(
        f"🏪 {it.emoji} {it.name}{cnt} выставлен по <b>{price} Z/шт</b> (итого {total} Z).\n"
        f"Продадутся все разом через ~{minutes // 60}ч {minutes % 60}м. "
        f"Товар убран из инвентаря."
    )


# ---------- ПОКУПКА: ревью рынка → прилавки → стакан ----------

async def _render_buy(message, tg_id: int) -> None:
    """Общее ревью рынка + кнопки-прилавки по всем продаваемым товарам."""
    stock = await storage.get_stock()
    totals: dict[str, int] = {}
    for item, _price, qty in stock:
        totals[item] = totals.get(item, 0) + qty

    # прилавки — только эмодзи, в два столбца
    buttons = []
    for it in sellable_items():
        have = totals.get(it.key, 0)
        tail = f" ×{have}" if have else " —"
        buttons.append(InlineKeyboardButton(text=f"{it.emoji}{tail}",
                                            callback_data=f"market:stall:{it.key}"))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="⬅️ К рынку", callback_data="menu:market")])
    await _show(message,
                f"🛒 <b>Покупка</b>\n{market_vibe()}\n\nВыбери, к какому прилавку подойти:",
                rows)


@router.callback_query(F.data == "market:buymenu")
async def market_buymenu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render_buy(cb.message, cb.from_user.id)
    await cb.answer()


async def _render_stall(message, item: str, page: int = 0) -> None:
    """Стакан конкретного товара: цены и количество."""
    it = ITEMS[item]
    offers = [(i, p, q) for i, p, q in await storage.get_stock() if i == item]
    lines = [f"{it.emoji} <b>Прилавок: {it.name}</b>", ""]
    rows = []
    if not offers:
        lines.append("Прилавок пуст — никто не привёз 🕸")
    else:
        chunk, page, pages = page_slice(offers, page, BUY_PAGE_SIZE)
        for _item, price, qty in chunk:
            lines.append(f"• за {price} Z — {qty} шт")
            rows.append([InlineKeyboardButton(text=f"Взять по {price} Z (×{qty})",
                                              callback_data=f"market:buy:{item}:{price}")])
        if pages > 1:
            rows.append(nav_row(page, pages, f"marketbpg:{item}:"))
    rows.append([InlineKeyboardButton(text="⬅️ К прилавкам", callback_data="market:buymenu")])
    await _show(message, "\n".join(lines), rows)


@router.callback_query(F.data.startswith("market:stall:"))
async def market_stall(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    item = cb.data.split(":")[2]
    if item not in ITEMS:
        return await cb.answer("Нет такого прилавка", show_alert=True)
    await _render_stall(cb.message, item)
    await cb.answer()


@router.callback_query(F.data.startswith("marketbpg:"))
async def market_buy_page(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    _, item, page = cb.data.split(":")
    if item not in ITEMS:
        return await cb.answer("Нет такого прилавка", show_alert=True)
    await _render_stall(cb.message, item, int(page))
    await cb.answer()


@router.callback_query(F.data.startswith("market:buy:"))
async def market_buy(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    _, _, item, price_raw = cb.data.split(":")
    price = int(price_raw)
    it = ITEMS.get(item)
    if not it:
        return await cb.answer("Нет такого товара", show_alert=True)

    in_stock = {(i, p): q for i, p, q in await storage.get_stock()}.get((item, price), 0)
    if in_stock <= 0:
        await cb.answer("Уже разобрали 🤷", show_alert=True)
        return await _render_buy(cb.message, tg_id)

    profile = await storage.get_profile(tg_id)
    available = (profile[3] if profile else 0) - await storage.hidden_now(tg_id)
    space = it.max_qty - await storage.get_item_qty(tg_id, item)  # склад — 99
    if space <= 0:
        return await cb.answer(f"Склад забит ({it.max_qty} шт) — сначала продай или потрать",
                               show_alert=True)
    if available < price:
        return await cb.answer(f"Не хватает даже на одну ({price} Z)", show_alert=True)

    limit = min(in_stock, space, available // price)
    await state.set_state(MarketStates.buying)
    await state.update_data(item=item, price=price,
                            chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    await _show(
        cb.message,
        f"🛒 {it.emoji} <b>{it.name}</b> по <b>{price} Z</b> (на прилавке {in_stock} шт)\n"
        f"Твой лимит: <b>{limit}</b> (склад {space}, денег на {available // price}).\n"
        "Сколько берём? Напиши число:")
    await cb.answer()


@router.message(MarketStates.buying)
async def market_buy_input(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    tg_id = msg.from_user.id
    item, price = data["item"], data["price"]
    it = ITEMS.get(item)
    delete_later(bot, msg.chat.id, msg.message_id)

    async def finish(text: str):
        try:
            await bot.edit_message_caption(chat_id=data["chat_id"], message_id=data["msg_id"],
                                           caption=text, reply_markup=_back(tg_id))
        except Exception:
            await msg.answer(text, reply_markup=_back(tg_id))

    raw = (msg.text or "").strip()
    if not raw.isdigit() or int(raw) < 1 or it is None:
        return await finish("❌ Это не число — отменено.")
    n = int(raw)

    # пересчитываем лимиты на момент ввода
    space = it.max_qty - await storage.get_item_qty(tg_id, item)
    if space <= 0:
        return await finish(f"❌ Склад забит ({it.max_qty} шт) — отменено.")
    n = min(n, space)

    taken = await storage.take_stock(item, price, n)
    if taken <= 0:
        return await finish("❌ Уже разобрали — отменено.")
    total = price * taken
    if not await storage.spend_zbucks(tg_id, total):
        await storage.add_stock(item, price, taken)  # вернуть на прилавок
        return await finish(f"❌ Не хватает Z (нужно {total}) — отменено.")

    await storage.add_item(tg_id, item, taken, it.max_qty)
    await storage.bump(tg_id, f"bought_{item}", taken)
    cnt = f" ×{taken}" if taken > 1 else ""
    note = "" if taken == n else f" (успел взять только {taken} — остальное разобрали)"
    await finish(f"🛒 Куплено: {it.emoji} {it.name}{cnt} за <b>{total} Z</b>!{note}")
