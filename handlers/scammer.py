"""Мини-игра «Телефонный мошенник» (нелегальная работа). Нужен телефон."""
import random
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.markdown import hlink

from content.scammer import CHARACTERS, hint, scam_chat
from db import storage
from game.cars import flex_line
from game.scammer import ATTEMPTS, COOLDOWN_MIN, ROUNDS, WINDOW, WINDOW_CROSS, reward
from game.taxman import grant
from keyboards import back_menu
from utils.guards import ensure_private
from utils.notify import announce

router = Router()
_games: dict[int, dict] = {}


class ScamStates(StatesGroup):
    attempt = State()


@router.callback_query(F.data == "scammer:start")
async def scammer_start(cb: CallbackQuery, state: FSMContext, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    if (await storage.get_item_qty(tg_id, "samsung") < 1
            and await storage.get_item_qty(tg_id, "iphone") < 1):
        return await cb.answer("📱 Нужен телефон — купи Айфон или Самсунг в магазине", show_alert=True)

    last = await storage.get_cooldown(tg_id, "scammer")
    if last:
        elapsed = datetime.now() - datetime.fromisoformat(last)
        if elapsed < timedelta(minutes=COOLDOWN_MIN):
            left = int((timedelta(minutes=COOLDOWN_MIN) - elapsed).total_seconds())
            return await cb.answer(f"⏳ Телефон разряжается, ещё {left // 60}м {left % 60}с", show_alert=True)
    await storage.set_cooldown(tg_id, "scammer")

    window = WINDOW_CROSS if await storage.get_item_qty(tg_id, "cross") > 0 else WINDOW
    _games[tg_id] = {
        "round": 0, "score": 0, "chars": random.sample(list(CHARACTERS), ROUNDS),
        "name": cb.from_user.full_name, "chat_id": cb.message.chat.id,
        "msg_id": cb.message.message_id, "target": None, "best": None, "attempts": 0,
        "window": window,
    }
    await cb.answer()
    await _next_round(bot, tg_id, state)


async def _say(bot: Bot, g: dict, text: str, markup=None) -> None:
    # шлём НОВОЕ сообщение (не редактируем старое — оно улетает вверх)
    try:
        await bot.send_message(g["chat_id"], text, reply_markup=markup)
    except Exception:
        pass


async def _next_round(bot: Bot, tg_id: int, state: FSMContext, prefix: str = "") -> None:
    g = _games.get(tg_id)
    if not g:
        return
    g["round"] += 1
    rnd = g["round"]
    if rnd > ROUNDS:
        return await _finish(bot, tg_id, state, prefix)
    character = g["chars"][rnd - 1]
    g["target"] = CHARACTERS[character]
    g["best"] = None
    g["attempts"] = ATTEMPTS
    await state.set_state(ScamStates.attempt)
    await _say(bot, g,
                f"{prefix}📞 Раунд {rnd}/{ROUNDS}\nЗвонишь: <b>{character}</b>\n"
                f"Убеди его — напиши сообщение. Угадай нужное число слов.\n"
                f"Попыток: {ATTEMPTS}.")


@router.message(ScamStates.attempt)
async def scam_attempt(msg: Message, state: FSMContext, bot: Bot):
    tg_id = msg.from_user.id
    g = _games.get(tg_id)
    if not g:
        return await state.clear()

    character = g["chars"][g["round"] - 1]
    target = g["target"]
    count = len((msg.text or "").split())
    diff = abs(count - target)

    if diff == 0:
        r = reward(0)
        g["score"] += r
        return await _next_round(bot, tg_id, state,
                                 prefix=f"🎯 <b>{character} поверил каждому слову!</b> "
                                        f"Точное попадание — +{r} Z!\n\n")

    g["best"] = diff if g["best"] is None else min(g["best"], diff)
    g["attempts"] -= 1
    if g["attempts"] > 0:
        return await _say(bot, g,
                           f"📞 <b>{character}</b>\nТы написал: {count} слов.\n"
                           f"{hint(count, target, character)}\nПопыток осталось: {g['attempts']}.")

    r = reward(g["best"], g["window"])
    g["score"] += r
    if r > 0:
        prefix = f"💸 {character} поколебался и отдал <b>{r} Z</b> (мимо на {g['best']}).\n\n"
    else:
        prefix = f"🚫 {character} раскусил развод — 0 Z.\n\n"
    await _next_round(bot, tg_id, state, prefix=prefix)


async def _finish(bot: Bot, tg_id: int, state: FSMContext, prefix: str = "") -> None:
    g = _games.pop(tg_id, None)
    await state.clear()
    if not g:
        return
    score = g["score"]
    if score:
        await grant(bot, tg_id, score, dirty=True)  # развод по телефону — грязные
        await storage.bump(tg_id, "scam_won", score)
    await _say(bot, g, f"{prefix}📞 <b>Обзвон окончен!</b>\nНаварил: <b>{score} Z</b>",
                back_menu(tg_id))
    mention = hlink(g["name"], f"tg://user?id={tg_id}")
    # в тред — без сумм, только масштаб навара
    await announce(bot, scam_chat(mention, score) + await flex_line(tg_id))
