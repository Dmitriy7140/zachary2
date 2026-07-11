"""Работа «Шеф» (легальная): 10 блюд, угадай первое действие по рецепту.

Нужен предмет Ъ (нож). За каждое неиспорченное блюдо — 100 Z, максимум 1000.
Свойства продуктов не объясняются: игрок учится читать рецепты сам.
"""
import random
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content.chef import CHEF_POEM, RECIPES, build_round, chef_chat
from db import storage
from game.cars import flex_line
from game.taxman import grant
from keyboards import back_menu
from utils.guards import ensure_private
from utils.notify import announce
from utils.photo import show_text_menu

router = Router()

ROUNDS = 10
REWARD = 100          # Z за неиспорченное блюдо
COOLDOWN_MIN = 30

_games: dict[int, dict] = {}


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "chef:start")
async def chef_start(cb: CallbackQuery):
    """Дверь на кухню: стих (без смысла, как заповедано) и кнопка начать."""
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    rows = [
        [InlineKeyboardButton(text="🔥 К плите", callback_data="chef:begin")],
    ] + back_menu(tg_id).inline_keyboard
    # приходим с фото-экрана легалки — текст пересоздаст сообщение
    await show_text_menu(
        cb.message,
        f"👨‍🍳 <b>Шеф</b>\n\n{CHEF_POEM}\n\n"
        f"Смена: {ROUNDS} блюд по {REWARD} Z. Нужен Ъ 🔪.",
        _kb(rows))
    await cb.answer()


@router.callback_query(F.data == "chef:begin")
async def chef_begin(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    if await storage.get_item_qty(tg_id, "znak") < 1:
        return await cb.answer("🔪 Без Ъ на кухню не пускают. Купи его в магазине. "
                               "Если осмелишься.", show_alert=True)

    last = await storage.get_cooldown(tg_id, "chef")
    if last:
        elapsed = datetime.now() - datetime.fromisoformat(last)
        if elapsed < timedelta(minutes=COOLDOWN_MIN):
            left = int((timedelta(minutes=COOLDOWN_MIN) - elapsed).total_seconds())
            return await cb.answer(f"⏳ Кухня проветривается ещё {left // 60}м {left % 60}с",
                                   show_alert=True)
    await storage.set_cooldown(tg_id, "chef")

    _games[tg_id] = {
        "round": 0, "score": 0, "active": None, "correct": None,
        "recipes": random.sample(RECIPES, ROUNDS),
        "name": cb.from_user.full_name,
        "chat_id": cb.message.chat.id, "msg_id": cb.message.message_id,
    }
    await cb.answer()
    await _next_round(cb.bot, tg_id)


async def _edit(bot: Bot, g: dict, text: str, rows=None) -> None:
    try:
        await bot.edit_message_text(text, chat_id=g["chat_id"], message_id=g["msg_id"],
                                    reply_markup=_kb(rows) if rows else None)
    except Exception:
        pass


async def _next_round(bot: Bot, tg_id: int, prefix: str = "") -> None:
    g = _games.get(tg_id)
    if not g:
        return
    g["round"] += 1
    rnd = g["round"]
    if rnd > ROUNDS:
        return await _finish(bot, tg_id, prefix)

    recipe = g["recipes"][rnd - 1]
    options, correct_idx = build_round(recipe)
    g["active"] = rnd
    g["correct"] = correct_idx  # правильный ответ храним на сервере

    rows = [[InlineKeyboardButton(text=opt, callback_data=f"chef:pick:{rnd}:{i}")]
            for i, opt in enumerate(options)]
    await _edit(bot, g,
                f"{prefix}🍳 Блюдо {rnd}/{ROUNDS}\n"
                f"Поварская книга гласит:\n<i>«{recipe['text']}»</i>\n\n"
                f"С чего начнёшь?",
                rows)


@router.callback_query(F.data.startswith("chef:pick:"))
async def chef_pick(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    g = _games.get(tg_id)
    if not g:
        return await cb.answer()
    _, _, rnd_raw, idx_raw = cb.data.split(":")
    if g["active"] != int(rnd_raw):
        return await cb.answer()
    g["active"] = None

    if int(idx_raw) == g["correct"]:
        g["score"] += REWARD
        await cb.answer(f"✅ Точно! +{REWARD} Z")
        prefix = "✅ Блюдо удалось!\n\n"
    else:
        await cb.answer("❌ Испортил! Кухня недовольна.")
        prefix = "❌ Блюдо безнадёжно испорчено. Забудь его. Оно тебя — нет.\n\n"
    await _next_round(bot, tg_id, prefix)


async def _finish(bot: Bot, tg_id: int, prefix: str = "") -> None:
    g = _games.pop(tg_id, None)
    if not g:
        return
    score = g["score"]
    if score:
        await grant(bot, tg_id, score)  # легальная работа
        await storage.bump(tg_id, "chef_won", score)
    await storage.bump(tg_id, "chef_games")

    await _edit(bot, g,
                f"{prefix}🍳 <b>Смена окончена!</b>\n"
                f"Блюд не испорчено: {score // REWARD}/{ROUNDS}\n"
                f"Заработано: <b>{score} Z</b>",
                back_menu(tg_id).inline_keyboard)

    mention = hlink(g["name"], f"tg://user?id={tg_id}")
    await announce(bot, chef_chat(mention) + await flex_line(tg_id))
