"""Мини-игра «Бей Вовку»: за 4 сек ткнуть лысого 👨‍🦲 среди волосатых 🧑‍🦰.

5 раундов, попытка 20 Z, кулдаун 30 мин. За победный раунд 5 Z, но если
побед меньше 3 — выигрыша нет. Играть только в личке, итог пишем в тред.
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from config import config
from db import storage
from keyboards import back_menu
from utils.cleanup import delete_later
from utils.guards import ensure_private

log = logging.getLogger(__name__)
router = Router()

ROUNDS = 5
WIN_REWARD = 5
WIN_THRESHOLD = 3
COST = 20
COOLDOWN = timedelta(minutes=30)
ROUND_TIME = 4   # сек на раунд
GAP = 2          # сек между раундами

BALD = "👨‍🦲"
HAIRY = "🧑‍🦰"

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
    if profile[3] < COST:
        return await cb.answer(f"Не хватает Z (попытка {COST})", show_alert=True)

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
    await _start_round(bot, tg_id)


async def _start_round(bot: Bot, tg_id: int) -> None:
    state = _games.get(tg_id)
    if not state:
        return
    state["round"] += 1
    rnd = state["round"]
    if rnd > ROUNDS:
        return await _finish(bot, tg_id)

    bald = random.randint(0, 8)
    state["active"] = rnd
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c
            is_bald = i == bald
            row.append(InlineKeyboardButton(
                text=BALD if is_bald else HAIRY,
                callback_data=f"vovka:hit:{'b' if is_bald else 'h'}:{rnd}",
            ))
        rows.append(row)

    sent = await bot.send_message(
        state["chat_id"],
        f"🥊 Раунд {rnd}/{ROUNDS} — бей Вовку (лысого {BALD})! ⏱ 4 сек",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    state["msg_id"] = sent.message_id
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
    _, _, tag, rnd_raw = cb.data.split(":")
    rnd = int(rnd_raw)
    if state.get("active") != rnd:
        return await cb.answer()  # устаревший / уже разрешённый клик

    state["active"] = None
    if state.get("timeout"):
        state["timeout"].cancel()

    won = tag == "b"
    if won:
        state["wins"] += 1
    try:
        await cb.message.edit_text(
            f"Раунд {rnd}/{ROUNDS}: " + ("✅ ПОПАЛ!" if won else "❌ Мимо!")
        )
    except Exception:
        pass
    await cb.answer()
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
        thread_text = f"🥊 {mention} пытался бить Вовку и слил ({wins}/{ROUNDS}). {COST} Z на ветер."
    try:
        sent = await bot.send_message(
            chat_id=config.channel_id, message_thread_id=config.thread_id or None,
            text=thread_text,
        )
        delete_later(bot, sent.chat.id, sent.message_id, 60)
    except Exception:
        pass
