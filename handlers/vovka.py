"""Мини-игра «Бей Вовку»: за 4 сек ткнуть лысого 👨‍🦲 среди волосатых 🧑‍🦰.

5 раундов, попытка 20 Z, кулдаун 30 мин. За победный раунд 5 Z, но если
побед меньше 3 — выигрыша нет. Играть только в личке, итог пишем в тред.
"""
import asyncio
import logging
import random
import time
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from db import storage
from keyboards import back_menu
from utils.guards import ensure_private
from utils.notify import announce

log = logging.getLogger(__name__)
router = Router()

ROUNDS = 5
WIN_REWARD = 5
WIN_THRESHOLD = 3
COST = 0
COOLDOWN = timedelta(seconds=3)
ROUND_TIME = 5   # сек на реакцию (бездействие = проигрыш раунда)
GAP = 2          # сек между раундами
MIN_REACTION = 0.4  # сек: клик быстрее — это бот, засчитываем промах

BALD = "👨‍🦲"
HAIRY = "🧑‍🦰"

# Пул «жертв»: каждый раунд один тип — цель (уникальный), другой — фон (8 штук).
TYPES = [
    ("👨‍🦲", "лысого"),
    ("🧑‍🦰", "рыжего"),
    ("🤓", "ботаника"),
    ("🧔", "бородатого"),
    ("👮", "мента"),
    ("🤡", "клоуна"),
]

_games: dict[int, dict] = {}   # tg_id -> состояние партии
_bg: set = set()               # ссылки на фоновые задачи


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


@router.callback_query(F.data == "vovka:start")
async def vovka_start(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    profile = await storage.get_profile(tg_id)
    if not profile:
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    if tg_id in _games:
        return await cb.answer("Игра уже идёт", show_alert=True)

    last = await storage.get_cooldown(tg_id, "vovka")
    if last:
        elapsed = datetime.now() - datetime.fromisoformat(last)
        if elapsed < COOLDOWN:
            left = int((COOLDOWN - elapsed).total_seconds())
            return await cb.answer(f"⏳ Вовка отдыхает. Приходи через {left // 60}м {left % 60}с",
                                   show_alert=True)
    if COST and profile[3] < COST:
        return await cb.answer(f"Не хватает Z (попытка {COST})", show_alert=True)

    if COST:
        await storage.spend_zbucks(tg_id, COST)
    await storage.set_cooldown(tg_id, "vovka")
    _games[tg_id] = {
        "round": 0, "wins": 0, "active": None,
        "chat_id": cb.message.chat.id, "name": cb.from_user.full_name,
        "msg_id": None, "timeout": None,
    }
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer()
    _spawn(_intro_then_start(bot, tg_id))


async def _intro_then_start(bot: Bot, tg_id: int) -> None:
    state = _games.get(tg_id)
    if not state:
        return
    sent = await bot.send_message(
        state["chat_id"],
        f"🥊 <b>Бей Вовку!</b>\n\n"
        f"Каждый раунд назову, кого бить — он всегда <b>один среди одинаковых</b>.\n"
        f"Читай задание внимательно 👀\n\n"
        f"Начинаем через 5 секунд…",
    )
    await asyncio.sleep(5)
    if tg_id not in _games:
        return
    try:
        await bot.delete_message(state["chat_id"], sent.message_id)
    except Exception:
        pass
    await _start_round(bot, tg_id)


async def _start_round(bot: Bot, tg_id: int) -> None:
    state = _games.get(tg_id)
    if not state:
        return
    state["round"] += 1
    rnd = state["round"]
    if rnd > ROUNDS:
        return await _finish(bot, tg_id)

    target_pos = random.randint(0, 8)
    (t_emoji, t_label), (f_emoji, _) = random.sample(TYPES, 2)  # цель и фон — разные типы
    state["active"] = rnd
    state["bald"] = target_pos      # ответ храним на сервере, не в callback_data
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c
            row.append(InlineKeyboardButton(
                text=t_emoji if i == target_pos else f_emoji,
                callback_data=f"vovka:hit:{i}:{rnd}",  # только позиция кнопки
            ))
        rows.append(row)

    sent = await bot.send_message(
        state["chat_id"],
        f"🥊 Раунд {rnd}/{ROUNDS} — <b>бей {t_label}</b> ({t_emoji})! ⏱ {ROUND_TIME} сек",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    state["msg_id"] = sent.message_id
    state["shown_at"] = time.monotonic()   # для проверки скорости реакции
    state["timeout"] = asyncio.create_task(
        _round_timeout(bot, tg_id, rnd, state["chat_id"], sent.message_id)
    )


@router.callback_query(F.data.startswith("vovka:hit:"))
async def vovka_hit(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    state = _games.get(tg_id)
    if not state:
        return await cb.answer()
    _, _, pos_raw, rnd_raw = cb.data.split(":")
    rnd = int(rnd_raw)
    pos = int(pos_raw)
    if state.get("active") != rnd:
        return await cb.answer()  # устаревший / уже разрешённый клик

    state["active"] = None
    if state.get("timeout"):
        state["timeout"].cancel()

    # анти-бот: нечеловечески быстрый клик = промах
    too_fast = (time.monotonic() - state.get("shown_at", 0)) < MIN_REACTION
    won = (pos == state.get("bald")) and not too_fast
    if won:
        state["wins"] += 1

    if too_fast:
        result, toast = "⚡ Слишком быстро — засчитано как промах!", "⚡ Не жульничай!"
    elif won:
        result, toast = "✅ ПОПАЛ!", ""
    else:
        result, toast = "❌ Мимо!", ""
    try:
        await cb.message.edit_text(f"Раунд {rnd}/{ROUNDS}: {result}")
    except Exception:
        pass
    await cb.answer(toast)
    _spawn(_advance(bot, tg_id))


async def _round_timeout(bot: Bot, tg_id: int, rnd: int, chat_id: int, msg_id: int) -> None:
    try:
        await asyncio.sleep(ROUND_TIME)
    except asyncio.CancelledError:
        return
    state = _games.get(tg_id)
    if not state or state.get("active") != rnd:
        return
    state["active"] = None
    try:
        await bot.delete_message(chat_id, msg_id)  # через 4 сек сообщение удаляется
    except Exception:
        pass
    await asyncio.sleep(GAP)
    if tg_id in _games:
        await _start_round(bot, tg_id)


async def _advance(bot: Bot, tg_id: int) -> None:
    await asyncio.sleep(GAP)
    state = _games.get(tg_id)
    if not state:
        return
    if state.get("msg_id"):
        try:
            await bot.delete_message(state["chat_id"], state["msg_id"])
        except Exception:
            pass
    await _start_round(bot, tg_id)


async def _finish(bot: Bot, tg_id: int) -> None:
    state = _games.pop(tg_id, None)
    if not state:
        return
    wins = state["wins"]
    reward = wins * WIN_REWARD if wins >= WIN_THRESHOLD else 0
    if reward:
        await storage.add_zbucks(tg_id, reward)
        await storage.bump(tg_id, "vovka_won", reward)

    if reward:
        text = (f"🥊 Игра окончена!\nПобед: <b>{wins}/{ROUNDS}</b>\n"
                f"💰 Выигрыш: <b>+{reward} Z</b>")
    else:
        text = (f"🥊 Игра окончена!\nПобед: <b>{wins}/{ROUNDS}</b> "
                f"(нужно ≥{WIN_THRESHOLD})\nВыигрыша нет 😢")
    try:
        await bot.send_message(state["chat_id"], text, reply_markup=back_menu(tg_id))
    except Exception:
        pass

    # Итог — в общий тред.
    mention = hlink(state["name"], f"tg://user?id={tg_id}")
    if reward:
        thread_text = f"🥊 {mention} отлупил Вовку — {wins}/{ROUNDS} побед, забрал {reward} Z!"
    else:
        thread_text = f"🥊 {mention} бил Вовку, но позорно слил ({wins}/{ROUNDS})."
    await announce(bot, thread_text)
