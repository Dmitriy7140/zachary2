"""Регистрация: игрок жмёт кнопку -> заявка тебе в личку -> подтверждение."""
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.markdown import hlink

from config import config
from db import storage
from keyboards import approve_kb

router = Router()


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


@router.callback_query(F.data.startswith("approve:"))
async def on_approve(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id != config.admin_id:
        return await cb.answer("Не для тебя 😈", show_alert=True)

    _, tg_id_raw, nick = cb.data.split(":", 2)
    tg_id = int(tg_id_raw)

    if await storage.create_profile(tg_id, None, nick):
        await cb.message.edit_text(f"✅ {nick} зарегистрирован (tg <code>{tg_id}</code>).")
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
