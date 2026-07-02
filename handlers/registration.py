"""Регистрация: заявка (кнопка в треде ИЛИ /register) -> подтверждение админом."""
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.markdown import hlink

from config import config
from db import storage
from keyboards import approve_kb

router = Router()


class RegStates(StatesGroup):
    nick = State()


def _valid_nick(nick: str) -> bool:
    return bool(nick) and len(nick) <= 16 and all(c.isalnum() or c == "_" for c in nick)


@router.message(Command("register", "link"))
async def cmd_register(msg: Message, command: CommandObject, state: FSMContext, bot: Bot):
    """Привязать ник, не заходя на сервер. /register [ник] или интерактивно."""
    if await storage.get_profile(msg.from_user.id):
        return await msg.answer("У тебя уже есть профиль 😉 Жми /start.")
    nick = (command.args or "").strip()
    if nick:
        return await _submit(msg, nick, bot)
    await state.set_state(RegStates.nick)
    await msg.answer("Как тебя зовут в Minecraft? Напиши свой ник одним сообщением 👇")


@router.message(RegStates.nick)
async def reg_nick(msg: Message, state: FSMContext, bot: Bot):
    await state.clear()
    nick = (msg.text or "").strip()
    if nick.startswith("/"):
        return await msg.answer("Отменено. Напиши /register, когда будешь готов.")
    await _submit(msg, nick, bot)


async def _submit(msg: Message, nick: str, bot: Bot) -> None:
    if not _valid_nick(nick):
        return await msg.answer(
            "Ник какой-то неправильный (буквы, цифры, _, до 16 символов). "
            "Попробуй заново: /register"
        )
    if await storage.get_profile(msg.from_user.id):
        return await msg.answer("У тебя уже есть профиль 😉")
    link = hlink(str(msg.from_user.id), f"tg://user?id={msg.from_user.id}")
    await bot.send_message(
        config.admin_id,
        f"Зарегистрировать пользователя {link} как <b>{nick}</b>? (заявка через /register)",
        reply_markup=approve_kb(msg.from_user.id, nick),
    )
    await msg.answer(f"📨 Заявка на ник <b>{nick}</b> отправлена. Жди подтверждения 🙌")


@router.callback_query(F.data.startswith("reg:"))
async def on_register_click(cb: CallbackQuery, bot: Bot):
    nick = cb.data.split(":", 1)[1]
    user = cb.from_user
    link = hlink(str(user.id), f"tg://user?id={user.id}")

    await bot.send_message(
        config.admin_id,
        f"Зарегистрировать пользователя {link} как <b>{nick}</b>?",
        reply_markup=approve_kb(user.id, nick),
    )
    await cb.answer("Заявка отправлена! Жди подтверждения 🙌", show_alert=True)

    # Удаляем приглашение из треда сразу после клика.
    try:
        await cb.message.delete()
    except Exception:
        pass  # сообщение могло устареть (>48ч) или уже удалено


@router.callback_query(F.data.startswith("approve:"))
async def on_approve(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id != config.admin_id:
        return await cb.answer("Не для тебя 😈", show_alert=True)

    _, tg_id_raw, nick = cb.data.split(":", 2)
    tg_id = int(tg_id_raw)

    if await storage.create_profile(tg_id, None, nick):
        # Поздравление — в тред, а не в личку админу.
        await bot.send_message(
            chat_id=config.channel_id,
            message_thread_id=config.thread_id or None,
            text=f"🎉 <b>{nick}</b> теперь в <b>ZakharCompanion</b>! Добро пожаловать в банду 💰",
        )
        # Короткий ответ админу, чтобы кнопки заявки погасли.
        await cb.message.edit_text(f"✅ {nick} зарегистрирован (tg <code>{tg_id}</code>).")
        # Личное уведомление самому игроку (если он писал боту).
        try:
            await bot.send_message(
                tg_id,
                f"🎉 Твой профиль в <b>ZakharCompanion</b> создан!\n"
                f"Ник: <b>{nick}</b>\nБаланс: <b>0 Z</b>\n\n"
                f"Жми /start — там мини-игры и магазин 💰",
            )
        except Exception:
            pass  # пользователь не начинал диалог с ботом
    else:
        await cb.message.edit_text(f"⚠️ {nick} или этот пользователь уже зарегистрирован.")
    await cb.answer()


@router.callback_query(F.data.startswith("reject:"))
async def on_reject(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id != config.admin_id:
        return await cb.answer("Не для тебя 😈", show_alert=True)

    _, tg_id_raw, nick = cb.data.split(":", 2)
    await cb.message.edit_text(f"❌ Заявка {nick} отклонена.")
    try:
        await bot.send_message(int(tg_id_raw), "Заявку на регистрацию отклонили 😔")
    except Exception:
        pass
    await cb.answer()
