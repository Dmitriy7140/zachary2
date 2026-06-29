"""Ставки: любой создаёт событие, игроки ставят на сторону, админ резолвит."""
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from config import config
from db import storage
from game.bets import BET_WINDOW_HOURS, SIDE_NAMES, resolve_event
from utils.guards import ensure_private, with_owner
from utils.notify import announce

router = Router()

MAX_ACTIVE = 5
DESC_MAXLEN = 120
DURATIONS = (2, 5, 12)


class BetStates(StatesGroup):
    describing = State()
    choosing_duration = State()
    amount = State()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back(owner: int):
    return _kb([[
        InlineKeyboardButton(text="⬅️ К ставкам", callback_data="menu:bets"),
        InlineKeyboardButton(text="🏠 В меню", callback_data=with_owner("menu:main", owner)),
    ]])


def _left(iso: str) -> str:
    secs = max(0, int((datetime.fromisoformat(iso) - datetime.now()).total_seconds()))
    return f"{secs // 3600}ч {secs % 3600 // 60}м"


async def _render_list(message, owner: int) -> None:
    events = await storage.list_active_events()
    lines = ["🎲 <b>Ставки</b>", ""]
    rows = []
    if events:
        for eid, desc, hours, bet_close_at, status in events:
            tag = f"приём ещё {_left(bet_close_at)}" if status == "betting" else "приём закрыт, ждём итог"
            lines.append(f"#{eid} «{desc}» — {hours}ч · {tag}")
            rows.append([InlineKeyboardButton(text=f"#{eid} {desc[:25]}",
                                              callback_data=f"bets:event:{eid}")])
    else:
        lines.append("Активных ставок нет. Создай первую!")
    rows.append([InlineKeyboardButton(text="➕ Создать событие", callback_data="bets:create")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", owner))])
    await message.edit_text("\n".join(lines), reply_markup=_kb(rows))


@router.callback_query(F.data == "menu:bets")
async def bets_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render_list(cb.message, cb.from_user.id)
    await cb.answer()


# --- создание события ---
@router.callback_query(F.data == "bets:create")
async def bets_create(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    if await storage.count_active_events() >= MAX_ACTIVE:
        return await cb.answer(f"Уже {MAX_ACTIVE} активных ставок — дождись развязки", show_alert=True)
    await state.set_state(BetStates.describing)
    await state.update_data(chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    await cb.message.edit_text("🎲 Опиши событие одним сообщением (на что спорим?):")
    await cb.answer()


@router.message(BetStates.describing)
async def bets_describe(msg: Message, state: FSMContext):
    desc = (msg.text or "").strip()[:DESC_MAXLEN]
    if not desc:
        await state.clear()
        return await msg.answer("Пусто — отменено.")
    data = await state.get_data()
    await state.update_data(description=desc)
    await state.set_state(BetStates.choosing_duration)
    rows = [[InlineKeyboardButton(text=f"{h} часов", callback_data=f"bets:dur:{h}")] for h in DURATIONS]
    try:
        await msg.bot.edit_message_text(
            f"🎲 «{desc}»\nЗа сколько часов событие должно случиться?",
            chat_id=data["chat_id"], message_id=data["msg_id"], reply_markup=_kb(rows))
    except Exception:
        await msg.answer("Выбери срок:", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("bets:dur:"), BetStates.choosing_duration)
async def bets_duration(cb: CallbackQuery, state: FSMContext, bot: Bot):
    if not await ensure_private(cb):
        return
    hours = int(cb.data.split(":")[2])
    data = await state.get_data()
    await state.clear()
    desc = data.get("description")
    if not desc:
        return await cb.answer("Сессия истекла, начни заново", show_alert=True)
    if await storage.count_active_events() >= MAX_ACTIVE:
        return await cb.answer(f"Уже {MAX_ACTIVE} активных ставок", show_alert=True)

    now = datetime.now()
    bet_close = now + timedelta(hours=BET_WINDOW_HOURS)
    resolve = bet_close + timedelta(hours=hours)
    eid = await storage.create_event(cb.from_user.id, cb.from_user.full_name, desc, hours,
                                     bet_close.isoformat(), resolve.isoformat())
    creator = hlink(cb.from_user.full_name, f"tg://user?id={cb.from_user.id}")
    await announce(bot, f"🎲 {creator} открыл ставку #{eid}: «{desc}» (срок {hours}ч). "
                        f"Приём ставок {BET_WINDOW_HOURS}ч — налетай!")
    await cb.message.edit_text(
        f"🎲 Событие #{eid} создано!\n«{desc}»\nПриём ставок {BET_WINDOW_HOURS}ч.",
        reply_markup=_back(cb.from_user.id))
    await cb.answer()


# --- ставка на событие ---
@router.callback_query(F.data.startswith("bets:event:"))
async def bets_event(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    eid = int(cb.data.split(":")[2])
    ev = await storage.get_event(eid)
    if not ev:
        return await cb.answer("Событие не найдено", show_alert=True)
    _, _, _, desc, hours, bet_close_at, _, status, _ = ev
    yes_pool, no_pool = await storage.event_pools(eid)
    lines = [f"🎲 <b>Ставка #{eid}</b>", desc, "",
             f"Срок события: {hours}ч",
             f"Банк: ✅ Сыграет {yes_pool} Z / ❌ Не сыграет {no_pool} Z"]
    rows = []
    if status == "betting":
        lines.append(f"Приём ещё {_left(bet_close_at)}")
        existing = await storage.get_stake(eid, cb.from_user.id)
        if existing:
            lines.append(f"Твоя ставка: <b>{SIDE_NAMES[existing[0]]}</b> {existing[1]} Z")
        else:
            rows.append([
                InlineKeyboardButton(text="✅ Сыграет", callback_data=f"bets:side:{eid}:yes"),
                InlineKeyboardButton(text="❌ Не сыграет", callback_data=f"bets:side:{eid}:no")])
    else:
        lines.append("Приём ставок закрыт.")
    rows.append([InlineKeyboardButton(text="⬅️ К ставкам", callback_data="menu:bets")])
    await cb.message.edit_text("\n".join(lines), reply_markup=_kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("bets:side:"))
async def bets_side(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    _, _, eid_raw, side = cb.data.split(":")
    eid = int(eid_raw)
    ev = await storage.get_event(eid)
    if not ev or ev[7] != "betting":
        return await cb.answer("Приём ставок закрыт", show_alert=True)
    if await storage.get_stake(eid, cb.from_user.id):
        return await cb.answer("Ты уже поставил на это событие", show_alert=True)
    profile = await storage.get_profile(cb.from_user.id)
    if not profile or profile[3] < 1:
        return await cb.answer("Нет Z для ставки", show_alert=True)

    await state.set_state(BetStates.amount)
    await state.update_data(eid=eid, side=side, chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    await cb.message.edit_text(
        f"🎲 Ставишь на <b>{SIDE_NAMES[side]}</b> (#{eid}).\n"
        f"Баланс: {profile[3]} Z.\nСколько ставишь? Напиши число:")
    await cb.answer()


@router.message(BetStates.amount)
async def bets_amount(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    tg_id = msg.from_user.id
    eid, side = data["eid"], data["side"]

    async def finish(text: str):
        try:
            await bot.edit_message_text(text, chat_id=data["chat_id"], message_id=data["msg_id"],
                                        reply_markup=_back(tg_id))
        except Exception:
            await msg.answer(text, reply_markup=_back(tg_id))

    ev = await storage.get_event(eid)
    if not ev or ev[7] != "betting":
        return await finish("❌ Приём ставок уже закрыт.")
    if await storage.get_stake(eid, tg_id):
        return await finish("❌ Ты уже поставил на это событие.")
    raw = (msg.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        return await finish("❌ Это не число — отменено.")
    amount = int(raw)
    if not await storage.spend_zbucks(tg_id, amount):
        return await finish("❌ Не хватает Z — отменено.")
    await storage.add_stake(eid, tg_id, side, amount)
    await finish(f"✅ Ставка принята: <b>{SIDE_NAMES[side]}</b> — {amount} Z на «{ev[3]}».")


# --- развязка админом ---
@router.callback_query(F.data.startswith("bets:resolve:"))
async def bets_resolve(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id != config.admin_id:
        return await cb.answer("Не для тебя", show_alert=True)
    _, _, eid_raw, outcome = cb.data.split(":")
    eid = int(eid_raw)
    if await resolve_event(bot, eid, outcome):
        await cb.message.edit_text(f"✅ Ставка #{eid}: {SIDE_NAMES[outcome]}. Выплаты сделаны.")
        try:
            await bot.unpin_chat_message(config.admin_id, cb.message.message_id)
        except Exception:
            pass
    else:
        await cb.message.edit_text(f"Ставка #{eid} уже разрешена.")
    await cb.answer()
