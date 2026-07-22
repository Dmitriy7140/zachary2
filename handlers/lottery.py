"""Глобальная лотерея: экран тиража, покупка билета и архив билетов."""
import re
from datetime import datetime
from secrets import token_urlsafe

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from content import lottery as lottery_content
from db import storage
from utils.guards import with_owner
from utils.photo import show_screen

router = Router()

_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{11}")
_POSITIVE_INT_RE = re.compile(r"[1-9][0-9]*")


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _positive_int(value: str) -> int | None:
    if _POSITIVE_INT_RE.fullmatch(value) is None:
        return None
    return int(value)


def _view_owner(data: str | None) -> int | None:
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[:2] != ["lot", "view"]:
        return None
    return _positive_int(parts[2])


def _expired_owner(data: str | None) -> int | None:
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[:2] != ["lot", "expired"]:
        return None
    return _positive_int(parts[2])


def _refresh_args(data: str | None) -> tuple[int, int] | None:
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[:2] != ["lot", "refresh"]:
        return None
    round_id = _positive_int(parts[2])
    owner = _positive_int(parts[3])
    return (round_id, owner) if round_id is not None and owner is not None else None


def _buy_args(data: str | None) -> tuple[int, str, int] | None:
    parts = (data or "").split(":")
    if len(parts) != 5 or parts[:2] != ["lot", "buy"]:
        return None
    round_id = _positive_int(parts[2])
    token = parts[3]
    owner = _positive_int(parts[4])
    if round_id is None or owner is None or _TOKEN_RE.fullmatch(token) is None:
        return None
    return round_id, token, owner


async def _check_owner(cb: CallbackQuery, owner: int | None) -> bool:
    if owner is None:
        await cb.answer("Эта кнопка сломалась. Вернись в меню и попробуй снова.", show_alert=True)
        return False
    if owner != cb.from_user.id:
        await cb.answer("Это не твой билетный киоск — открой своё меню 😉", show_alert=True)
        return False
    return True


def _sales_closed(closes_at: str, now: datetime) -> bool:
    try:
        return datetime.fromisoformat(closes_at) <= now
    except (TypeError, ValueError):
        return True


async def _render_round(cb: CallbackQuery, owner: int) -> None:
    now = datetime.now()
    view = await storage.get_lottery_view(tg_id=owner, now_iso=now.isoformat())
    if view is None:
        rows = [
            [InlineKeyboardButton(text="🔄 Обновить", callback_data=with_owner("lot:view", owner))],
            [InlineKeyboardButton(text="⬅️ К мини-играм", callback_data=with_owner("menu:games", owner))],
        ]
        await show_screen(cb.message, lottery_content.no_active_round(), _kb(rows))
        return

    closed = _sales_closed(view.closes_at, now)
    rows = []
    if not closed:
        token = token_urlsafe(8)
        buy_data = f"lot:buy:{view.round_id}:{token}:{owner}"
        if len(buy_data.encode("utf-8")) > 64:
            raise ValueError("lottery buy callback_data exceeds Telegram's 64-byte limit")
        rows.append([
            InlineKeyboardButton(
                text=f"🎟 Купить билет — {view.ticket_price} Z",
                callback_data=buy_data,
            )
        ])
    rows.extend([
        [InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data=f"lot:refresh:{view.round_id}:{owner}",
        )],
        [InlineKeyboardButton(text="⬅️ К мини-играм", callback_data=with_owner("menu:games", owner))],
    ])
    await show_screen(
        cb.message,
        lottery_content.round_screen(view, now, sales_closed=closed),
        _kb(rows),
    )


@router.callback_query(F.data.startswith("lot:view:"))
async def lottery_view(cb: CallbackQuery):
    owner = _view_owner(cb.data)
    if not await _check_owner(cb, owner):
        return
    if not await storage.get_profile(owner):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    await cb.answer()
    await _render_round(cb, owner)


@router.callback_query(F.data.startswith("lot:refresh:"))
async def lottery_refresh(cb: CallbackQuery):
    args = _refresh_args(cb.data)
    if args is None:
        return await _check_owner(cb, None)
    shown_round_id, owner = args
    if not await _check_owner(cb, owner):
        return
    if not await storage.get_profile(owner):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)

    now = datetime.now()
    view = await storage.get_lottery_view(tg_id=owner, now_iso=now.isoformat())
    changed = view is not None and view.round_id != shown_round_id
    await cb.answer("🎉 Уже начался новый тираж!" if changed else "Обновлено")
    await _render_round(cb, owner)


@router.callback_query(F.data.startswith("lot:buy:"))
async def lottery_buy(cb: CallbackQuery):
    args = _buy_args(cb.data)
    if args is None:
        return await _check_owner(cb, None)
    round_id, token, owner = args
    if not await _check_owner(cb, owner):
        return

    result = await storage.buy_lottery_ticket(
        round_id=round_id,
        tg_id=owner,
        request_key=token,
        now_iso=datetime.now().isoformat(),
    )
    status = result.status
    if status == "ok":
        ticket = f" №{result.ticket_number}" if result.ticket_number is not None else ""
        await cb.answer(f"🎟 Билет{ticket} куплен!")
    elif status == "duplicate":
        await cb.answer("Этот билет уже выдан. Покупка не повторилась.", show_alert=True)
    elif status == "closed":
        await cb.answer("Тираж уже закрыл кассу. Показываю актуальный.", show_alert=True)
    elif status == "insufficient":
        await cb.answer("Не хватает Z. Лототрон в долг не крутится.", show_alert=True)
    elif status == "no_profile":
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    else:
        await cb.answer("Кассир растерял билеты. Деньги не списаны.", show_alert=True)
    await _render_round(cb, owner)


@router.callback_query(F.data.startswith("lot:expired:"))
async def lottery_expired(cb: CallbackQuery):
    owner = _expired_owner(cb.data)
    if not await _check_owner(cb, owner):
        return
    if not await storage.get_profile(owner):
        return await cb.answer("Сначала зарегистрируйся 😉", show_alert=True)
    counts = await storage.get_lottery_ticket_counts(tg_id=owner)
    rows = [[InlineKeyboardButton(
        text="⬅️ К инвентарю",
        callback_data=with_owner("menu:inventory", owner),
    )]]
    await cb.answer()
    await show_screen(cb.message, lottery_content.expired_tickets(counts.expired_tickets), _kb(rows))
