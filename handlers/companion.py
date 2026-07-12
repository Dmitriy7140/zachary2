"""ZakharCompanion: профиль, баланс, заглушки разделов."""
import asyncio

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from content.ranks import rank
from db import storage
from game.fishing import fish_to_next_level, fishing_level
from game.leveling import xp_for_level
from keyboards import main_menu
from mc.rcon import online_players
from utils.cleanup import delete_later
from utils.guards import ensure_owner
from utils.photo import send_photo_menu, show_photo_menu

MAIN_PHOTO = "static/main.png"
MAIN_PHOTO_META = "main_photo_id"

router = Router()


async def _temp(msg: Message, text: str, **kw) -> None:
    """Ответить. В группе через минуту убрать и команду, и ответ; в личке — оставить."""
    sent = await msg.answer(text, **kw)
    if msg.chat.type != ChatType.PRIVATE:
        delete_later(msg.bot, msg.chat.id, msg.message_id)
        delete_later(msg.bot, sent.chat.id, sent.message_id)


async def _profile_card(profile: tuple) -> str:
    """Карточка профиля: ник, звание, прогресс опыта, рыбалка, баланс."""
    tg_id, _, nick, zbucks, xp, level = profile
    here = xp - xp_for_level(level)              # опыт внутри текущего уровня
    need = xp_for_level(level + 1) - xp_for_level(level)  # цена следующего уровня
    fish = await storage.player_stat(tg_id, "fish_caught")
    flvl = fishing_level(fish)
    to_next = fish_to_next_level(fish)
    fish_line = f"🎣 Рыбак: ур. <b>{flvl}</b>"
    fish_line += " (макс)" if to_next is None else f" (до след. уровня {to_next} рыб)"
    dirty = await storage.get_dirty(tg_id)
    dirty_line = f"🧾 Из них грязные бабки: <b>{dirty} Z</b>"
    if dirty:
        dirty_line += " — холщовый еблет уже принюхивается"
    se = "✅ оформлена" if await storage.is_self_employed(tg_id) else "❌ нет"
    return (
        f"👤 <b>{nick}</b>\n"
        f"⭐ Уровень <b>{level}</b> — {rank(level)}\n"
        f"✨ Опыт: {here} / {need} (до уровня {level + 1})\n"
        f"{fish_line}\n"
        f"📱 Самозанятость: {se}\n"
        f"💰 Всего денег: <b>{zbucks} Z</b>\n"
        f"{dirty_line}"
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
    if msg.chat.type != ChatType.PRIVATE:
        delete_later(msg.bot, msg.chat.id, msg.message_id)  # в группе убрать /start
    profile = await storage.get_profile(msg.from_user.id)
    if not profile:
        await msg.answer(
            "Привет! Профиля в <b>ZakharCompanion</b> у тебя пока нет.\n"
            "Привяжи ник командой /register — или зайди на сервер "
            "и зарегистрируйся через приветствие в канале 😉"
        )
        return
    await send_photo_menu(msg, MAIN_PHOTO, MAIN_PHOTO_META,
                          await _profile_card(profile),
                          main_menu(msg.from_user.id))


@router.callback_query(F.data.startswith("menu:main:"))
async def cb_main(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    profile = await storage.get_profile(cb.from_user.id)
    if not profile:
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await show_photo_menu(cb.message, MAIN_PHOTO, MAIN_PHOTO_META,
                          await _profile_card(profile),
                          main_menu(cb.from_user.id))
    await cb.answer()
