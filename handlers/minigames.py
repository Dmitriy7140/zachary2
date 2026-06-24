"""Мини-игры. Пока одна — «Дойка козы» (кулдаун 12ч)."""
import random
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from content import goat
from db import storage
from game.items import ITEMS
from keyboards import back_menu

router = Router()

GOAT_COOLDOWN = timedelta(hours=12)


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- меню мини-игр ---
@router.callback_query(F.data == "menu:games")
async def games_menu(cb: CallbackQuery):
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    rows = [
        [InlineKeyboardButton(text="🐐 Подоить козу", callback_data="goat:start")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:main")],
    ]
    await cb.message.edit_text("🎲 <b>Мини-игры</b>\nВыбери забаву:", reply_markup=_kb(rows))
    await cb.answer()


# --- Дойка козы: старт ---
@router.callback_query(F.data == "goat:start")
async def goat_start(cb: CallbackQuery):
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    last = await storage.get_cooldown(tg_id, "goat")
    if last:
        elapsed = datetime.now() - datetime.fromisoformat(last)
        if elapsed < GOAT_COOLDOWN:
            left = GOAT_COOLDOWN - elapsed
            h, m = divmod(int(left.total_seconds()) // 60, 60)
            return await cb.answer(f"⏳ Коза отдыхает. Приходи через {h}ч {m}м", show_alert=True)

    await storage.set_cooldown(tg_id, "goat")
    rows = [[
        InlineKeyboardButton(text="👈 Левая", callback_data="goat:r1:left"),
        InlineKeyboardButton(text="Правая 👉", callback_data="goat:r1:right"),
    ]]
    await cb.message.edit_text(
        "🐐 Перед вами коза. С какой титьки начнём?", reply_markup=_kb(rows)
    )
    await cb.answer()


# --- Раунд 1: выбор титьки ---
@router.callback_query(F.data.startswith("goat:r1:"))
async def goat_round1(cb: CallbackQuery):
    tg_id = cb.from_user.id
    await storage.add_zbucks(tg_id, 20)

    if random.random() < 0.5:  # неверная титька — игра заканчивается
        await cb.message.edit_text(f"{goat.pasha()}\n\n💰 +20 Z", reply_markup=back_menu())
        return await cb.answer()

    # верная титька — раунд 2
    rows = [[InlineKeyboardButton(text=goat.OPTION_LABELS[o], callback_data=f"goat:r2:{o}")]
            for o in ("1", "2", "3")]
    await cb.message.edit_text(f"💰 +20 Z\n\n{goat.ROUND2_INTRO}", reply_markup=_kb(rows))
    await cb.answer()


# --- Раунд 2 (+ авто-раунд 3) ---
@router.callback_query(F.data.startswith("goat:r2:"))
async def goat_round2(cb: CallbackQuery):
    tg_id = cb.from_user.id
    opt = cb.data.split(":")[2]

    if random.random() >= goat.SUCCESS_CHANCE.get(opt, 0):
        # провал — игра заканчивается, третьего раунда нет
        await storage.add_zbucks(tg_id, 10)
        await cb.message.edit_text(f"{goat.FAIL[opt]}\n\n💰 +10 Z", reply_markup=back_menu())
        return await cb.answer()

    # успех — +50 и только теперь раунд 3
    await storage.add_zbucks(tg_id, 50)
    round3 = await _round3(tg_id)
    await cb.message.edit_text(
        f"{goat.success(opt)}\n\n💰 +50 Z\n\n———\n{round3}", reply_markup=back_menu()
    )
    await cb.answer()


async def _round3(tg_id: int) -> str:
    """Третий раунд: зависит от наличия Ведра."""
    if await storage.get_item_qty(tg_id, "bucket") > 0:
        cans = await storage.get_item_qty(tg_id, "milk_can")
        if cans >= ITEMS["milk_can"].max_qty:
            await storage.add_zbucks(tg_id, 20)
            return f"{goat.ROUND3_BUCKET_FULL}\n💰 +20 Z"
        await storage.add_item(tg_id, "milk_can", 1, ITEMS["milk_can"].max_qty)
        return goat.ROUND3_BUCKET
    await storage.add_zbucks(tg_id, 20)
    return f"{goat.ROUND3_NO_BUCKET}\n💰 +20 Z"
