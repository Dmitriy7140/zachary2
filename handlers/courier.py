"""Работа «Курьер» (легальная): пеший или на «Велосипеде Братан». Нужен телефон."""
import random
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content.courier import DIR_LABELS, PARABLES, bratan
from db import storage
from game.cars import flex_line
from game.courier import (BIKE_REWARD, BRATAN_CHANCE, COOLDOWN_MIN, FOOT_REWARD, IPHONE_FAIL,
                          IPHONE_GLITCH, ROUNDS)
from game.taxman import grant
from keyboards import back_menu
from utils.guards import ensure_private, with_owner
from utils.notify import announce

router = Router()
_games: dict[int, dict] = {}


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "courier:menu")
async def courier_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    has_bike = await storage.get_item_qty(tg_id, "bike") > 0
    bike_label = "🚲 Вело-курьер (50 Z/точку)" if has_bike else "🚲 Вело-курьер (нужен Велосипед Братан)"
    rows = [
        [InlineKeyboardButton(text="🚶 Пеший курьер (30 Z/точку)", callback_data="courier:start:foot")],
        [InlineKeyboardButton(text=bike_label, callback_data="courier:start:bike")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=with_owner("menu:work", tg_id))],
    ]
    await cb.message.edit_text(
        "🛵 <b>Курьер</b>\nНавигатор сломан и вещает притчами — угадай направление 15 раз.\n"
        "Нужен телефон (Айфон рискует отвалиться).",
        reply_markup=_kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("courier:start:"))
async def courier_start(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    mode = cb.data.split(":")[2]
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    has_sam = await storage.get_item_qty(tg_id, "samsung") > 0
    has_iph = await storage.get_item_qty(tg_id, "iphone") > 0
    if not (has_sam or has_iph):
        return await cb.answer("📱 Нужен телефон — купи Айфон или Самсунг", show_alert=True)
    if mode == "bike" and await storage.get_item_qty(tg_id, "bike") < 1:
        return await cb.answer("🚲 Нужен «Велосипед Братан» из магазина", show_alert=True)

    last = await storage.get_cooldown(tg_id, "courier")
    if last:
        elapsed = datetime.now() - datetime.fromisoformat(last)
        if elapsed < timedelta(minutes=COOLDOWN_MIN):
            left = int((timedelta(minutes=COOLDOWN_MIN) - elapsed).total_seconds())
            return await cb.answer(f"⏳ Отдых ещё {left // 60}м {left % 60}с", show_alert=True)

    # айфон-глюк: если телефон только айфон — с шансом 30% всё отваливается
    if has_iph and not has_sam and random.random() < IPHONE_GLITCH:
        await storage.set_cooldown(tg_id, "courier")
        await cb.message.edit_text(IPHONE_FAIL, reply_markup=back_menu(tg_id))
        return await cb.answer()

    await storage.set_cooldown(tg_id, "courier")
    _games[tg_id] = {
        "round": 0, "score": 0, "mode": mode,
        "reward": BIKE_REWARD if mode == "bike" else FOOT_REWARD,
        "active": None, "dir": None, "name": cb.from_user.full_name,
        "chat_id": cb.message.chat.id, "msg_id": cb.message.message_id,
    }
    await cb.answer()
    await _next_round(bot, tg_id)


async def _edit(bot: Bot, g: dict, text: str, markup=None) -> None:
    try:
        await bot.edit_message_text(text, chat_id=g["chat_id"], message_id=g["msg_id"],
                                    reply_markup=markup)
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
    text, direction = random.choice(PARABLES)
    g["dir"] = direction
    g["active"] = rnd
    rows = [[InlineKeyboardButton(text=DIR_LABELS[d], callback_data=f"courier:go:{d}:{rnd}")
             for d in ("left", "fwd", "right")]]
    bratan_line = ""
    if g["mode"] == "bike" and random.random() < BRATAN_CHANCE:
        bratan_line = f"🚲 Братан: «{bratan()}»\n\n"
    await _edit(bot, g,
                f"{prefix}{bratan_line}📍 Точка {rnd}/{ROUNDS}\nНавигатор бормочет:\n"
                f"<i>«{text}»</i>\n\nКуда рулим?",
                _kb(rows))


@router.callback_query(F.data.startswith("courier:go:"))
async def courier_go(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    g = _games.get(tg_id)
    if not g:
        return await cb.answer()
    _, _, choice, rnd_raw = cb.data.split(":")
    if g["active"] != int(rnd_raw):
        return await cb.answer()
    g["active"] = None
    correct = choice == g["dir"]
    if correct:
        g["score"] += g["reward"]
        prefix = f"✅ В точку! +{g['reward']} Z\n\n"
    else:
        prefix = f"❌ Не туда (надо было {DIR_LABELS[g['dir']]}).\n\n"
    await cb.answer("✅" if correct else "❌")
    await _next_round(bot, tg_id, prefix)


async def _finish(bot: Bot, tg_id: int, prefix: str = "") -> None:
    g = _games.pop(tg_id, None)
    if not g:
        return
    score = g["score"]
    if score:
        await grant(bot, tg_id, score)
        await storage.bump(tg_id, "courier_won", score)
    mode_name = "вело-курьером" if g["mode"] == "bike" else "пешим курьером"
    await _edit(bot, g, f"{prefix}🛵 <b>Смена окончена!</b>\nРаботал {mode_name}, "
                        f"заработал <b>{score} Z</b>.", back_menu(tg_id))
    mention = hlink(g["name"], f"tg://user?id={tg_id}")
    await announce(bot, f"🛵 {mention} отработал смену {mode_name} и наварил {score} Z."
                        + await flex_line(tg_id))
