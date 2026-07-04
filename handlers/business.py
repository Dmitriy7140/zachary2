"""Меню «Бизнес»: самозанятость, покупка Комар-фарм Логистикс, отмыв, ребрендинг.

Самозанятость: 1000 Z разово + фиксированный налог 200 Z/день (списывает
планировщик бизнесов, уведомления о расходах приходят в личку).
"""
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from content.business import (MOSQUITO_LORE, UPGRADE2_LORE, UPGRADE3_LORE, bought,
                              launder_start, renamed, self_employed, upgraded2, upgraded3)
from db import storage
from game.business import (BIZ_MOSQUITO, DEFAULT_NAME, LAUNDER_HOURS, MOSQUITO_CORN,
                           MOSQUITO_EGGS, MOSQUITO_POTATO, MOSQUITO_PRICE, NAME_MAXLEN,
                           SE_TAX_KEY, SELF_EMPLOY_COST, SELF_EMPLOY_TAX, TIER_SMALL,
                           UPGRADE2_PRICE, UPGRADE3_PRICE, biz_display, launder_cap_for,
                           upkeep_for)
from game.cars import has_car

NO_CAR_WHINE = ("🚗 Так, стоп, а чё я как лох без тачки?! Надо сначала колёса "
                "понтовые, чтоб все завидовали. (Тачки — в магазине)")
from utils.cleanup import delete_later
from utils.guards import ensure_private, with_owner
from utils.notify import announce

router = Router()


class BizStates(StatesGroup):
    rename = State()
    launder = State()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mention(tg_id: int, name: str) -> str:
    return hlink(name, f"tg://user?id={tg_id}")


def _back_row(tg_id: int):
    return [InlineKeyboardButton(text="⬅️ К бизнесу", callback_data="menu:business"),
            InlineKeyboardButton(text="🏠 В меню", callback_data=with_owner("menu:main", tg_id))]


# ---------- меню ----------

async def _render(message, tg_id: int) -> None:
    biz = await storage.get_business(tg_id, BIZ_MOSQUITO)
    se = await storage.is_self_employed(tg_id)

    if biz is None:
        lines = ["🏢 <b>Бизнес</b>", ""]
        se_line = "📱 Самозанятость: " + (
            f"✅ оформлена (налог {SELF_EMPLOY_TAX} Z/день)" if se else "❌ не оформлена")
        lines.append(se_line)
        lines.append("")
        lines.append("Доступно к покупке:")
        rows = [[InlineKeyboardButton(text=f"🦟 {DEFAULT_NAME} — {MOSQUITO_PRICE} Z",
                                      callback_data="biz:card")]]
        if not se:
            rows.append([InlineKeyboardButton(
                text=f"📱 Самозанятость — {SELF_EMPLOY_COST} Z (+{SELF_EMPLOY_TAX}/день)",
                callback_data="biz:selfemploy")])
        rows.append([InlineKeyboardButton(text="⬅️ В меню",
                                          callback_data=with_owner("menu:main", tg_id))])
        await message.edit_text("\n".join(lines), reply_markup=_kb(rows))
        return

    tier, level, custom_name, paused = biz
    dirty = await storage.get_dirty(tg_id)
    hidden = await storage.hidden_now(tg_id)
    in_wash = await storage.laundering_active_sum(tg_id)
    prod = f"{MOSQUITO_EGGS[0]}–{MOSQUITO_EGGS[1]} 🥚 в час"
    if level >= 2:
        prod += f" + {MOSQUITO_CORN[0]}–{MOSQUITO_CORN[1]} 🌽"
    if level >= 3:
        prod += f" + {MOSQUITO_POTATO[0]}–{MOSQUITO_POTATO[1]} 🥔"
    cap = launder_cap_for(level)
    lines = [
        f"🦟 <b>{biz_display(custom_name, level)}</b>",
        f"Уровень <b>{level}</b> · малый бизнес",
        f"Статус: {'⛔ приостановлен (не оплачено содержание)' if paused else '✅ работает'}",
        f"Содержание: {upkeep_for(level)} Z/день",
        f"Продукция: {prod} (падает в инвентарь)",
        "",
        f"🧺 Отмыв: в стирке <b>{in_wash}</b> / {cap} Z · "
        f"грязных на руках: {max(0, dirty - hidden)} Z",
    ]
    for amount, ready_at in await storage.get_launderings(tg_id):
        left = max(0, int((datetime.fromisoformat(ready_at) - datetime.now()).total_seconds()))
        lines.append(f"  • {amount} Z — вернутся через {left // 3600}ч {left % 3600 // 60}м")
    if level == 1:
        upg_label = f"⬆️ Улучшить — {UPGRADE2_PRICE} Z"
    elif level == 2:
        upg_label = f"⬆️ Улучшить — {UPGRADE3_PRICE} Z"
    else:
        upg_label = "⬆️ Улучшить"
    rows = [
        [InlineKeyboardButton(text="🧺 Отмыть бабки", callback_data="biz:launder")],
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data="biz:rename"),
         InlineKeyboardButton(text=upg_label, callback_data="biz:upgrade")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", tg_id))],
    ]
    await message.edit_text("\n".join(lines), reply_markup=_kb(rows))


@router.callback_query(F.data == "menu:business")
async def business_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render(cb.message, cb.from_user.id)
    await cb.answer()


# ---------- самозанятость ----------

@router.callback_query(F.data == "biz:selfemploy")
async def biz_selfemploy(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if await storage.is_self_employed(tg_id):
        return await cb.answer("Ты уже самозанятый 😉", show_alert=True)

    has_samsung = await storage.get_item_qty(tg_id, "samsung") > 0
    has_iphone = await storage.get_item_qty(tg_id, "iphone") > 0
    if not has_samsung:
        if has_iphone:
            return await cb.answer(
                "📱 С айфона Госуслуги не работают — крутится колёсико и вылетает. "
                "Нужен Самсунг.", show_alert=True)
        return await cb.answer("📱 Нужен Самсунг — Госуслуги сами себя не откроют", show_alert=True)

    if not await storage.spend_zbucks(tg_id, SELF_EMPLOY_COST):
        return await cb.answer(f"Не хватает Z (регистрация {SELF_EMPLOY_COST}, "
                               f"дальше налог {SELF_EMPLOY_TAX} Z/день)", show_alert=True)

    await storage.set_self_employed(tg_id)
    # первый налог — через сутки, дальше планировщик сам
    await storage.set_cooldown_until(
        tg_id, SE_TAX_KEY, (datetime.now() + timedelta(days=1)).isoformat())
    await announce(bot, self_employed(_mention(tg_id, cb.from_user.full_name)))
    await cb.answer(f"📱 Самозанятость оформлена! Теперь ФНС будет откусывать "
                    f"{SELF_EMPLOY_TAX} Z в день.", show_alert=True)
    await _render(cb.message, tg_id)


# ---------- карточка и покупка ----------

@router.callback_query(F.data == "biz:card")
async def biz_card(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if await storage.get_business(tg_id, BIZ_MOSQUITO):
        return await cb.answer("У тебя уже есть этот бизнес", show_alert=True)
    rows = [
        [InlineKeyboardButton(text=f"💰 Купить за {MOSQUITO_PRICE} Z", callback_data="biz:buy")],
        _back_row(tg_id),
    ]
    await cb.message.edit_text(
        f"{MOSQUITO_LORE}\n\n"
        f"Цена: <b>{MOSQUITO_PRICE} Z</b> · содержание {MOSQUITO_UPKEEP} Z/день\n"
        f"Продукция: {MOSQUITO_EGGS[0]}–{MOSQUITO_EGGS[1]} 🥚 в час",
        reply_markup=_kb(rows))
    await cb.answer()


@router.callback_query(F.data == "biz:buy")
async def biz_buy(cb: CallbackQuery, bot: Bot, state: FSMContext):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if await storage.get_business(tg_id, BIZ_MOSQUITO):
        return await cb.answer("У тебя уже есть этот бизнес", show_alert=True)
    if not await storage.is_self_employed(tg_id):
        return await cb.answer(
            "📱 Без самозанятости бизнес не оформить — сначала зарегистрируйся "
            "через Самсунг (кнопка в меню Бизнес)", show_alert=True)
    if not await storage.spend_zbucks(tg_id, MOSQUITO_PRICE):
        return await cb.answer(f"Не хватает Z (нужно {MOSQUITO_PRICE})", show_alert=True)

    now = datetime.now()
    await storage.create_business(
        tg_id, BIZ_MOSQUITO, TIER_SMALL,
        produce_at=(now + timedelta(hours=1)).isoformat(),
        upkeep_at=(now + timedelta(days=1)).isoformat(),
    )
    await announce(bot, bought(_mention(tg_id, cb.from_user.full_name),
                               biz_display(None, 1), MOSQUITO_PRICE))

    # сразу предлагаем ребрендинг
    await state.set_state(BizStates.rename)
    await state.update_data(chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    await cb.message.edit_text(
        f"🦟 <b>{biz_display(None, 1)}</b> теперь твой!\n\n"
        f"Хочешь переименовать? Напиши название одним сообщением "
        f"(до {NAME_MAXLEN} символов).\nОставить как есть — отправь «-».")
    await cb.answer()


# ---------- переименование ----------

@router.callback_query(F.data == "biz:rename")
async def biz_rename(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_business(tg_id, BIZ_MOSQUITO):
        return await cb.answer("Сначала купи бизнес", show_alert=True)
    await state.set_state(BizStates.rename)
    await state.update_data(chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    await cb.message.edit_text(
        f"✏️ Новое название (до {NAME_MAXLEN} символов) одним сообщением.\n"
        f"Отменить — отправь «-».")
    await cb.answer()


@router.message(BizStates.rename)
async def biz_rename_input(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    tg_id = msg.from_user.id
    delete_later(bot, msg.chat.id, msg.message_id)

    async def finish():
        try:
            await bot.delete_message(data["chat_id"], data["msg_id"])
        except Exception:
            pass
        sent = await msg.answer("🏢 <b>Бизнес</b>")
        await _render(sent, tg_id)

    name = (msg.text or "").strip()
    if not name or name == "-" or name.startswith("/"):
        return await finish()
    name = name[:NAME_MAXLEN]
    await storage.set_business_name(tg_id, BIZ_MOSQUITO, name)
    biz_row = await storage.get_business(tg_id, BIZ_MOSQUITO)
    level = biz_row[1] if biz_row else 1
    await announce(bot, renamed(_mention(tg_id, msg.from_user.full_name),
                                biz_display(name, level)))
    await finish()


# ---------- отмыв ----------

@router.callback_query(F.data == "biz:launder")
async def biz_launder(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    biz = await storage.get_business(tg_id, BIZ_MOSQUITO)
    if not biz:
        return await cb.answer("Сначала купи бизнес", show_alert=True)
    cap = launder_cap_for(biz[1])

    dirty_avail = max(0, await storage.get_dirty(tg_id) - await storage.hidden_now(tg_id))
    free_cap = cap - await storage.laundering_active_sum(tg_id)
    limit = min(dirty_avail, free_cap)
    if free_cap <= 0:
        return await cb.answer(f"🧺 Стирка забита ({cap} Z) — жди возврата", show_alert=True)
    if dirty_avail <= 0:
        return await cb.answer("Грязных денег на руках нет — нечего стирать 🤷", show_alert=True)

    await state.set_state(BizStates.launder)
    await state.update_data(chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    await cb.message.edit_text(
        f"🧺 <b>Отмыв бабок</b>\n"
        f"Грязных на руках: <b>{dirty_avail} Z</b> · свободно в стирке: <b>{free_cap} Z</b>\n"
        f"Закладка вернётся чистой через {LAUNDER_HOURS} часа.\n\n"
        f"Сколько закладываем? Напиши число (до {limit}):")
    await cb.answer()


@router.message(BizStates.launder)
async def biz_launder_input(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    tg_id = msg.from_user.id
    delete_later(bot, msg.chat.id, msg.message_id)

    async def finish(text: str):
        try:
            await bot.edit_message_text(text, chat_id=data["chat_id"], message_id=data["msg_id"],
                                        reply_markup=_kb([_back_row(tg_id)]))
        except Exception:
            await msg.answer(text, reply_markup=_kb([_back_row(tg_id)]))

    raw = (msg.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        return await finish("❌ Это не число — отменено.")
    amount = int(raw)

    # перепроверяем лимиты на момент ввода
    biz_row = await storage.get_business(tg_id, BIZ_MOSQUITO)
    cap = launder_cap_for(biz_row[1]) if biz_row else 0
    dirty_avail = max(0, await storage.get_dirty(tg_id) - await storage.hidden_now(tg_id))
    free_cap = cap - await storage.laundering_active_sum(tg_id)
    if amount > dirty_avail:
        return await finish(f"❌ Грязных на руках только {dirty_avail} Z — отменено.")
    if amount > free_cap:
        return await finish(f"❌ В стирке свободно лишь {free_cap} Z — отменено.")
    # amount <= доступных грязных, значит спишутся именно грязные (они первые)
    if await storage.spend_zbucks_traced(tg_id, amount) is None:
        return await finish("❌ Не хватает Z — отменено.")

    ready_at = datetime.now() + timedelta(hours=LAUNDER_HOURS)
    await storage.add_laundering(tg_id, amount, ready_at.isoformat())

    biz_name = biz_display(biz_row[2] if biz_row else None, biz_row[1] if biz_row else 1)
    await announce(bot, launder_start(_mention(tg_id, msg.from_user.full_name), biz_name, amount))
    await finish(f"🧺 {amount} Z ушли в стирку. Вернутся чистыми "
                 f"{ready_at.strftime('%d.%m в %H:%M')}.")


# ---------- улучшение ----------

# следующий уровень: (цена, что добавится, лор, фраза для треда)
_UPGRADES = {
    1: (UPGRADE2_PRICE, f"+{MOSQUITO_CORN[0]}–{MOSQUITO_CORN[1]} 🌽 в час",
        UPGRADE2_LORE, upgraded2),
    2: (UPGRADE3_PRICE, f"+{MOSQUITO_POTATO[0]}–{MOSQUITO_POTATO[1]} 🥔 в час",
        UPGRADE3_LORE, upgraded3),
}


@router.callback_query(F.data == "biz:upgrade")
async def biz_upgrade(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    biz = await storage.get_business(tg_id, BIZ_MOSQUITO)
    if not biz:
        return await cb.answer("Сначала купи бизнес", show_alert=True)
    level = biz[1]
    if level not in _UPGRADES:
        return await cb.answer("🔨 Дальше пока некуда — комары отдыхают на лаврах холдинга",
                               show_alert=True)
    # до 2 уровня бизнесмен без тачки не готов морально
    if level == 1 and not await has_car(tg_id):
        return await cb.answer(NO_CAR_WHINE, show_alert=True)
    price, gain, _lore, _phrase = _UPGRADES[level]
    rows = [
        [InlineKeyboardButton(text=f"💰 Улучшить за {price} Z", callback_data="biz:upgrade:yes")],
        _back_row(tg_id),
    ]
    await cb.message.edit_text(
        f"⬆️ <b>Уровень {level + 1}</b>\n\n"
        f"Прибавка к продукции: {gain}.\n"
        f"Содержание вырастет до {upkeep_for(level + 1)} Z/день (зарплаты!), "
        f"зато простор отмыва — до {launder_cap_for(level + 1)} Z.\n"
        f"Цена: <b>{price} Z</b>",
        reply_markup=_kb(rows))
    await cb.answer()


@router.callback_query(F.data == "biz:upgrade:yes")
async def biz_upgrade_yes(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    biz = await storage.get_business(tg_id, BIZ_MOSQUITO)
    if not biz:
        return await cb.answer("Сначала купи бизнес", show_alert=True)
    level = biz[1]
    if level not in _UPGRADES:
        return await cb.answer("Уже на максимуме 😉", show_alert=True)
    if level == 1 and not await has_car(tg_id):
        return await cb.answer(NO_CAR_WHINE, show_alert=True)
    price, gain, lore, phrase = _UPGRADES[level]
    if not await storage.spend_zbucks(tg_id, price):
        return await cb.answer(f"Не хватает Z (нужно {price})", show_alert=True)

    new_level = level + 1
    await storage.set_business_level(tg_id, BIZ_MOSQUITO, new_level)
    biz_name = biz_display(biz[2], new_level)  # титул растёт вместе с уровнем
    await announce(bot, phrase(_mention(tg_id, cb.from_user.full_name), biz_name, price))
    rows = [_back_row(tg_id)]
    await cb.message.edit_text(
        f"{lore}\n\n🦟 <b>{biz_name}</b> теперь уровня {new_level}: {gain}.",
        reply_markup=_kb(rows))
    await cb.answer()
