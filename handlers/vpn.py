"""Нелегальная работа «Продавец VPN»: 7 клиентов, три протокола и один лысый.

Правильный протокол +300, неправильный +250 (клиент обзовётся), отказ — 0.
Продал замаскированному Вовке — взятка 500 (или всё, что есть). Раз в час.
Доход — грязный (нелегалка).
"""
import random
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content.vpn import (BRIBE, CLIENTS, INTRO, PROTO_LABELS, REWARD_GOOD, REWARD_OK,
                         busted, dodged, no_sale, sale_good, sale_ok, vpn_chat)
from db import storage
from game.cars import flex_line
from game.taxman import grant
from keyboards import back_menu
from utils.guards import ensure_private, with_owner
from utils.notify import announce
from utils.photo import show_text_menu

router = Router()

ROUNDS = 7
COOLDOWN_MIN = 60

_games: dict[int, dict] = {}


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "vpn:start")
async def vpn_start(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    rows = [
        [InlineKeyboardButton(text="🌐 Встать на угол", callback_data="vpn:begin")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", tg_id))],
    ]
    # приходим с фото-экрана нелегалки — текст пересоздаст сообщение
    await show_text_menu(cb.message, INTRO, _kb(rows))
    await cb.answer()


@router.callback_query(F.data == "vpn:begin")
async def vpn_begin(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    last = await storage.get_cooldown(tg_id, "vpn")
    if last:
        elapsed = datetime.now() - datetime.fromisoformat(last)
        if elapsed < timedelta(minutes=COOLDOWN_MIN):
            left = int((timedelta(minutes=COOLDOWN_MIN) - elapsed).total_seconds())
            return await cb.answer(f"⏳ На углу пока палевно. Вернись через "
                                   f"{left // 60}м {left % 60}с", show_alert=True)
    await storage.set_cooldown(tg_id, "vpn")

    _games[tg_id] = {
        "round": 0, "score": 0, "busted": False, "active": None, "kind": None,
        "clients": random.sample(CLIENTS, ROUNDS),
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

    text, kind = g["clients"][rnd - 1]
    g["active"] = rnd
    g["kind"] = kind  # категория клиента — на сервере, не в callback_data

    rows = [
        [InlineKeyboardButton(text=PROTO_LABELS["wireguard"],
                              callback_data=f"vpn:sell:{rnd}:wireguard"),
         InlineKeyboardButton(text=PROTO_LABELS["vless"],
                              callback_data=f"vpn:sell:{rnd}:vless"),
         InlineKeyboardButton(text=PROTO_LABELS["hysteria"],
                              callback_data=f"vpn:sell:{rnd}:hysteria")],
        [InlineKeyboardButton(text="🚫 Не продавать", callback_data=f"vpn:sell:{rnd}:skip")],
    ]
    await _edit(bot, g,
                f"{prefix}🌐 Клиент {rnd}/{ROUNDS}\n\n<i>{text}</i>\n\nЧто впариваем?",
                rows)


@router.callback_query(F.data.startswith("vpn:sell:"))
async def vpn_sell(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    g = _games.get(tg_id)
    if not g:
        return await cb.answer()
    _, _, rnd_raw, choice = cb.data.split(":")
    if g["active"] != int(rnd_raw):
        return await cb.answer()
    g["active"] = None
    kind = g["kind"]

    if kind == "vovka":
        if choice == "skip":
            prefix = dodged() + "\n\n"
            await cb.answer("🕶 Пронесло...")
        else:
            # пиздец: взятка 500 или всё, что наскребётся
            profile = await storage.get_profile(tg_id)
            available = (profile[3] if profile else 0) - await storage.hidden_now(tg_id)
            take = min(BRIBE, max(0, available))
            if take > 0:
                await storage.spend_zbucks(tg_id, take)
            g["busted"] = True
            await storage.bump(tg_id, "vpn_busted")
            prefix = busted(take if take else BRIBE) + "\n\n"
            await cb.answer("💥 Это был ОН", show_alert=True)
    elif choice == "skip":
        prefix = no_sale() + "\n\n"
        await cb.answer()
    elif choice == kind:
        g["score"] += REWARD_GOOD
        prefix = sale_good(REWARD_GOOD) + "\n\n"
        await cb.answer(f"✅ +{REWARD_GOOD} Z")
    else:
        g["score"] += REWARD_OK
        prefix = sale_ok(REWARD_OK) + "\n\n"
        await cb.answer(f"💸 +{REWARD_OK} Z")

    await _next_round(bot, tg_id, prefix)


async def _finish(bot: Bot, tg_id: int, prefix: str = "") -> None:
    g = _games.pop(tg_id, None)
    if not g:
        return
    score = g["score"]
    if score:
        await grant(bot, tg_id, score, dirty=True)  # барыжный доход — грязный
        await storage.bump(tg_id, "vpn_won", score)
    await storage.bump(tg_id, "vpn_games")

    tail = "\n💥 Минус взятка лысому." if g["busted"] else ""
    await _edit(bot, g,
                f"{prefix}🌐 <b>Смена на углу окончена!</b>\n"
                f"Наторговал: <b>{score} Z</b> (грязными){tail}",
                back_menu(tg_id).inline_keyboard)

    mention = hlink(g["name"], f"tg://user?id={tg_id}")
    await announce(bot, vpn_chat(mention, score, g["busted"]) + await flex_line(tg_id))
