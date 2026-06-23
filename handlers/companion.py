"""ZakharCompanion: профиль, баланс, заглушки разделов."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from db import storage
from keyboards import main_menu

router = Router()


@router.message(CommandStart())
async def start(msg: Message):
    profile = await storage.get_profile(msg.from_user.id)
    if not profile:
        await msg.answer(
            "Привет! Профиля в <b>ZakharCompanion</b> у тебя пока нет.\n"
            "Зайди на сервер и зарегистрируйся через приветствие в канале 😉"
        )
        return
    await msg.answer(
        f"С возвращением, <b>{profile[2]}</b>!\nБаланс: <b>{profile[3]} Z</b>",
        reply_markup=main_menu(),
    )


@router.message(Command("balance"))
async def balance(msg: Message):
    profile = await storage.get_profile(msg.from_user.id)
    if not profile:
        return await msg.answer("Сначала зарегистрируйся 😉")
    await msg.answer(f"💰 Баланс: <b>{profile[3]} Z</b>")


@router.callback_query(F.data == "menu:balance")
async def cb_balance(cb: CallbackQuery):
    profile = await storage.get_profile(cb.from_user.id)
    bal = profile[3] if profile else 0
    await cb.answer(f"💰 {bal} Z", show_alert=True)


@router.callback_query(F.data.in_({"menu:games", "menu:shop", "menu:pranks"}))
async def cb_stub(cb: CallbackQuery):
    await cb.answer("🚧 Раздел в разработке", show_alert=True)
