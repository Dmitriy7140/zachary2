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


def _buy_args(data: str | None) -> tuple[int, int, str, int] | None:
    parts = (data or "").split(":")
    if parts[:2] != ["lot", "buy"]:
        return None
    # Старые уже показанные экраны содержат callback без количества и всегда
    # означают один билет. Новые кнопки передают строго 1 или 10.
    if len(parts) == 5:
        round_id = _positive_int(parts[2])
        ticket_count = 1
        token = parts[3]
        owner = _positive_int(parts[4])
    elif len(parts) == 6:
        round_id = _positive_int(parts[2])
        ticket_count = _positive_int(parts[3])
        token = parts[4]
        owner = _positive_int(parts[5])
    else:
        return None
    if (
        round_id is None
        or ticket_count not in storage.LOTTERY_PURCHASE_TICKET_COUNTS
        or owner is None
        or _TOKEN_RE.fullmatch(token) is None
    ):
        return None
    return round_id, ticket_count, token, owner


def _buy_callback_data(
    round_id: int, ticket_count: int, token: str, owner: int
) -> str:
    """Собрать короткий callback для новой покупки и не превысить лимит Telegram."""
    callback_data = f"lot:buy:{round_id}:{ticket_count}:{token}:{owner}"
    if len(callback_data.encode("utf-8")) > 64:
        raise ValueError("lottery buy callback_data exceeds Telegram's 64-byte limit")
    return callback_data


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
        buy_buttons = []
        for ticket_count in (1, 10):
            buy_buttons.append(InlineKeyboardButton(
                text=(
                    f"🎟 1 билет — {view.ticket_price} Z"
                    if ticket_count == 1
                    else f"🎟 ×10 — {view.ticket_price * ticket_count} Z"
                ),
                callback_data=_buy_callback_data(
                    view.round_id, ticket_count, token_urlsafe(8), owner
                ),
            ))
        rows.append(buy_buttons)
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
    round_id, ticket_count, token, owner = args
    if not await _check_owner(cb, owner):
        return

    result = await storage.buy_lottery_tickets(
        round_id=round_id,
        tg_id=owner,
        ticket_count=ticket_count,
        request_key=token,
        now_iso=datetime.now().isoformat(),
    )
    status = result.status
    if status == "ok":
        await cb.answer(lottery_content.purchase_success(result.ticket_numbers))
    elif status == "duplicate":
        await cb.answer(
            lottery_content.purchase_duplicate(result.ticket_numbers), show_alert=True
        )
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
