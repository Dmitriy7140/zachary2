"""24-часовая лотерея: розыгрыш и доставка уведомлений.

Денежные изменения и смена тиража происходят атомарно в storage.
Здесь остаются только посткоммитные действия: Густав и Telegram-outbox.
"""
import asyncio
import logging
import secrets
from datetime import datetime, timedelta
from typing import Callable

from aiogram import Bot
from aiogram.utils.markdown import hlink

from config import config
from db import storage
from game.taxman import maybe_gustav

log = logging.getLogger(__name__)

TICKET_PRICE = 50
ROUND_HOURS = 24
ROUND_DURATION = timedelta(hours=ROUND_HOURS)
FEE_BPS = 1_000
COMMISSION_BPS = FEE_BPS
SCHEDULER_INTERVAL_SECONDS = 30

NOTIFICATION_RETRY_BASE_SECONDS = 30
NOTIFICATION_RETRY_MAX_SECONDS = 60 * 60
NOTIFICATION_BATCH_SIZE = 20
WORK_CLAIM_LEASE_SECONDS = 5 * 60

PRIVATE_NOTIFICATION = "winner_private"
PUBLIC_NOTIFICATION = "result_public"


async def ensure_current_round(now: datetime | None = None) -> int:
    """Создать первый тираж, если открытого ещё нет.

    Storage не заменяет просроченный открытый тираж: его сначала
    должен завершить `_settle_due`, не теряя билеты и банк.
    """
    current = now or datetime.now()
    return await storage.ensure_lottery_round(
        current.isoformat(),
        (current + ROUND_DURATION).isoformat(),
        ticket_price=TICKET_PRICE,
        fee_bps=FEE_BPS,
    )


async def run_lottery_scheduler(bot: Bot) -> None:
    """Сразу обработать лотерею, затем повторять tick каждые 30 секунд."""
    try:
        while True:
            try:
                await _tick(bot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Защитная граница: фазы _tick тоже изолируют ошибки,
                # но неизвестная ошибка не должна убивать scheduler.
                log.exception("Лотерея: ошибка планировщика: %s", exc)
            await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        log.info("Планировщик лотереи остановлен")
        raise


async def _tick(
    bot: Bot,
    *,
    now: datetime | None = None,
    randbelow: Callable[[int], int] = secrets.randbelow,
) -> None:
    """Один тестируемый такт планировщика.

    Каждая посткоммитная фаза изолирована: например, сбой Telegram не
    мешает отметить Густава или доставить другое уведомление.
    """
    current = now or datetime.now()

    try:
        await ensure_current_round(current)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("Лотерея: не удалось обеспечить текущий тираж: %s", exc)

    await _settle_due(current, randbelow)
    await _process_pending_tax(bot, current)
    await _deliver_pending_notifications(bot, current)


async def _settle_due(current: datetime, randbelow: Callable[[int], int]) -> None:
    """Атомарно завершить просроченный тираж и открыть следующий."""
    try:
        result = await storage.settle_due_lottery(
            current.isoformat(),
            (current + ROUND_DURATION).isoformat(),
            next_ticket_price=TICKET_PRICE,
            next_fee_bps=FEE_BPS,
            randbelow=randbelow,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("Лотерея: ошибка завершения тиража: %s", exc)
        return

    if result is not None:
        log.info(
            "Лотерея #%s завершена: билетов %s, банк %s Z, приз %s Z",
            result.round_id,
            result.ticket_count,
            result.gross_pool,
            result.prize_amount,
        )


async def _process_pending_tax(bot: Bot, current: datetime) -> None:
    """Выполнить отложенную проверку Густава по снимку балансов."""
    claim_token = secrets.token_urlsafe(16)
    now_iso = current.isoformat()
    claim_until = (
        current + timedelta(seconds=WORK_CLAIM_LEASE_SECONDS)
    ).isoformat()
    try:
        settlements = await storage.claim_pending_lottery_tax(
            claim_token,
            now_iso,
            claim_until,
            limit=NOTIFICATION_BATCH_SIZE,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("Лотерея: не удалось арендовать pending tax: %s", exc)
        return

    for settlement in settlements:
        try:
            if settlement.winner_tg_id is not None:
                await maybe_gustav(
                    bot,
                    settlement.winner_tg_id,
                    settlement.winner_balance_before,
                    settlement.winner_balance_after,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception(
                "Лотерея #%s: не удалось обработать Густава: %s",
                settlement.round_id,
                exc,
            )
            try:
                await storage.release_lottery_tax_claim(
                    settlement.round_id, claim_token
                )
            except Exception as release_exc:
                log.exception(
                    "Лотерея #%s: не удалось освободить lease Густава: %s",
                    settlement.round_id,
                    release_exc,
                )
            continue

        try:
            marked = await storage.mark_lottery_tax_processed(
                settlement.round_id, claim_token, now_iso
            )
            if not marked:
                log.warning(
                    "Лотерея #%s: lease Густава потерян до отметки результата",
                    settlement.round_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Не освобождаем lease: post-commit side effect уже мог пройти.
            # После expiry повтор безопасно упирается в idempotency Густава.
            log.exception(
                "Лотерея #%s: не удалось отметить Густава обработанным: %s",
                settlement.round_id,
                exc,
            )


async def _deliver_pending_notifications(bot: Bot, current: datetime) -> None:
    """Доставить due-сообщения outbox; каждую ошибку вернуть в retry."""
    now_iso = current.isoformat()
    claim_token = secrets.token_urlsafe(16)
    claim_until = (
        current + timedelta(seconds=WORK_CLAIM_LEASE_SECONDS)
    ).isoformat()
    try:
        notifications = await storage.claim_lottery_notifications(
            claim_token,
            now_iso,
            claim_until,
            limit=NOTIFICATION_BATCH_SIZE,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("Лотерея: не удалось арендовать outbox: %s", exc)
        return

    for notification in notifications:
        try:
            await _send_notification(bot, notification)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            delay = _notification_retry_delay(notification.attempts)
            next_attempt = (current + timedelta(seconds=delay)).isoformat()
            error = f"{type(exc).__name__}: {exc}"[:1000]
            log.exception(
                "Лотерея #%s: не доставлено уведомление %s "
                "(повтор через %s с): %s",
                notification.round_id,
                notification.notification_id,
                delay,
                exc,
            )
            try:
                await storage.mark_lottery_notification_retry(
                    notification.notification_id,
                    claim_token,
                    next_attempt,
                    error,
                )
            except asyncio.CancelledError:
                raise
            except Exception as retry_exc:
                log.exception(
                    "Лотерея: не удалось сохранить retry уведомления %s: %s",
                    notification.notification_id,
                    retry_exc,
                )
            continue

        try:
            marked = await storage.mark_lottery_notification_sent(
                notification.notification_id, claim_token, now_iso
            )
            if not marked:
                log.warning(
                    "Лотерея: lease уведомления %s потерян до отметки sent",
                    notification.notification_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Сообщение уже могло уйти: оставляем claim до expiry вместо
            # немедленного повтора и возможного дубля.
            log.exception(
                "Лотерея: не удалось отметить уведомление %s отправленным: %s",
                notification.notification_id,
                exc,
            )


async def _send_notification(bot: Bot, notification) -> None:
    if notification.kind == PRIVATE_NOTIFICATION:
        recipient = notification.recipient_tg_id or notification.winner_tg_id
        if recipient is None:
            raise ValueError("у личного уведомления нет получателя")
        await bot.send_message(recipient, _private_result_text(notification))
        return

    if notification.kind == PUBLIC_NOTIFICATION:
        winner = await _winner_label(notification)
        await bot.send_message(
            chat_id=config.channel_id,
            message_thread_id=config.thread_id or None,
            text=_public_result_text(notification, winner),
        )
        return

    raise ValueError(f"неизвестный тип lottery notification: {notification.kind!r}")


async def _winner_label(notification) -> str:
    """HTML-safe Telegram-ссылка на победителя."""
    tg_id = notification.winner_tg_id
    if tg_id is None:
        raise ValueError("у результата нет победителя")

    profile = await storage.get_profile(tg_id)
    nick = profile[2] if profile else notification.winner_nick
    # hlink сам экранирует title для HTML parse mode.
    return hlink(str(nick or "Игрок"), f"tg://user?id={int(tg_id)}")


def _private_result_text(notification) -> str:
    return (
        "🎟 <b>Твой билет выиграл!</b>\n"
        f"Тираж #{notification.round_id}, "
        f"билет №{notification.winner_ticket_number}.\n"
        f"Приз: <b>{notification.prize_amount} Z</b> 💰"
    )


def _public_result_text(notification, winner: str) -> str:
    return (
        f"🎟 <b>Лотерея #{notification.round_id} разыграна!</b>\n"
        f"Билет №{notification.winner_ticket_number} игрока {winner} "
        f"выиграл <b>{notification.prize_amount} Z</b>.\n"
        f"Банк: {notification.gross_pool} Z, "
        f"комиссия: {notification.house_cut} Z."
    )


def _notification_retry_delay(attempts: int) -> int:
    """Экспоненциальная задержка 30, 60, 120, ... секунд с потолком в час."""
    exponent = min(max(int(attempts or 0), 0), 20)
    return min(
        NOTIFICATION_RETRY_BASE_SECONDS * (2 ** exponent),
        NOTIFICATION_RETRY_MAX_SECONDS,
    )
