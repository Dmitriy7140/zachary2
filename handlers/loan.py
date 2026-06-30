"""Взять в долг: попросить у игрока сумму, он решает дать или нет. История — в тред."""
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from db import storage
from game.debts import schedule_first_nag
from utils.guards import ensure_private, with_owner
from utils.notify import announce
from utils.pagination import nav_row, page_slice

router = Router()

PAGE_SIZE = 6


class LoanStates(StatesGroup):
    amount = State()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back(owner: int):
    return _kb([[InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", owner))]])


def _mention(tg_id: int, name: str) -> str:
    return hlink(name, f"tg://user?id={tg_id}")


async def _render(message, tg_id: int, page: int = 0) -> None:
    lines = ["🤲 <b>Долг</b>", ""]
    rows = []

    debts = await storage.get_debts(tg_id)
    if debts:
        lines.append("<b>Твои долги:</b>")
        for did, lender_id, lender_nick, amount, defaulted in debts:
            flag = " ⚠️" if defaulted else ""
            lines.append(f"• {lender_nick}: {amount} Z{flag}")
            rows.append([InlineKeyboardButton(text=f"💸 Вернуть {amount} Z → {lender_nick}",
                                              callback_data=f"loan:repay:{did}")])
        lines.append("")

    players = await storage.list_other_profiles(tg_id)
    if not players:
        lines.append("Просить не у кого — других игроков нет.")
    else:
        lines.append("<b>Попросить взаймы у:</b>")
        chunk, page, pages = page_slice(players, page, PAGE_SIZE)
        for pid, nick, zb in chunk:
            rows.append([InlineKeyboardButton(text=f"{nick} ({zb} Z)", callback_data=f"loan:who:{pid}")])
        if pages > 1:
            rows.append(nav_row(page, pages, "loanpg:"))

    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", tg_id))])
    await message.edit_text("\n".join(lines), reply_markup=_kb(rows))


@router.callback_query(F.data == "menu:loan")
async def loan_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    if not await storage.get_profile(cb.from_user.id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await _render(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data.startswith("loanpg:"))
async def loan_page(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    await _render(cb.message, cb.from_user.id, int(cb.data.split(":")[1]))
    await cb.answer()


@router.callback_query(F.data.startswith("loan:who:"))
async def loan_who(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    lender_id = int(cb.data.split(":")[2])
    lender = await storage.get_profile(lender_id)
    if not lender:
        return await cb.answer("Игрок не найден", show_alert=True)
    if lender[3] < 1:
        return await cb.answer("У него нет Z 🤷", show_alert=True)

    await state.set_state(LoanStates.amount)
    await state.update_data(lender_id=lender_id, lender_nick=lender[2],
                            chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    await cb.message.edit_text(
        f"🤲 Просишь в долг у <b>{lender[2]}</b> (у него {lender[3]} Z).\n"
        f"Сколько просишь? Напиши число (не больше {lender[3]}):"
    )
    await cb.answer()


@router.message(LoanStates.amount)
async def loan_amount(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    borrower_id = msg.from_user.id
    lender_id = data["lender_id"]

    async def finish(text: str):
        try:
            await bot.edit_message_text(text, chat_id=data["chat_id"], message_id=data["msg_id"],
                                        reply_markup=_back(borrower_id))
        except Exception:
            await msg.answer(text, reply_markup=_back(borrower_id))

    lender = await storage.get_profile(lender_id)
    if not lender:
        return await finish("❌ Игрок пропал — отменено.")
    raw = (msg.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        return await finish("❌ Это не число — отменено.")
    amount = int(raw)
    if amount > lender[3]:
        return await finish(f"❌ У {lender[2]} только {lender[3]} Z — проси меньше.")

    borrower = _mention(borrower_id, msg.from_user.full_name)
    kb = _kb([[
        InlineKeyboardButton(text="✅ Дать в долг", callback_data=f"loan:yes:{borrower_id}:{amount}"),
        InlineKeyboardButton(text="❌ Отказать", callback_data=f"loan:no:{borrower_id}:{amount}"),
    ]])
    try:
        await bot.send_message(lender_id, f"🤲 {borrower} просит у тебя <b>{amount} Z</b> в долг. Дать?",
                               reply_markup=kb)
    except Exception:
        return await finish(f"❌ Не вышло связаться с {lender[2]} — он, видимо, не писал боту.")
    await finish(f"📨 Запрос на {amount} Z отправлен <b>{lender[2]}</b>. Жди ответа.")


@router.callback_query(F.data.startswith("loan:yes:"))
async def loan_yes(cb: CallbackQuery, bot: Bot):
    _, _, borrower_raw, amount_raw = cb.data.split(":")
    borrower_id, amount = int(borrower_raw), int(amount_raw)
    lender_id = cb.from_user.id

    if not await storage.spend_zbucks(lender_id, amount):
        await cb.message.edit_text("❌ У тебя уже нет столько Z — долг не выдан.")
        try:
            await bot.send_message(borrower_id, "😔 Кредитор передумал — у него не хватило Z.")
        except Exception:
            pass
        return await cb.answer()

    await storage.add_zbucks(borrower_id, amount)
    lender = _mention(lender_id, cb.from_user.full_name)
    b_profile = await storage.get_profile(borrower_id)
    borrower = _mention(borrower_id, b_profile[2] if b_profile else "Игрок")

    await storage.add_debt(borrower_id, lender_id, cb.from_user.full_name, amount,
                           datetime.now().isoformat())
    await schedule_first_nag(borrower_id)

    await cb.message.edit_text(f"✅ Ты дал в долг <b>{amount} Z</b>.")
    try:
        await bot.send_message(borrower_id,
                               f"✅ {lender} дал тебе <b>{amount} Z</b> в долг!\n"
                               f"Не забудь вернуть — иначе станешь Чепушилой 🤡")
    except Exception:
        pass
    await announce(bot, f"🤝 {lender} дал {borrower} <b>{amount} Z</b> в долг.")
    await cb.answer()


@router.callback_query(F.data.startswith("loan:repay:"))
async def loan_repay(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    did = int(cb.data.split(":")[2])
    debt = await storage.get_debt(did)
    if not debt:
        await cb.answer("Долг уже закрыт", show_alert=True)
        return await _render(cb.message, cb.from_user.id)
    _, borrower_id, lender_id, lender_nick, amount = debt
    if borrower_id != cb.from_user.id:
        return await cb.answer("Это не твой долг", show_alert=True)
    if not await storage.spend_zbucks(cb.from_user.id, amount):
        return await cb.answer(f"Не хватает Z (нужно {amount})", show_alert=True)

    await storage.add_zbucks(lender_id, amount)
    await storage.remove_debt(did)
    borrower = _mention(cb.from_user.id, cb.from_user.full_name)
    lender = _mention(lender_id, lender_nick)
    await announce(bot, f"🤝 {borrower} вернул {lender} долг <b>{amount} Z</b>. Красава!")
    await cb.answer(f"Долг {amount} Z возвращён!", show_alert=True)
    await _render(cb.message, cb.from_user.id)


@router.callback_query(F.data.startswith("loan:no:"))
async def loan_no(cb: CallbackQuery, bot: Bot):
    _, _, borrower_raw, _ = cb.data.split(":")
    borrower_id = int(borrower_raw)
    lender = _mention(cb.from_user.id, cb.from_user.full_name)
    await cb.message.edit_text("❌ Ты отказал в долге.")
    try:
        await bot.send_message(borrower_id, f"😔 {lender} отказал тебе в долге.")
    except Exception:
        pass
    await cb.answer()
