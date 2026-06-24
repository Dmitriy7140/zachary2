"""Раздел «Пакости»: эффект на выбранного игрока через RCON."""
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from config import config
from content.pranks import PRANKS, prank_commands, prank_message
from db import storage
from keyboards import back_menu
from mc.rcon import online_players, rcon
from utils.cleanup import delete_later
from utils.guards import ensure_private

log = logging.getLogger(__name__)
router = Router()

LETTER_MAXLEN = 100


class LetterStates(StatesGroup):
    waiting = State()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_menu(message) -> None:
    rows = [
        [InlineKeyboardButton(text=f"{p.name} — {p.price} Z", callback_data=f"prank:{p.key}")]
        for p in PRANKS.values()
    ]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:main")])
    await message.edit_text("😈 <b>Пакости</b>\nВыбери, что устроить:", reply_markup=_kb(rows))


@router.callback_query(F.data == "menu:pranks")
async def pranks_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render_menu(cb.message)
    await cb.answer()


@router.callback_query(F.data.startswith("prank:"))
async def prank_flow(cb: CallbackQuery, bot: Bot, state: FSMContext):
    if not await ensure_private(cb):
        return
    parts = cb.data.split(":", 2)
    prank = PRANKS.get(parts[1])
    if not prank:
        return await cb.answer("Нет такой пакости", show_alert=True)

    if len(parts) == 2:
        await _choose_target(cb, prank)
    elif prank.kind == "title":
        await _ask_letter(cb, state, prank, parts[2])
    else:
        await _execute(cb, bot, prank, parts[2])


async def _choose_target(cb: CallbackQuery, prank) -> None:
    try:
        players = await online_players()
    except Exception:
        return await cb.answer("⚠️ Сервер недоступен", show_alert=True)
    if not players:
        return await cb.answer("🌙 На сервере никого — некого пакостить", show_alert=True)

    rows = [
        [InlineKeyboardButton(text=f"🎯 {nick}", callback_data=f"prank:{prank.key}:{nick}")]
        for nick in players
    ]
    rows.append([InlineKeyboardButton(text="⬅️ К пакостям", callback_data="menu:pranks")])
    await cb.message.edit_text(
        f"😈 <b>{prank.name}</b> — {prank.price} Z\nНа кого накладываем?",
        reply_markup=_kb(rows),
    )
    await cb.answer()


async def _execute(cb: CallbackQuery, bot: Bot, prank, nick: str) -> None:
    tg_id = cb.from_user.id
    profile = await storage.get_profile(tg_id)
    if not profile:
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    if profile[3] < prank.price:
        return await cb.answer(f"Не хватает Z (нужно {prank.price})", show_alert=True)

    # Сначала выполняем — если RCON упал, деньги не списываем.
    try:
        for cmd in prank_commands(prank, nick):
            await rcon(cmd)
    except Exception as e:
        log.warning("Пакость RCON упала: %s", e)
        return await cb.answer("⚠️ Сервер не ответил, деньги не списаны", show_alert=True)

    await storage.spend_zbucks(tg_id, prank.price)
    victim = await _victim_display(nick)
    buyer = _buyer(tg_id, cb.from_user.full_name)
    await _announce(bot, prank_message(prank, victim, buyer))
    await cb.answer(f"✅ {prank.name} → {nick}", show_alert=True)
    await _render_menu(cb.message)


# --- «Написать письмо»: ввод текста самим заказчиком ---
async def _ask_letter(cb: CallbackQuery, state: FSMContext, prank, nick: str) -> None:
    tg_id = cb.from_user.id
    profile = await storage.get_profile(tg_id)
    if not profile or profile[3] < prank.price:
        return await cb.answer(f"Не хватает Z (нужно {prank.price})", show_alert=True)

    await state.set_state(LetterStates.waiting)
    await state.update_data(
        nick=nick, price=prank.price,
        chat_id=cb.message.chat.id, msg_id=cb.message.message_id,
    )
    await cb.message.edit_text(
        f"✉️ <b>Написать письмо</b> для <b>{nick}</b>\n\n"
        f"Напиши текст одним сообщением (до {LETTER_MAXLEN} символов):"
    )
    await cb.answer()


@router.message(LetterStates.waiting)
async def letter_text(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    nick, price = data["nick"], data["price"]
    tg_id = msg.from_user.id

    text = (msg.text or "").strip()
    if not text or text.startswith("/"):
        return await msg.answer("Письмо отменено.")
    text = text[:LETTER_MAXLEN]
    delete_later(bot, msg.chat.id, msg.message_id)  # убрать ввод

    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    cmds = [
        f"title {nick} times 10 100 20",
        f'title {nick} title {{"text":"{safe}","color":"gold","bold":true}}',
    ]
    try:
        for c in cmds:
            await rcon(c)
    except Exception as e:
        log.warning("Письмо RCON упало: %s", e)
        return await msg.answer("⚠️ Сервер не ответил, деньги не списаны.")

    await storage.spend_zbucks(tg_id, price)
    buyer = _buyer(tg_id, msg.from_user.full_name)
    victim = await _victim_display(nick)
    await _announce(bot, f"✉️ {buyer} отправил {victim} письмо: «{text}»")

    # Вернуть меню пакостей на месте приглашения.
    try:
        await bot.edit_message_text(
            "✉️ Письмо отправлено!", chat_id=data["chat_id"], message_id=data["msg_id"],
            reply_markup=back_menu(),
        )
    except Exception:
        pass


# --- вспомогательное ---
async def _announce(bot: Bot, text: str) -> None:
    sent = await bot.send_message(
        chat_id=config.channel_id, message_thread_id=config.thread_id or None, text=text
    )
    delete_later(bot, sent.chat.id, sent.message_id, 60)


def _buyer(tg_id: int, full_name: str) -> str:
    return hlink(full_name, f"tg://user?id={tg_id}")


async def _victim_display(nick: str) -> str:
    tg_id = await storage.get_tg_id_by_nick(nick)
    return hlink(nick, f"tg://user?id={tg_id}") if tg_id else nick
