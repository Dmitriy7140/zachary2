"""Инвентарь: список предметов -> подменю действий у каждого предмета."""
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hlink

from content.items_fun import (bike_ride, bike_ride_chat, milk_drink, milk_drink_chat, milk_shake,
                               milk_shake_chat, rod_wave, rod_wave_chat)
from content.phone import iphone_butt
from content.shady import iphone_trash
from content.zhmyzhko import corn_throw, egg_smash
from db import storage
from handlers.business import do_self_employ
from game.items import ITEMS
from keyboards import back_menu
from utils.guards import ensure_owner, with_owner
from utils.notify import announce
from utils.photo import show_photo_menu, show_text_menu

# то же фото, что в главном меню: переход туда-обратно меняет только подпись
MAIN_PHOTO = "static/main.png"
MAIN_PHOTO_META = "main_photo_id"

router = Router()

IPHONE_CD_MIN = 5
BIKE_INSURANCE_PCT = 5

# доступные действия по предметам: key -> [(action, label)]
ACTIONS = {
    "iphone": [("butt", "🍑 Засунуть в жопу"), ("trash", "🗑 Выбросить")],
    "samsung": [("write", "✉️ Написать сообщение")],
    "bike": [("ride", "🚲 Покататься на велике")],
    "milk_can": [("shake", "🥤 Взболтать"), ("drink", "🥛 Попить")],
    "rod": [("wave", "🎣 Помахать удочкой")],
    "egg": [("smash", "🥚 Разбить себе об лоб")],
    "corn": [("throw", "🗑 Выкинуть")],
}


class SmsStates(StatesGroup):
    text = State()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- список предметов ---
@router.callback_query(F.data.startswith("menu:inventory:"))
async def inventory(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    items = await storage.get_inventory(tg_id)
    lottery_counts = await storage.get_lottery_ticket_counts(tg_id=tg_id)
    buttons = []
    for key, qty in items.items():
        it = ITEMS.get(key)
        if not it or qty <= 0:
            continue
        label = f"{it.emoji} {it.name}" + (f" ×{qty}" if it.max_qty > 1 else "")
        buttons.append(InlineKeyboardButton(text=label,
                                            callback_data=with_owner(f"invitem:{key}", tg_id)))
    # Лотерейные билеты — виртуальные позиции из истории тиражей. Они не
    # попадают в ITEMS/inventory, поэтому не продаются и не удаляются вместе
    # с обычными предметами.
    rows = []
    if lottery_counts.active_tickets > 0:
        rows.append([InlineKeyboardButton(
            text=f"🎟 Лотерейные билетики ×{lottery_counts.active_tickets}",
            callback_data=with_owner("lot:view", tg_id),
        )])
    if lottery_counts.expired_tickets > 0:
        rows.append([InlineKeyboardButton(
            text=f"🧾 Протухшие билетики ×{lottery_counts.expired_tickets}",
            callback_data=with_owner("lot:expired", tg_id),
        )])
    # Обычные предметы — два столбца после полноширинных билетов.
    rows.extend(buttons[i:i + 2] for i in range(0, len(buttons), 2))
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", tg_id))])

    has_lottery_tickets = lottery_counts.active_tickets > 0 or lottery_counts.expired_tickets > 0
    text = (
        "🎒 <b>Инвентарь</b>\nВыбери предмет:"
        if buttons or has_lottery_tickets
        else "🎒 <b>Инвентарь</b>\n\nпусто 🕸"
    )
    await show_photo_menu(cb.message, MAIN_PHOTO, MAIN_PHOTO_META, text, _kb(rows))
    await cb.answer()


# --- подменю предмета ---
@router.callback_query(F.data.startswith("invitem:"))
async def item_menu(cb: CallbackQuery):
    if not await ensure_owner(cb):
        return
    tg_id = cb.from_user.id
    key = cb.data.split(":")[1]
    it = ITEMS.get(key)
    if not it or await storage.get_item_qty(tg_id, key) < 1:
        return await cb.answer("Этого предмета уже нет", show_alert=True)

    actions = list(ACTIONS.get(key, []))
    # Госуслуги живут в Самсунге: оформление самозанятости — только отсюда
    if key == "samsung" and not await storage.is_self_employed(tg_id):
        actions.append(("selfemploy", "📱 Оформить самозанятость — 1000 Z"))
    rows = [[InlineKeyboardButton(text=label, callback_data=with_owner(f"invact:{key}:{act}", tg_id))]
            for act, label in actions]
    rows.append([InlineKeyboardButton(text="⬅️ К инвентарю", callback_data=with_owner("menu:inventory", tg_id))])
    tail = "\nЧто делаем?" if actions else "\nС этим предметом ничего не сделать."
    await show_photo_menu(cb.message, MAIN_PHOTO, MAIN_PHOTO_META,
                          f"{it.emoji} <b>{it.name}</b>{tail}", _kb(rows))
    await cb.answer()


# --- действия ---
@router.callback_query(F.data.startswith("invact:"))
async def item_action(cb: CallbackQuery, bot: Bot):
    if not await ensure_owner(cb):
        return
    tg_id = cb.from_user.id
    _, key, action, _ = cb.data.split(":")
    if await storage.get_item_qty(tg_id, key) < 1:
        return await cb.answer("Предмета нет", show_alert=True)

    if key == "iphone" and action == "butt":
        await _iphone_butt(cb, bot, tg_id)
    elif key == "iphone" and action == "trash":
        await _iphone_trash(cb, bot, tg_id)
    elif key == "samsung" and action == "write":
        await _samsung_write(cb, tg_id)
    elif key == "samsung" and action == "selfemploy":
        if await do_self_employ(cb, bot):
            await show_text_menu(
                cb.message,
                "📱 Самозанятость оформлена через Госуслуги на Самсунге. "
                "ФНС уже потирает руки: −200 Z/день.",
                back_menu(tg_id))
    elif key == "bike" and action == "ride":
        await _bike_ride(cb, bot, tg_id)
    elif key == "milk_can" and action == "shake":
        await cb.answer(milk_shake(), show_alert=True)
        await announce(bot, milk_shake_chat(_mention(cb)))
    elif key == "milk_can" and action == "drink":
        await cb.answer(milk_drink(), show_alert=True)
        await announce(bot, milk_drink_chat(_mention(cb)))
    elif key == "rod" and action == "wave":
        await cb.answer(rod_wave(), show_alert=True)
        await announce(bot, rod_wave_chat(_mention(cb)))
    elif key == "egg" and action == "smash":
        # яйцо уничтожается, Жмыжко ругается в треде
        if not await storage.remove_item(tg_id, "egg", 1):
            return await cb.answer("Яиц уже нет", show_alert=True)
        await announce(bot, egg_smash(_mention(cb)))
        await cb.answer("🥚 Хрясь! Со лба капает. Пан Жмыжко уже в курсе.", show_alert=True)
    elif key == "corn" and action == "throw":
        # кукуруза уничтожается, тред осуждает
        if not await storage.remove_item(tg_id, "corn", 1):
            return await cb.answer("Кукурузы уже нет", show_alert=True)
        await announce(bot, corn_throw(_mention(cb)))
        await cb.answer("🌽 Выкинул. Деревня осуждает.", show_alert=True)
    else:
        await cb.answer()


def _mention(cb: CallbackQuery) -> str:
    return hlink(cb.from_user.full_name, f"tg://user?id={cb.from_user.id}")


async def _iphone_butt(cb: CallbackQuery, bot: Bot, tg_id: int) -> None:
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


async def _iphone_trash(cb: CallbackQuery, bot: Bot, tg_id: int) -> None:
    if not await storage.remove_item(tg_id, "iphone", 1):
        return await cb.answer("Айфона уже нет", show_alert=True)
    await announce(bot, iphone_trash(_mention(cb)))
    await show_text_menu(
        cb.message,
        "🗑 Айфон отправился в мусорку. Жопа снова в строю — пятая тысяча влезет.",
        back_menu(tg_id),
    )
    await cb.answer()


async def _bike_ride(cb: CallbackQuery, bot: Bot, tg_id: int) -> None:
    profile = await storage.get_profile(tg_id)
    take = (profile[3] * BIKE_INSURANCE_PCT) // 100 if profile else 0
    if take > 0:
        await storage.spend_zbucks(tg_id, take)
    await cb.answer(bike_ride(take), show_alert=True)
    await announce(bot, bike_ride_chat(_mention(cb), take))


# --- Самсунг: список получателей + отправка (только в личке) ---
async def _samsung_write(cb: CallbackQuery, tg_id: int) -> None:
    if cb.message.chat.type != ChatType.PRIVATE:
        return await cb.answer("✉️ Писать можно только в личке бота", show_alert=True)
    owners = await storage.item_owners("samsung", tg_id)
    if not owners:
        return await cb.answer("Больше ни у кого нет Самсунга 🤷", show_alert=True)
    rows = [[InlineKeyboardButton(text=f"📲 {nick}", callback_data=f"sms:to:{pid}")]
            for pid, nick in owners]
    rows.append([InlineKeyboardButton(text="⬅️ К инвентарю", callback_data=with_owner("menu:inventory", tg_id))])
    await show_text_menu(cb.message, "📲 <b>Самсунг</b>\nКому написать?", _kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("sms:to:"))
async def sms_to(cb: CallbackQuery, state: FSMContext):
    if cb.message.chat.type != ChatType.PRIVATE:
        return await cb.answer("Только в личке", show_alert=True)
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
