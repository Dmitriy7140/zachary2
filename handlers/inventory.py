"""Инвентарь игрока + взаимодействие с Айфоном и Самсунгом."""
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from content.phone import iphone_butt
from db import storage
from game.items import ITEMS
from keyboards import back_menu
from utils.guards import ensure_owner, ensure_private, with_owner
from utils.notify import announce

router = Router()

IPHONE_CD_MIN = 5


class SmsStates(StatesGroup):
    text = State()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("menu:inventory:"))
async def inventory(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    items = await storage.get_inventory(tg_id)
    lines = []
    for key, qty in items.items():
        it = ITEMS.get(key)
        if not it or qty <= 0:
            continue
        lines.append(f"{it.emoji} {it.name}" + (f" ×{qty}" if it.max_qty > 1 else ""))
    body = "\n".join(lines) if lines else "пусто 🕸"

    rows = []
    # взаимодействие с телефонами — только в личке (ensure_private)
    if cb.message.chat.type == ChatType.PRIVATE:
        if items.get("iphone", 0) > 0:
            rows.append([InlineKeyboardButton(text="🍑 Засунуть Айфон в жопу", callback_data="inv:iphone")])
        if items.get("samsung", 0) > 0:
            rows.append([InlineKeyboardButton(text="✉️ Написать с Самсунга", callback_data="inv:samsung")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", tg_id))])

    await cb.message.edit_text(f"🎒 <b>Инвентарь</b>\n\n{body}", reply_markup=_kb(rows))
    await cb.answer()


# --- Айфон: засунуть в жопу ---
@router.callback_query(F.data == "inv:iphone")
async def iphone_use(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if await storage.get_item_qty(tg_id, "iphone") < 1:
        return await cb.answer("У тебя нет Айфона", show_alert=True)

    last = await storage.get_cooldown(tg_id, "iphone")
    if last:
        elapsed = datetime.now() - datetime.fromisoformat(last)
        if elapsed < timedelta(minutes=IPHONE_CD_MIN):
            left = int((timedelta(minutes=IPHONE_CD_MIN) - elapsed).total_seconds())
            return await cb.answer(f"⏳ Дай отойти, ещё {left // 60}м {left % 60}с", show_alert=True)
    await storage.set_cooldown(tg_id, "iphone")

    await storage.bump(tg_id, "iphone_butt")
    mention = hlink(cb.from_user.full_name, f"tg://user?id={tg_id}")
    await announce(bot, iphone_butt(mention))
    await cb.answer("🍑 Сделано. Тред уже осуждает.", show_alert=True)


# --- Самсунг: написать другому владельцу Самсунга ---
@router.callback_query(F.data == "inv:samsung")
async def samsung_menu(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if await storage.get_item_qty(tg_id, "samsung") < 1:
        return await cb.answer("У тебя нет Самсунга", show_alert=True)

    owners = await storage.item_owners("samsung", tg_id)
    if not owners:
        return await cb.answer("Больше ни у кого нет Самсунга 🤷", show_alert=True)
    rows = [[InlineKeyboardButton(text=f"📲 {nick}", callback_data=f"sms:to:{pid}")]
            for pid, nick in owners]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", tg_id))])
    await cb.message.edit_text("📲 <b>Самсунг</b>\nКому написать?", reply_markup=_kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("sms:to:"))
async def sms_to(cb: CallbackQuery, state: FSMContext):
    if not await ensure_private(cb):
        return
    to_id = int(cb.data.split(":")[2])
    to_profile = await storage.get_profile(to_id)
    if not to_profile or await storage.get_item_qty(to_id, "samsung") < 1:
        return await cb.answer("У него уже нет Самсунга", show_alert=True)
    await state.set_state(SmsStates.text)
    await state.update_data(to_id=to_id, chat_id=cb.message.chat.id, msg_id=cb.message.message_id)
    await cb.message.edit_text(f"📲 Пишешь <b>{to_profile[2]}</b>. Напиши текст сообщения:")
    await cb.answer()


@router.message(SmsStates.text)
async def sms_send(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    to_id = data["to_id"]

    async def finish(text: str):
        try:
            await bot.edit_message_text(text, chat_id=data["chat_id"], message_id=data["msg_id"],
                                        reply_markup=back_menu(msg.from_user.id))
        except Exception:
            await msg.answer(text, reply_markup=back_menu(msg.from_user.id))

    text = (msg.text or "").strip()[:300]
    if not text:
        return await finish("Пустое сообщение — отменено.")
    sender = hlink(msg.from_user.full_name, f"tg://user?id={msg.from_user.id}")
    try:
        await bot.send_message(to_id, f"📲 <b>Самсунг</b> — сообщение от {sender}:\n\n{text}")
    except Exception:
        return await finish("❌ Не доставлено — адресат не писал боту.")
    await storage.bump(msg.from_user.id, "sms_sent")
    await finish("✅ Сообщение отправлено с Самсунга.")
