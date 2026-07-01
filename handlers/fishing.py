"""Рыбалка: закинуть удочку с наживкой, улов через 10 минут."""
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import hlink

from content.fishing import no_rod, no_rod_chat
from db import storage
from game.fishing import BAIT_ITEMS, CAST_MINUTES, fishing_level
from game.items import ITEMS
from keyboards import back_menu
from utils.guards import ensure_private, with_owner
from utils.notify import announce

router = Router()


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "fishing:start")
async def fishing_start(cb: CallbackQuery, bot: Bot):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    if not await storage.get_profile(tg_id):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    # без удочки — смех Жмыжко и Славянина
    if await storage.get_item_qty(tg_id, "rod") < 1:
        await cb.message.edit_text(no_rod(), reply_markup=back_menu(tg_id))
        await cb.answer()
        mention = hlink(cb.from_user.full_name, f"tg://user?id={tg_id}")
        return await announce(bot, no_rod_chat(mention))

    # уже закинута
    active = await storage.active_cast(tg_id)
    if active:
        bait_tier, catch_at = active
        left = max(0, int((datetime.fromisoformat(catch_at) - datetime.now()).total_seconds()))
        await cb.message.edit_text(
            f"🎣 Удочка закинута (наживка {ITEMS[BAIT_ITEMS[bait_tier]].emoji}).\n"
            f"Улов через {left // 60}м {left % 60}с — придёт уведомление.",
            reply_markup=back_menu(tg_id))
        return await cb.answer()

    # выбор наживки
    fc = await storage.player_stat(tg_id, "fish_caught")
    lvl = fishing_level(fc)
    rows = []
    for tier in (1, 2, 3):
        qty = await storage.get_item_qty(tg_id, BAIT_ITEMS[tier])
        if qty > 0:
            it = ITEMS[BAIT_ITEMS[tier]]
            rows.append([InlineKeyboardButton(text=f"{it.emoji} {it.name} (×{qty})",
                                              callback_data=f"fish:cast:{tier}")])
    if not rows:
        return await _msg(cb, "🎣 Нет наживки! Купи приманку в магазине.", tg_id)

    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=with_owner("menu:main", tg_id))])
    await cb.message.edit_text(
        f"🎣 <b>Рыбалка</b> · уровень {lvl} (поймано рыб: {fc})\nВыбери наживку и закинь удочку:",
        reply_markup=_kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("fish:cast:"))
async def fish_cast(cb: CallbackQuery):
    if not await ensure_private(cb):
        return
    tg_id = cb.from_user.id
    tier = int(cb.data.split(":")[2])
    if await storage.get_item_qty(tg_id, "rod") < 1:
        return await cb.answer("Нет удочки", show_alert=True)
    if await storage.active_cast(tg_id):
        return await cb.answer("Удочка уже закинута", show_alert=True)
    if not await storage.remove_item(tg_id, BAIT_ITEMS[tier], 1):
        return await cb.answer("Нет такой наживки", show_alert=True)

    catch_at = (datetime.now() + timedelta(minutes=CAST_MINUTES)).isoformat()
    await storage.cast_rod(tg_id, tier, catch_at)
    await _msg(cb, f"🎣 Закинул удочку с наживкой {ITEMS[BAIT_ITEMS[tier]].emoji}!\n"
                   f"Улов будет через {CAST_MINUTES} минут.", tg_id)


async def _msg(cb: CallbackQuery, text: str, tg_id: int):
    await cb.message.edit_text(text, reply_markup=back_menu(tg_id))
    await cb.answer()
