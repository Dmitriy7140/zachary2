"""Меню бизнесов: легальные конторы, отмыв и бистро слизней."""
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from content import slugs as slug_text
from content.business import (MOSQUITO_LORE, UPGRADE2_LORE, UPGRADE3_LORE,
                              bought as mosquito_bought, launder_done, launder_start,
                              renamed as mosquito_renamed, self_employed,
                              upgraded2, upgraded3)
from db import storage
from game.business import (BIZ_MOSQUITO, BIZ_SLUGS, BUSINESS_KEYS,
                           LAUNDER_HOURS, MOSQUITO_CORN, MOSQUITO_EGGS,
                           MOSQUITO_POTATO, MOSQUITO_PRICE, NAME_MAXLEN,
                           SE_TAX_KEY, SELF_EMPLOY_COST, SELF_EMPLOY_TAX,
                           SLUG_LORE, SLUG_PRICE, TIER_SMALL, available_slug_recipes,
                           biz_display, business_card_name, business_purchase_price,
                           get_slug_recipe, launder_cap_for, slug_recipe_limit,
                           upgrade_price, upkeep_for)
from game.cars import has_car
from game.items import ITEMS
from utils.cleanup import delete_later
from utils.guards import ensure_private, with_owner
from utils.notify import announce
from utils.photo import show_photo_menu, show_text_menu

BIZ_OFFICE_PHOTO = "static/business_office.png"
BIZ_OFFICE_META = "biz_office_photo_id"

NO_CAR_WHINE = ("🚗 Так, стоп, а чё я как лох без тачки?! Надо сначала колёса "
                "понтовые, чтоб все завидовали. (Тачки — в магазине)")

router = Router()


class BizStates(StatesGroup):
    rename = State()
    launder = State()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mention(tg_id: int, name: str) -> str:
    return hlink(name, f"tg://user?id={tg_id}")


def _known_business(biz: str) -> bool:
    return biz in BUSINESS_KEYS


def _back_to_legal(tg_id: int) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="⬅️ К легальному бизнесу", callback_data="biz:legal"),
            InlineKeyboardButton(text="🏠 В меню", callback_data=with_owner("menu:main", tg_id))]


def _back_to_root(tg_id: int) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="⬅️ К бизнесу", callback_data="menu:business"),
            InlineKeyboardButton(text="🏠 В меню", callback_data=with_owner("menu:main", tg_id))]


async def _answer_business(cb: CallbackQuery, biz: str | None = None) -> None:
    """Закрыть spinner; слизни подкалывают владельца тачки только в личке."""
    if biz == BIZ_SLUGS and await has_car(cb.from_user.id):
        await cb.answer(slug_text.car_mockery(), show_alert=True)
        return
    await cb.answer()


async def _owned_businesses(tg_id: int) -> list[tuple]:
    return [row for row in await storage.list_businesses(tg_id) if row[0] in BUSINESS_KEYS]


async def _render_root(message: Message, tg_id: int) -> None:
    await show_photo_menu(
        message,
        BIZ_OFFICE_PHOTO,
        BIZ_OFFICE_META,
        "🏢 <b>Бизнес</b>\n\n"
        "Круглый из <i>«Брата»</i> наверняка одобрил бы: деньги должны работать, "
        "а ты — иногда проверять, куда именно. Выбирай сторону предпринимательства.",
        _kb([
            [InlineKeyboardButton(text="✅ Легальный", callback_data="biz:legal")],
            [InlineKeyboardButton(text="🕶 Нелегальный", callback_data="biz:illegal")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", tg_id))],
        ]),
    )


async def _render_legal(message: Message, tg_id: int) -> None:
    owned = await _owned_businesses(tg_id)
    se = await storage.is_self_employed(tg_id)
    lines = ["✅ <b>Легальный бизнес</b>", ""]
    lines.append("📱 Самозанятость: " + (
        f"✅ оформлена (налог −{SELF_EMPLOY_TAX} Z/день)" if se
        else "❌ не оформлена — оформляется в 🎒 Инвентарь → Самсунг"))
    lines.append("")
    rows: list[list[InlineKeyboardButton]] = []
    if owned:
        lines.append("<b>Твои конторы:</b>")
        for biz, _tier, level, custom_name, _paused in owned:
            # В каталоге остаётся понятное каноническое название, а после
            # ребрендинга владелец сразу видит на кнопке своё.
            label = f"{custom_name or business_card_name(biz)} · ур. {level}"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"biz:open:{biz}")])
    else:
        lines.append("Пока ни одной конторы. Капитал ждёт твоих ошибок.")
    rows.append([InlineKeyboardButton(text="💼 Купить бизнес", callback_data="biz:catalog")])
    rows.append(_back_to_root(tg_id))
    await show_photo_menu(message, BIZ_OFFICE_PHOTO, BIZ_OFFICE_META, "\n".join(lines), _kb(rows))


async def _render_catalog(message: Message, tg_id: int) -> None:
    owned = {row[0] for row in await _owned_businesses(tg_id)}
    lines = ["💼 <b>Покупка бизнеса</b>", ""]
    rows: list[list[InlineKeyboardButton]] = []
    for biz in BUSINESS_KEYS:
        if biz in owned:
            continue
        rows.append([InlineKeyboardButton(
            text=f"{business_card_name(biz)} — {business_purchase_price(biz)} Z",
            callback_data=f"biz:card:{biz}",
        )])
    if not rows:
        lines.append("Ты уже скупил весь доступный легальный бизнес. Поздравляем, капиталист.")
    else:
        lines.append("Выбери контору. Бумаги нужны настоящие, а идеи — как получится.")
    rows.append(_back_to_legal(tg_id))
    await show_text_menu(message, "\n".join(lines), _kb(rows))


def _mosquito_production(level: int) -> str:
    text = f"{MOSQUITO_EGGS[0]}–{MOSQUITO_EGGS[1]} 🥚 в час"
    if level >= 2:
        text += f" + {MOSQUITO_CORN[0]}–{MOSQUITO_CORN[1]} 🌽"
    if level >= 3:
        text += f" + {MOSQUITO_POTATO[0]}–{MOSQUITO_POTATO[1]} 🥔"
    return text


async def _render_business(message: Message, tg_id: int, biz: str) -> bool:
    if not _known_business(biz):
        return False
    row = await storage.get_business(tg_id, biz)
    if not row:
        return False
    _tier, level, custom_name, paused = row
    dirty = await storage.get_dirty(tg_id)
    hidden = await storage.hidden_now(tg_id)
    in_wash = await storage.laundering_active_sum(tg_id, biz)
    cap = launder_cap_for(level)
    name = biz_display(custom_name, level, biz)
    icon = "🦟" if biz == BIZ_MOSQUITO else "🐌"
    lines = [
        f"{icon} <b>{name}</b>",
        f"Уровень <b>{level}</b> · малый бизнес",
        f"Статус: {'⛔ приостановлен (не оплачено содержание)' if paused else '✅ работает'}",
        f"Содержание: {upkeep_for(level, biz)} Z/день",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    if biz == BIZ_MOSQUITO:
        lines.append(f"Продукция: {_mosquito_production(level)} (падает в инвентарь)")
    else:
        cooks = await storage.list_slug_cooks(tg_id)
        active = [entry for entry in cooks if entry[2] != "delivered"]
        lines.append(f"Готовится и ждёт выдачи: <b>{len(active)}</b> / 5")
        for item, ready_at, status in active:
            item_name = ITEMS.get(item).name if item in ITEMS else item
            if status == "ready":
                lines.append(f"  • {item_name} — готово, ждёт места в инвентаре")
            else:
                left = max(0, int((datetime.fromisoformat(ready_at) - datetime.now()).total_seconds()))
                lines.append(f"  • {item_name} — через {left // 60}м {left % 60}с")
        lines.append("")
        lines.append("<b>Производство:</b>")
        for recipe in available_slug_recipes(level):
            product = ITEMS[recipe.item]
            ingredient = ITEMS[recipe.ingredient]
            lines.append(
                f"• {product.name}: {recipe.ingredient_qty} {ingredient.emoji}, "
                f"{recipe.minutes} мин")
            rows.append([InlineKeyboardButton(
                text=f"🐌 Готовить {product.emoji} {product.name}",
                callback_data=f"biz:cook:{recipe.item}",
            )])
    lines.extend([
        "",
        f"🧺 Отмыв: в стирке <b>{in_wash}</b> / {cap} Z · "
        f"грязных на руках: {max(0, dirty - hidden)} Z",
    ])
    launderings = await storage.get_launderings(tg_id, biz)
    for amount, ready_at in launderings[:5]:
        left = max(0, int((datetime.fromisoformat(ready_at) - datetime.now()).total_seconds()))
        lines.append(f"  • {amount} Z — вернутся через {left // 3600}ч {left % 3600 // 60}м")
    if len(launderings) > 5:
        lines.append(f"  • … и ещё {len(launderings) - 5} закладок")
    price = upgrade_price(biz, level)
    upgrade_label = f"⬆️ Улучшить — {price} Z" if price else "⬆️ Максимальный уровень"
    rows.extend([
        [InlineKeyboardButton(text="🧺 Отмыть бабки", callback_data=f"biz:launder:{biz}")],
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"biz:rename:{biz}"),
         InlineKeyboardButton(text=upgrade_label, callback_data=f"biz:upgrade:{biz}")],
        _back_to_legal(tg_id),
    ])
    await show_photo_menu(message, BIZ_OFFICE_PHOTO, BIZ_OFFICE_META, "\n".join(lines), _kb(rows))
    return True


# ---------- корень и каталоги ----------

@router.callback_query(F.data == "menu:business")
async def business_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render_root(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "biz:legal")
async def business_legal(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render_legal(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "biz:illegal")
async def business_illegal(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    await show_text_menu(
        cb.message,
        "🕶 <b>Нелегальный бизнес</b>\n\n"
        "Пока тут пусто: схемы ещё сушатся на батарее, а бухгалтер прячется от Густава.",
        _kb([_back_to_root(cb.from_user.id)]),
    )
    await cb.answer()


@router.callback_query(F.data == "biz:catalog")
async def business_catalog(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    await _render_catalog(cb.message, cb.from_user.id)
    await cb.answer()


async def _show_card(cb: CallbackQuery, biz: str) -> None:
    if not _known_business(biz):
        return await cb.answer("Нет такого бизнеса", show_alert=True)
    if await storage.get_business(cb.from_user.id, biz):
        return await cb.answer("У тебя уже есть этот бизнес", show_alert=True)
    if biz == BIZ_MOSQUITO:
        text = (
            f"{MOSQUITO_LORE}\n\n"
            f"Цена: <b>{MOSQUITO_PRICE} Z</b> · содержание {upkeep_for(1, biz)} Z/день\n"
            f"Продукция: {_mosquito_production(1)}"
        )
    else:
        recipe = get_slug_recipe("slime_pie")
        text = (
            f"{SLUG_LORE}\n\n"
            f"Цена: <b>{SLUG_PRICE} Z</b> · зарплаты слизням {upkeep_for(1, biz)} Z/день\n"
            f"Первое производство: {ITEMS[recipe.item].name} — "
            f"{recipe.ingredient_qty} {ITEMS[recipe.ingredient].name}, {recipe.minutes} мин."
        )
    await show_text_menu(
        cb.message, text,
        _kb([
            [InlineKeyboardButton(text=f"💰 Купить за {business_purchase_price(biz)} Z",
                                  callback_data=f"biz:buy:{biz}")],
            _back_to_legal(cb.from_user.id),
        ]),
    )
    await _answer_business(cb, biz)


@router.callback_query(F.data.startswith("biz:card:"))
async def business_card(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    await _show_card(cb, cb.data.split(":")[2])


@router.callback_query(F.data == "biz:card")
async def legacy_business_card(cb: CallbackQuery):
    """Старые сообщения с кнопкой Комаров остаются рабочими."""
    if not await ensure_private(cb):
        return
    await _show_card(cb, BIZ_MOSQUITO)


@router.callback_query(F.data.startswith("biz:open:"))
async def business_open(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    biz = cb.data.split(":")[2]
    if not await _render_business(cb.message, cb.from_user.id, biz):
        return await cb.answer("Этой конторы у тебя уже нет", show_alert=True)
    await _answer_business(cb, biz)


# ---------- самозанятость (вызывается из Инвентаря → Самсунг) ----------

async def do_self_employ(cb: CallbackQuery, bot: Bot) -> bool:
    """Оформить самозанятость. True — оформили."""
    tg_id = cb.from_user.id
    if await storage.is_self_employed(tg_id):
        await cb.answer("Ты уже самозанятый 😉", show_alert=True)
        return False
    has_samsung = await storage.get_item_qty(tg_id, "samsung") > 0
    has_iphone = await storage.get_item_qty(tg_id, "iphone") > 0
    if not has_samsung:
        text = ("📱 С айфона Госуслуги не работают — крутится колёсико и вылетает. Нужен Самсунг."
                if has_iphone else "📱 Нужен Самсунг — Госуслуги сами себя не откроют")
        await cb.answer(text, show_alert=True)
        return False
    if not await storage.spend_zbucks(tg_id, SELF_EMPLOY_COST):
        await cb.answer(f"Не хватает Z (регистрация {SELF_EMPLOY_COST}, дальше налог "
                        f"−{SELF_EMPLOY_TAX} Z/день)", show_alert=True)
        return False
    await storage.set_self_employed(tg_id)
    await storage.set_cooldown_until(
        tg_id, SE_TAX_KEY, (datetime.now() + timedelta(days=1)).isoformat())
    await announce(bot, self_employed(_mention(tg_id, cb.from_user.full_name)))
    await cb.answer(f"📱 Самозанятость оформлена! Теперь ФНС будет откусывать "
                    f"{SELF_EMPLOY_TAX} Z в день.", show_alert=True)
    return True


@router.callback_query(F.data == "biz:selfemploy")
async def biz_selfemploy(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    if await do_self_employ(cb, bot):
        await _render_root(cb.message, cb.from_user.id)


# ---------- покупка ----------

async def _buy_business(cb: CallbackQuery, bot: Bot, state: FSMContext, biz: str) -> None:
    if not _known_business(biz):
        return await cb.answer("Нет такого бизнеса", show_alert=True)
    now = datetime.now()
    produce_at = (now + timedelta(hours=1)).isoformat() if biz == BIZ_MOSQUITO else None
    status = await storage.buy_business_atomic(
        cb.from_user.id, biz, TIER_SMALL, business_purchase_price(biz),
        produce_at=produce_at, upkeep_at=(now + timedelta(days=1)).isoformat(),
    )
    errors = {
        "already_owned": "У тебя уже есть этот бизнес",
        "not_self_employed": ("📱 Деньги есть, а бумажек нет! Без самозанятости бизнес не оформить — "
                                "открой 🎒 Инвентарь → Самсунг."),
        "insufficient_funds": f"Не хватает Z (нужно {business_purchase_price(biz)})",
        "no_profile": "Сначала зарегистрируйся 😉",
    }
    if status != "ok":
        return await cb.answer(errors.get(status, "Не удалось оформить бизнес"), show_alert=True)
    name = biz_display(None, 1, biz)
    who = _mention(cb.from_user.id, cb.from_user.full_name)
    if biz == BIZ_MOSQUITO:
        await announce(bot, mosquito_bought(who, name, business_purchase_price(biz)))
    else:
        await announce(bot, slug_text.bought(who, name, business_purchase_price(biz)))
    await state.set_state(BizStates.rename)
    await state.update_data(biz=biz, chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    await cb.message.edit_text(
        f"<b>{name}</b> теперь твой!\n\nХочешь переименовать? Напиши название одним "
        f"сообщением (до {NAME_MAXLEN} символов). Оставить как есть — отправь «-»."
    )
    await _answer_business(cb, biz)


@router.callback_query(F.data.startswith("biz:buy:"))
async def business_buy(cb: CallbackQuery, bot: Bot, state: FSMContext):
    if not await ensure_private(cb):
        return
    await _buy_business(cb, bot, state, cb.data.split(":")[2])


@router.callback_query(F.data == "biz:buy")
async def legacy_business_buy(cb: CallbackQuery, bot: Bot, state: FSMContext):
    if not await ensure_private(cb):
        return
    await _buy_business(cb, bot, state, BIZ_MOSQUITO)


# ---------- переименование ----------

async def _begin_rename(cb: CallbackQuery, state: FSMContext, biz: str) -> None:
    if not _known_business(biz) or not await storage.get_business(cb.from_user.id, biz):
        return await cb.answer("Сначала купи бизнес", show_alert=True)
    message = await show_text_menu(
        cb.message,
        f"✏️ Новое название (до {NAME_MAXLEN} символов) одним сообщением.\n"
        "Отменить — отправь «-».",
    )
    await state.set_state(BizStates.rename)
    await state.update_data(biz=biz, chat_id=message.chat.id, msg_id=message.message_id)
    await _answer_business(cb, biz)


@router.callback_query(F.data.startswith("biz:rename:"))
async def business_rename(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    await _begin_rename(cb, state, cb.data.split(":")[2])


@router.callback_query(F.data == "biz:rename")
async def legacy_business_rename(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    # CallbackQuery неизменяемый; старые кнопки направляем явно, а не меняем
    # cb.data на лету.
    await _begin_rename(cb, state, BIZ_MOSQUITO)


@router.message(BizStates.rename)
async def business_rename_input(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    if msg.chat.type != ChatType.PRIVATE:
        return
    tg_id = msg.from_user.id
    biz = data.get("biz", BIZ_MOSQUITO)
    delete_later(bot, msg.chat.id, msg.message_id)
    raw = (msg.text or "").strip()
    if raw and raw != "-" and not raw.startswith("/") and await storage.get_business(tg_id, biz):
        await storage.set_business_name(tg_id, biz, raw[:NAME_MAXLEN])
        row = await storage.get_business(tg_id, biz)
        name = biz_display(raw[:NAME_MAXLEN], row[1] if row else 1, biz)
        who = _mention(tg_id, msg.from_user.full_name)
        await announce(bot, mosquito_renamed(who, name) if biz == BIZ_MOSQUITO
                       else slug_text.renamed(who, name))
    try:
        await bot.delete_message(data["chat_id"], data["msg_id"])
    except Exception:
        pass
    sent = await msg.answer("🏢 <b>Бизнес</b>")
    await _render_business(sent, tg_id, biz)


# ---------- отмыв ----------

async def _begin_launder(cb: CallbackQuery, state: FSMContext, biz: str) -> None:
    row = await storage.get_business(cb.from_user.id, biz) if _known_business(biz) else None
    if not row:
        return await cb.answer("Сначала купи бизнес", show_alert=True)
    cap = launder_cap_for(row[1])
    dirty_avail = max(0, await storage.get_dirty(cb.from_user.id) - await storage.hidden_now(cb.from_user.id))
    free_cap = cap - await storage.laundering_active_sum(cb.from_user.id, biz)
    if free_cap <= 0:
        return await cb.answer(f"🧺 Стирка забита ({cap} Z) — жди возврата", show_alert=True)
    if dirty_avail <= 0:
        return await cb.answer("Грязных денег на руках нет — нечего стирать 🤷", show_alert=True)
    message = await show_text_menu(
        cb.message,
        f"🧺 <b>Отмыв бабок</b>\nГрязных на руках: <b>{dirty_avail} Z</b> · "
        f"свободно в стирке: <b>{free_cap} Z</b>\n"
        f"Закладка вернётся чистой через {LAUNDER_HOURS} часа.\n\n"
        f"Сколько закладываем? Напиши число (до {min(dirty_avail, free_cap)}):",
    )
    await state.set_state(BizStates.launder)
    await state.update_data(biz=biz, chat_id=message.chat.id, msg_id=message.message_id)
    await _answer_business(cb, biz)


@router.callback_query(F.data.startswith("biz:launder:"))
async def business_launder(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    await _begin_launder(cb, state, cb.data.split(":")[2])


@router.callback_query(F.data == "biz:launder")
async def legacy_business_launder(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    await _begin_launder(cb, state, BIZ_MOSQUITO)


@router.message(BizStates.launder)
async def business_launder_input(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    if msg.chat.type != ChatType.PRIVATE:
        return
    tg_id = msg.from_user.id
    biz = data.get("biz", BIZ_MOSQUITO)
    delete_later(bot, msg.chat.id, msg.message_id)
    raw = (msg.text or "").strip()

    async def finish(text: str) -> None:
        try:
            await bot.edit_message_text(
                text, chat_id=data["chat_id"], message_id=data["msg_id"],
                reply_markup=_kb([_back_to_legal(tg_id)]),
            )
        except Exception:
            await msg.answer(text, reply_markup=_kb([_back_to_legal(tg_id)]))

    if not raw.isdigit() or int(raw) < 1:
        return await finish("❌ Это не число — отменено.")
    amount = int(raw)
    ready_at = (datetime.now() + timedelta(hours=LAUNDER_HOURS)).isoformat()
    row = await storage.get_business(tg_id, biz)
    status = await storage.start_laundering_atomic(
        tg_id, biz, amount, ready_at, launder_cap_for(row[1]) if row else 0)
    errors = {
        "not_owned": "❌ Бизнеса уже нет — отменено.",
        "paused": "❌ Бизнес на паузе: сначала дождись оплаты содержания.",
        "insufficient_dirty": "❌ Столько грязных денег уже недоступно — отменено.",
        "limit": "❌ В стирке не осталось столько места — отменено.",
        "no_profile": "❌ Профиль уже не найден — отменено.",
    }
    if status != "ok":
        return await finish(errors.get(status, "❌ Не удалось заложить деньги — отменено."))
    row = await storage.get_business(tg_id, biz)
    name = biz_display(row[2] if row else None, row[1] if row else 1, biz)
    ready_label = datetime.fromisoformat(ready_at).strftime('%d.%m в %H:%M')
    who = _mention(tg_id, msg.from_user.full_name)
    await announce(
        bot,
        launder_start(who, name, amount) if biz == BIZ_MOSQUITO
        else slug_text.launder_start(who, name, amount),
    )
    if biz == BIZ_SLUGS:
        return await finish(slug_text.launder_started_personal(amount, ready_label))
    await finish(f"🧺 {amount} Z ушли в стирку. Вернутся чистыми {ready_label}.")


# ---------- улучшение ----------

async def _show_upgrade_confirmation(cb: CallbackQuery, biz: str) -> None:
    row = await storage.get_business(cb.from_user.id, biz) if _known_business(biz) else None
    if not row:
        return await cb.answer("Сначала купи бизнес", show_alert=True)
    level = row[1]
    price = upgrade_price(biz, level)
    if price is None:
        return await cb.answer("🔨 Дальше пока некуда — холдинг отдыхает на лаврах", show_alert=True)
    if biz == BIZ_MOSQUITO and level == 1 and not await has_car(cb.from_user.id):
        return await cb.answer(NO_CAR_WHINE, show_alert=True)
    await show_text_menu(
        cb.message,
        f"⬆️ <b>Уровень {level + 1}</b>\n\n"
        f"Содержание вырастет до {upkeep_for(level + 1, biz)} Z/день, "
        f"а отмыв — до {launder_cap_for(level + 1)} Z.\n"
        f"Цена: <b>{price} Z</b>",
        _kb([
            [InlineKeyboardButton(text=f"💰 Улучшить за {price} Z",
                                  callback_data=f"biz:upgrade_yes:{biz}:{level}")],
            _back_to_legal(cb.from_user.id),
        ]),
    )
    await _answer_business(cb, biz)


@router.callback_query(F.data == "biz:upgrade:yes")
async def legacy_business_upgrade_yes(cb: CallbackQuery):
    """Старая кнопка не содержит уровень — только перерисовываем safe-confirm."""
    if not await ensure_private(cb):
        return
    await _show_upgrade_confirmation(cb, BIZ_MOSQUITO)


@router.callback_query(F.data == "biz:upgrade")
async def legacy_business_upgrade(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    await _show_upgrade_confirmation(cb, BIZ_MOSQUITO)


@router.callback_query(F.data.startswith("biz:upgrade:"))
async def business_upgrade(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    parts = cb.data.split(":")
    if len(parts) != 3:
        return await cb.answer("Старая кнопка улучшения", show_alert=True)
    await _show_upgrade_confirmation(cb, parts[2])


@router.callback_query(F.data.startswith("biz:upgrade_yes:"))
async def business_upgrade_yes(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    parts = cb.data.split(":")
    if len(parts) != 4:
        return await cb.answer("Старая кнопка улучшения", show_alert=True)
    _, _, biz, level_raw = parts
    if not _known_business(biz) or not level_raw.isdigit() or int(level_raw) < 1:
        return await cb.answer("Старая кнопка улучшения", show_alert=True)
    level = int(level_raw)
    if biz == BIZ_MOSQUITO and level == 1 and not await has_car(cb.from_user.id):
        return await cb.answer(NO_CAR_WHINE, show_alert=True)
    price = upgrade_price(biz, level)
    if price is None:
        return await cb.answer("Уже на максимуме 😉", show_alert=True)
    status = await storage.upgrade_business_atomic(cb.from_user.id, biz, level, price)
    if status != "ok":
        errors = {
            "not_owned": "Сначала купи бизнес",
            "stale": "Уровень уже изменился — обнови экран",
            "max_level": "Уже на максимальном уровне 😉",
            "insufficient_funds": f"Не хватает Z (нужно {price})",
        }
        return await cb.answer(errors.get(status, "Не удалось улучшить бизнес"), show_alert=True)
    new_level = level + 1
    row = await storage.get_business(cb.from_user.id, biz)
    name = biz_display(row[2] if row else None, new_level, biz)
    who = _mention(cb.from_user.id, cb.from_user.full_name)
    if biz == BIZ_MOSQUITO:
        lore = UPGRADE2_LORE if new_level == 2 else UPGRADE3_LORE
        phrase = upgraded2(who, name, price) if new_level == 2 else upgraded3(who, name, price)
    else:
        lore = ("⬆️ Слизни расширили «пекарню». Капиталисты радостно вложились в глину, "
                "а слизни решили, что это любовь к кулинарии.")
        phrase = slug_text.upgraded(who, name, price, new_level)
    await announce(bot, phrase)
    await cb.message.edit_text(
        f"{lore}\n\n<b>{name}</b> теперь уровня {new_level}.",
        reply_markup=_kb([_back_to_legal(cb.from_user.id)]),
    )
    await _answer_business(cb, biz)


# ---------- готовка слизней ----------

@router.callback_query(F.data.startswith("biz:cook:"))
async def business_cook_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    parts = cb.data.split(":")
    if len(parts) != 3:
        return await cb.answer("Старая кнопка готовки", show_alert=True)
    item = parts[2]
    recipe = get_slug_recipe(item)
    row = await storage.get_business(cb.from_user.id, BIZ_SLUGS)
    if not recipe or not row:
        return await cb.answer("Сначала купи бистро", show_alert=True)
    if row[3]:
        return await cb.answer("Слизни бастуют: сначала заплати зарплату", show_alert=True)
    if row[1] < recipe.unlock_level:
        return await cb.answer("Этот рецепт откроется на следующем уровне", show_alert=True)
    active = len([entry for entry in await storage.list_slug_cooks(cb.from_user.id)
                  if entry[2] != "delivered"])
    ingredient_qty = await storage.get_item_qty(cb.from_user.id, recipe.ingredient)
    product_qty = await storage.get_item_qty(cb.from_user.id, recipe.item)
    limit = slug_recipe_limit(active, ingredient_qty, product_qty, recipe)
    if limit <= 0:
        return await cb.answer("Не хватает сырья, места в инвентаре или свободных печек", show_alert=True)
    rows = [[InlineKeyboardButton(text=str(n), callback_data=f"biz:cook_qty:{item}:{n}")
             for n in range(1, limit + 1)], _back_to_legal(cb.from_user.id)]
    await show_text_menu(
        cb.message,
        f"🐌 <b>{ITEMS[recipe.item].name}</b>\n"
        f"На одну штуку: {recipe.ingredient_qty} {ITEMS[recipe.ingredient].name}.\n"
        f"Каждая будет готова через {recipe.minutes} мин; свободно можно поставить: {limit}.\n\n"
        "Сколько лепим?",
        _kb(rows),
    )
    await _answer_business(cb, BIZ_SLUGS)


@router.callback_query(F.data.startswith("biz:cook_qty:"))
async def business_cook_start(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    parts = cb.data.split(":")
    if len(parts) != 4:
        return await cb.answer("Старая кнопка готовки", show_alert=True)
    _, _, item, amount_raw = parts
    recipe = get_slug_recipe(item)
    if not recipe or not amount_raw.isdigit() or int(amount_raw) < 1:
        return await cb.answer("Старая кнопка готовки", show_alert=True)
    amount = int(amount_raw)
    ready_at = (datetime.now() + timedelta(minutes=recipe.minutes)).isoformat()
    status = await storage.start_slug_cooking_atomic(
        cb.from_user.id, recipe.item, recipe.ingredient, recipe.ingredient_qty,
        recipe.unlock_level, amount, ready_at,
    )
    errors = {
        "not_owned": "Сначала купи бистро",
        "paused": "Слизни бастуют: сначала заплати зарплату",
        "locked": "Этот рецепт ещё закрыт",
        "no_ingredients": "Сырья уже не хватает",
        "limit": "Свободных печек уже нет",
        "inventory_full": "В инвентаре не хватит места для готовых изделий",
    }
    if status != "ok":
        return await cb.answer(errors.get(status, "Не удалось запустить готовку"), show_alert=True)
    await _render_business(cb.message, cb.from_user.id, BIZ_SLUGS)
    await _answer_business(cb, BIZ_SLUGS)
