"""Мини-игра «Рулетка». Ставишь на цвет, угадал — ×1.5, нет — теряешь ставку.

Колесо: 🟢 зелёное 10% (зеро) · 🔴 красное 45% · ⚫ чёрное 45%.
Ставить можно на красное или чёрное. Выпало зелёное — обе ставки проигрывают.
Множитель выигрыша ×1.5 (ставка + половина). Ставка ≤ 50% баланса. Только в личке.
"""
import random

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from db import storage
from keyboards import back_menu
from utils.cleanup import delete_later
from utils.guards import ensure_private, with_owner
from utils.notify import announce

router = Router()

WHEEL = {"green": ("🟢", "ЗЕЛЁНОЕ"), "red": ("🔴", "КРАСНОЕ"), "black": ("⚫", "ЧЁРНОЕ")}
MULT = {"green": 10, "red": 1.5, "black": 1.5}  # множитель выигрыша по цвету
_rng = random.SystemRandom()  # энтропия ОС — честный независимый спин


class RouletteStates(StatesGroup):
    betting = State()


@router.callback_query(F.data == "roulette:start")
async def roulette_start(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    profile = await storage.get_profile(cb.from_user.id)
    if not profile:
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    if profile[3] < 1:
        return await cb.answer("Маловато Z для ставки 😅", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Красное (45%)", callback_data="roul:color:red"),
         InlineKeyboardButton(text="⚫ Чёрное (45%)", callback_data="roul:color:black")],
        [InlineKeyboardButton(text="🟢 Зелёное (10%, ×10)", callback_data="roul:color:green")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", cb.from_user.id))],
    ])
    await cb.message.edit_text(
        "🎰 <b>Рулетка</b>\n"
        "🟢 зелёное 10% → ×10 · 🔴 красное 45% → ×1.5 · ⚫ чёрное 45% → ×1.5\n"
        "Угадал цвет — забираешь выигрыш, нет — ставка сгорает.\n\n"
        "На какой цвет ставишь?",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("roul:color:"))
async def roulette_color(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    color = cb.data.split(":")[2]
    profile = await storage.get_profile(cb.from_user.id)
    if not profile:
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    max_bet = profile[3]
    if max_bet < 1:
        return await cb.answer("Маловато Z для ставки 😅", show_alert=True)

    emoji, name = WHEEL[color]
    await state.set_state(RouletteStates.betting)
    await state.update_data(color=color, max_bet=max_bet,
                            chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    await cb.message.edit_text(
        f"🎰 Ставка на {emoji} <b>{name}</b>\n"
        f"Баланс: <b>{profile[3]} Z</b>\n"
        f"Сколько ставишь? Можно всё — до <b>{max_bet} Z</b>.\n"
        "Напиши число одним сообщением:"
    )
    await cb.answer()


@router.message(RouletteStates.betting)
async def roulette_bet(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    tg_id = msg.from_user.id
    delete_later(bot, msg.chat.id, msg.message_id)

    async def finish(text: str):
        try:
            await bot.edit_message_text(text, chat_id=data["chat_id"], message_id=data["msg_id"],
                                        reply_markup=back_menu(tg_id))
        except Exception:
            await msg.answer(text, reply_markup=back_menu(tg_id))

    raw = (msg.text or "").strip()
    if not raw.isdigit():
        return await finish("❌ Это не число — ставка отменена.")
    bet = int(raw)
    if bet < 1 or bet > data["max_bet"]:
        return await finish(f"❌ Ставка должна быть от 1 до {data['max_bet']} Z — отменено.")
    if not await storage.spend_zbucks(tg_id, bet):
        return await finish("❌ Недостаточно Z — отменено.")

    # Спин колеса (SystemRandom + явные веса)
    wheel = _rng.choices(("green", "red", "black"), weights=(10, 45, 45))[0]
    emoji, name = WHEEL[wheel]
    bet_emoji, bet_name = WHEEL[data["color"]]

    if wheel == data["color"]:
        payout = int(bet * MULT[data["color"]])
        await storage.add_zbucks(tg_id, payout)
        line = f"Выпало {emoji} <b>{name}</b> — угадал! 🎉\nСтавка {bet} → <b>{payout} Z</b>"
        mention = hlink(msg.from_user.full_name, f"tg://user?id={tg_id}")
        await announce(bot, f"🎰 {mention} поймал {emoji} {name} в рулетке и забрал {payout} Z!")
    else:
        line = f"Выпало {emoji} <b>{name}</b> — мимо 💀\nСтавка {bet} Z сгорела (ты ставил на {bet_emoji})"

    new_balance = (await storage.get_profile(tg_id))[3]
    await finish(f"🎰 {line}\n\nБаланс: <b>{new_balance} Z</b>")
