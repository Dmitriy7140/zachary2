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
from game.illegal_jobs import (VPN_LEVEL_THRESHOLDS, VPN_RANKS,
                               reward_with_rank_bonus, successes_to_next_level,
                               vpn_rank)
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
    successes = await storage.player_stat(tg_id, "vpn_successes")
    level, rank = vpn_rank(successes)
    to_next = successes_to_next_level(VPN_LEVEL_THRESHOLDS, successes)
    progression = []
    for index, (name, needed) in enumerate(zip(VPN_RANKS, VPN_LEVEL_THRESHOLDS), start=1):
        mark = "▶️" if index == level else "▪️"
        requirement = "старт" if needed == 0 else f"{needed} успешных продаж"
        progression.append(f"{mark} {index}. {name.name} — {requirement}")
    next_line = "Максимальный уровень." if to_next is None else f"До следующего: <b>{to_next}</b> успешных продаж."
    rows = [
        [InlineKeyboardButton(text="🌐 Начать смену", callback_data="vpn:begin")],
        [InlineKeyboardButton(text="⬅️ К нелегальным работам",
                              callback_data=with_owner("work:illegal", tg_id))],
    ]
    lines = [
        INTRO,
        "",
        f"Ранг: <b>{level}. {rank.name}</b> · +{rank.bonus_pct}%",
        f"Успешных продаж: <b>{successes}</b> · {next_line}",
        f"Всего наторговал: <b>{await storage.player_stat(tg_id, 'vpn_won')} Z</b>",
        f"Лучшая смена: <b>{await storage.player_stat(tg_id, 'vpn_best_score')} Z</b> · "
        f"смен: <b>{await storage.player_stat(tg_id, 'vpn_games')}</b> · "
        f"лысой поймал: <b>{await storage.player_stat(tg_id, 'vpn_busted')}</b>",
        "",
        "<b>Прогрессия:</b>",
        *progression,
    ]
    # приходим с фото-экрана нелегалки — текст пересоздаст сообщение
    await show_text_menu(cb.message, "\n".join(lines), _kb(rows))
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
        "successful_sales": 0,
        "successes_before": await storage.player_stat(tg_id, "vpn_successes"),
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


def _rank_reward(g: dict, base_reward: int) -> int:
    """Удачная продажа сразу учитывает достигнутую ступень."""
    next_successes = g["successes_before"] + g["successful_sales"] + 1
    _, rank = vpn_rank(next_successes)
    g["successful_sales"] += 1
    return reward_with_rank_bonus(base_reward, rank.bonus_pct)


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
        reward = _rank_reward(g, REWARD_GOOD)
        g["score"] += reward
        prefix = sale_good(reward) + "\n\n"
        await cb.answer(f"✅ +{reward} Z")
    else:
        reward = _rank_reward(g, REWARD_OK)
        g["score"] += reward
        prefix = sale_ok(reward) + "\n\n"
        await cb.answer(f"💸 +{reward} Z")

    await _next_round(bot, tg_id, prefix)


async def _finish(bot: Bot, tg_id: int, prefix: str = "") -> None:
    g = _games.pop(tg_id, None)
    if not g:
        return
    score = g["score"]
    if score:
        await grant(bot, tg_id, score, dirty=True)  # барыжный доход — грязный
        await storage.bump(tg_id, "vpn_won", score)
        await storage.set_stat_max(tg_id, "vpn_best_score", score)
    successes = g["successful_sales"]
    if successes:
        await storage.bump(tg_id, "vpn_successes", successes)
    await storage.bump(tg_id, "vpn_games")

    tail = "\n💥 Минус взятка лысому." if g["busted"] else ""
    level, rank = vpn_rank(g["successes_before"] + successes)
    await _edit(bot, g,
                f"{prefix}🌐 <b>Смена на углу окончена!</b>\n"
                f"Наторговал: <b>{score} Z</b> (грязными){tail}\n"
                f"Ранг: <b>{level}. {rank.name}</b> · +{rank.bonus_pct}%",
                back_menu(tg_id).inline_keyboard)

    mention = hlink(g["name"], f"tg://user?id={tg_id}")
    await announce(bot, vpn_chat(mention, score, g["busted"]) + await flex_line(tg_id))
