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

router = Router()


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
    except asyncio.TimeoutError:
        await msg.answer("⌛ Сервер не ответил (RCON-таймаут). Порт открыт, но обмен завис — проверь пароль/бинд.")
        return
    except Exception as e:
        await msg.answer(f"⚠️ Не удалось связаться с сервером:\n<code>{e}</code>")
        return

    if not players:
        await msg.answer("🌙 На сервере сейчас никого.")
    else:
        lst = "\n".join(f"• {p}" for p in players)
        await msg.answer(f"🎮 Онлайн ({len(players)}):\n{lst}")


@router.message(CommandStart())
async def start(msg: Message):
    profile = await storage.get_profile(msg.from_user.id)
    if not profile:
        await msg.answer(
            "Привет! Профиля в <b>ZakharCompanion</b> у тебя пока нет.\n"
            "Зайди на сервер и зарегистрируйся через приветствие в канале 😉"
        )
        return
    await msg.answer(_profile_card(profile), reply_markup=main_menu())


@router.message(Command("balance"))
async def balance(msg: Message):
    profile = await storage.get_profile(msg.from_user.id)
    if not profile:
        return await msg.answer("Сначала зарегистрируйся 😉")
    await msg.answer(f"💰 Баланс: <b>{profile[3]} Z</b>")


@router.callback_query(F.data == "menu:main")
async def cb_main(cb: CallbackQuery):
    profile = await storage.get_profile(cb.from_user.id)
    if not profile:
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await cb.message.edit_text(_profile_card(profile), reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data == "menu:balance")
async def cb_balance(cb: CallbackQuery):
    profile = await storage.get_profile(cb.from_user.id)
    bal = profile[3] if profile else 0
    await cb.answer(f"💰 {bal} Z", show_alert=True)


@router.callback_query(F.data == "menu:pranks")
async def cb_stub(cb: CallbackQuery):
    await cb.answer("🚧 Раздел в разработке", show_alert=True)
