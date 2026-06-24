"""ZakharCompanion: профиль, баланс, заглушки разделов."""
import asyncio

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from content.ranks import rank
from db import storage
from game.leveling import xp_for_level
from keyboards import main_menu
from mc.rcon import online_players
from utils.cleanup import delete_later
from utils.guards import ensure_owner

router = Router()


async def _temp(msg: Message, text: str, **kw) -> None:
    """Ответить и через минуту удалить и ответ, и саму команду."""
    sent = await msg.answer(text, **kw)
    delete_later(msg.bot, msg.chat.id, msg.message_id)
    delete_later(msg.bot, sent.chat.id, sent.message_id)


def _profile_card(profile: tuple) -> str:
    """Карточка профиля: ник, звание, прогресс опыта, баланс."""
    _, _, nick, zbucks, xp, level = profile
    here = xp - xp_for_level(level)              # опыт внутри текущего уровня
    need = xp_for_level(level + 1) - xp_for_level(level)  # цена следующего уровня
    return (
        f"👤 <b>{nick}</b>\n"
        f"⭐ Уровень <b>{level}</b> — {rank(level)}\n"
        f"✨ Опыт: {here} / {need} (до уровня {level + 1})\n"
        f"💰 Баланс: <b>{zbucks} Z</b>"
    )


@router.message(Command("online"))
async def online(msg: Message):
    """Живой тест RCON: показать, кто сейчас на сервере."""
    try:
        players = await online_players()
        if not players:
            text = "🌙 На сервере сейчас никого."
        else:
            lst = "\n".join(f"• {p}" for p in players)
            text = f"🎮 Онлайн ({len(players)}):\n{lst}"
    except asyncio.TimeoutError:
        text = "⌛ Сервер не ответил (RCON-таймаут)."
    except Exception as e:
        text = f"⚠️ Не удалось связаться с сервером:\n<code>{e}</code>"
    await _temp(msg, text)


@router.message(CommandStart())
async def start(msg: Message):
    delete_later(msg.bot, msg.chat.id, msg.message_id)  # убрать саму /start
    profile = await storage.get_profile(msg.from_user.id)
    if not profile:
        await msg.answer(
            "Привет! Профиля в <b>ZakharCompanion</b> у тебя пока нет.\n"
            "Зайди на сервер и зарегистрируйся через приветствие в канале 😉"
        )
        return
    await msg.answer(_profile_card(profile), reply_markup=main_menu(msg.from_user.id))


@router.callback_query(F.data.startswith("menu:main:"))
async def cb_main(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    profile = await storage.get_profile(cb.from_user.id)
    if not profile:
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await cb.message.edit_text(_profile_card(profile), reply_markup=main_menu(cb.from_user.id))
    await cb.answer()
