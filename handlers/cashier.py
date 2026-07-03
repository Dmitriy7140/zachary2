"""Мини-игра «Кассир» (легальная работа). 30 раундов, раз в 30 мин."""
import asyncio
import random
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content.cashier import BAD, GOOD, zhmyzhko
from db import storage
from game.cashier import (COOLDOWN_MIN, GALYA_BONUS, GALYA_TIME, LEVEL_NAMES, OTMENA_CHANCE,
                          ROUNDS, ZHMYZHKO_CHANCE, level)
from game.taxman import grant
from keyboards import back_menu
from utils.guards import ensure_private
from utils.notify import announce

router = Router()

_games: dict[int, dict] = {}
_bg: set = set()


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


def _reward(lvl: str) -> int:
    return random.randint(2, 6) if lvl == "senior" else random.randint(1, 3)


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "cashier:start")
async def cashier_start(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    last = await storage.get_cooldown(tg_id, "cashier")
    if last:
        elapsed = datetime.now() - datetime.fromisoformat(last)
        if elapsed < timedelta(minutes=COOLDOWN_MIN):
            left = int((timedelta(minutes=COOLDOWN_MIN) - elapsed).total_seconds())
            return await cb.answer(f"⏳ Перерыв ещё {left // 60}м {left % 60}с", show_alert=True)
    await storage.set_cooldown(tg_id, "cashier")

    games = await storage.player_stat(tg_id, "cashier_games")
    _games[tg_id] = {
        "round": 0, "score": 0, "picks": 0, "level": level(games), "active": None, "kind": None,
        "good": None, "timeout": None, "name": cb.from_user.full_name,
        "chat_id": cb.message.chat.id, "msg_id": cb.message.message_id,
    }
    await cb.answer()
    await _next_round(cb.bot, tg_id)


async def _edit(bot: Bot, state: dict, text: str, rows) -> None:
    try:
        await bot.edit_message_text(text, chat_id=state["chat_id"], message_id=state["msg_id"],
                                    reply_markup=_kb(rows))
    except Exception:
        pass


async def _next_round(bot: Bot, tg_id: int) -> None:
    state = _games.get(tg_id)
    if not state:
        return
    state["round"] += 1
    rnd = state["round"]
    if rnd > ROUNDS:
        return await _finish(bot, tg_id)
    state["active"] = rnd

    if random.random() < OTMENA_CHANCE:
        state["kind"] = "otmena"
        lvl = state["level"]
        if lvl == "junior":
            body = "🚨 <b>ОТМЕНА!</b>\nНадо срочно позвать Галю!"
            label = "ГАЛЯ!!"
        else:
            body = "🚨 <b>ОТМЕНА!</b>\nВы Галя — надо отменить!"
            label = "Отменить"
        await _edit(bot, state, f"🛒 Раунд {rnd}/{ROUNDS}\n\n{body}\n(успей за {GALYA_TIME[lvl]} сек!)",
                    [[InlineKeyboardButton(text=label, callback_data=f"cash:galya:{rnd}")]])
        state["timeout"] = asyncio.create_task(_otmena_timeout(bot, tg_id, rnd, GALYA_TIME[lvl]))
    else:
        state["kind"] = "normal"
        good = random.random() < 0.5
        state["good"] = good
        item = random.choice(GOOD if good else BAD)
        await _edit(bot, state, f"🛒 Раунд {rnd}/{ROUNDS}\nНа ленте: <b>{item}</b>\nПикать?",
                    [[InlineKeyboardButton(text="✅ Пикнуть", callback_data=f"cash:pick:{rnd}"),
                      InlineKeyboardButton(text="⛔ Пропустить", callback_data=f"cash:skip:{rnd}")]])


@router.callback_query(F.data.startswith("cash:pick:"))
async def cash_pick(cb: CallbackQuery):
    await _resolve(cb, picked=True)


@router.callback_query(F.data.startswith("cash:skip:"))
async def cash_skip(cb: CallbackQuery):
    await _resolve(cb, picked=False)


async def _resolve(cb: CallbackQuery, picked: bool) -> None:
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    state = _games.get(tg_id)
    if not state:
        return await cb.answer()
    rnd = int(cb.data.split(":")[2])
    if state["active"] != rnd or state["kind"] != "normal":
        return await cb.answer()
    state["active"] = None

    correct = (picked == state["good"])  # пикнул хорошее ИЛИ пропустил плохое
    if correct:
        amt = _reward(state["level"])
        state["score"] += amt
        if picked:
            state["picks"] += 1  # засчитываем именно пикнутый товар
        await cb.answer(f"✅ +{amt} Z")
    else:
        amt = random.randint(1, 3)
        state["score"] -= amt
        if random.random() < ZHMYZHKO_CHANCE:
            await cb.answer(zhmyzhko(amt), show_alert=True)
        else:
            await cb.answer(f"❌ штраф −{amt} Z")
    await _next_round(cb.bot, tg_id)


@router.callback_query(F.data.startswith("cash:galya:"))
async def cash_galya(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    state = _games.get(tg_id)
    if not state:
        return await cb.answer()
    rnd = int(cb.data.split(":")[2])
    if state["active"] != rnd or state["kind"] != "otmena":
        return await cb.answer()
    state["active"] = None
    if state.get("timeout"):
        state["timeout"].cancel()
    bonus = GALYA_BONUS[state["level"]]
    state["score"] += bonus
    await cb.answer(f"🎉 Успел! +{bonus} Z")
    await _next_round(cb.bot, tg_id)


async def _otmena_timeout(bot: Bot, tg_id: int, rnd: int, secs: int) -> None:
    try:
        await asyncio.sleep(secs)
    except asyncio.CancelledError:
        return
    state = _games.get(tg_id)
    if not state or state["active"] != rnd:
        return
    state["active"] = None
    _spawn(_next_round(bot, tg_id))


async def _finish(bot: Bot, tg_id: int) -> None:
    state = _games.pop(tg_id, None)
    if not state:
        return
    payout = max(0, state["score"])
    honest = await storage.is_honest(tg_id)
    if honest:
        payout = int(payout * 1.1)  # бонус «Честного человека»
    picks = state["picks"]
    if payout:
        await grant(bot, tg_id, payout)
        await storage.bump(tg_id, "cashier_won", payout)
    if picks:
        await storage.bump(tg_id, "cashier_picks", picks)
    await storage.bump(tg_id, "cashier_games")

    games = await storage.player_stat(tg_id, "cashier_games")
    bonus = " (+10% Честный человек 🎖)" if honest else ""
    text = (f"🛒 <b>Смена окончена!</b>\nЗаработано: <b>{payout} Z</b>{bonus}\n"
            f"Пикнуто товаров: {picks}\nСмен отработано: {games}\nРанг: {LEVEL_NAMES[level(games)]}")
    if state["level"] == "junior" and level(games) == "senior":
        text += f"\n\n🎉 Повышение до Старшего кассира! ЗП теперь ×2."
    await _edit(bot, state, text, back_menu(tg_id).inline_keyboard)

    mention = hlink(state["name"], f"tg://user?id={tg_id}")
    await announce(bot, f"🛒 {mention} отработал смену кассиром: заработал <b>{payout} Z</b>, "
                        f"пикнул {picks} товаров.")
