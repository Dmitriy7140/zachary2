"""Мини-игра «Телефонный мошенник» (нелегальная работа). Нужен телефон."""
import random
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from content.scammer import CHARACTERS, hint, scam_chat
from db import storage
from game.cars import flex_line
from game.illegal_jobs import (SCAMMER_LEVEL_THRESHOLDS, SCAMMER_RANKS,
                               reward_with_rank_bonus, scammer_rank,
                               successes_to_next_level)
from game.scammer import ATTEMPTS, COOLDOWN_MIN, ROUNDS, WINDOW, WINDOW_CROSS, reward
from game.taxman import grant
from keyboards import back_menu
from utils.guards import ensure_private, with_owner
from utils.notify import announce
from utils.photo import show_text_menu

router = Router()
_games: dict[int, dict] = {}


class ScamStates(StatesGroup):
    attempt = State()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "scammer:menu")
async def scammer_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    successes = await storage.player_stat(tg_id, "scam_successes")
    level, rank = scammer_rank(successes)
    to_next = successes_to_next_level(SCAMMER_LEVEL_THRESHOLDS, successes)
    progression = []
    for index, (name, needed) in enumerate(zip(SCAMMER_RANKS, SCAMMER_LEVEL_THRESHOLDS), start=1):
        mark = "▶️" if index == level else "▪️"
        requirement = "старт" if needed == 0 else f"{needed} успешных обзвонов"
        progression.append(f"{mark} {index}. {name.name} — {requirement}")
    next_line = "Максимальный уровень." if to_next is None else f"До следующего: <b>{to_next}</b> успешных обзвонов."
    lines = [
        "📞 <b>Телефонный мошенник</b>",
        "Звони доверчивым гражданам и угадывай, сколько слов нужно сказать.",
        "",
        f"Ранг: <b>{level}. {rank.name}</b> · +{rank.bonus_pct}%",
        f"Успешных обзвонов: <b>{successes}</b> · {next_line}",
        f"Всего наварил: <b>{await storage.player_stat(tg_id, 'scam_won')} Z</b>",
        f"Лучший обзвон: <b>{await storage.player_stat(tg_id, 'scam_best_score')} Z</b> · "
        f"сеансов: <b>{await storage.player_stat(tg_id, 'scam_games')}</b>",
        "",
        "<b>Прогрессия:</b>",
        *progression,
    ]
    rows = [
        [InlineKeyboardButton(text="📞 Начать обзвон", callback_data="scammer:start")],
        [InlineKeyboardButton(text="⬅️ К нелегальным работам",
                              callback_data=with_owner("work:illegal", tg_id))],
    ]
    await show_text_menu(cb.message, "\n".join(lines), _kb(rows))
    await cb.answer()


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
        "window": window, "successful_calls": 0,
        "successes_before": await storage.player_stat(tg_id, "scam_successes"),
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


def _rank_reward(g: dict, base_reward: int) -> int:
    """Удачный звонок сразу учитывает достигнутую ступень."""
    next_successes = g["successes_before"] + g["successful_calls"] + 1
    _, rank = scammer_rank(next_successes)
    g["successful_calls"] += 1
    return reward_with_rank_bonus(base_reward, rank.bonus_pct)


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
        r = _rank_reward(g, reward(0))
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

    base_reward = reward(g["best"], g["window"])
    r = _rank_reward(g, base_reward) if base_reward else 0
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
        await storage.set_stat_max(tg_id, "scam_best_score", score)
    successes = g["successful_calls"]
    if successes:
        await storage.bump(tg_id, "scam_successes", successes)
    await storage.bump(tg_id, "scam_games")
    level, rank = scammer_rank(g["successes_before"] + successes)
    await _say(bot, g,
                f"{prefix}📞 <b>Обзвон окончен!</b>\nНаварил: <b>{score} Z</b>\n"
                f"Ранг: <b>{level}. {rank.name}</b> · +{rank.bonus_pct}%",
                back_menu(tg_id))
    mention = hlink(g["name"], f"tg://user?id={tg_id}")
    # в тред — без сумм, только масштаб навара
    await announce(bot, scam_chat(mention, score) + await flex_line(tg_id))
