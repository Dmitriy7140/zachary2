import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from config import config
from content import lottery as lottery_content
from db import storage
from game import lottery
from handlers import lottery as lottery_handler


STARTS_AT = datetime(2026, 7, 22, 12, 0, 0)
CLOSES_AT = STARTS_AT + timedelta(hours=24)


class _TemporaryStorageCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._old_db_path = config.db_path
        self._temp_dir = tempfile.TemporaryDirectory()
        config.db_path = str(Path(self._temp_dir.name) / "lottery.sqlite3")
        await storage.close()
        # IsolatedAsyncioTestCase создаёт новый loop для каждого теста.
        # Lock живёт на уровне модуля и после теста с contention привязан к
        # старому loop, поэтому каждому изолированному DB-кейсу нужен свой.
        storage._economy_lock = asyncio.Lock()

    async def asyncTearDown(self) -> None:
        await storage.close()
        config.db_path = self._old_db_path
        self._temp_dir.cleanup()

    async def _fetchone(self, sql: str, params: tuple = ()) -> tuple | None:
        cursor = await storage._db.execute(sql, params)
        return await cursor.fetchone()

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        cursor = await storage._db.execute(sql, params)
        return await cursor.fetchall()


class LotteryMigrationTests(_TemporaryStorageCase):
    async def test_init_twice_migrates_legacy_db_without_losing_data(self) -> None:
        legacy = sqlite3.connect(config.db_path)
        legacy.executescript(
            """
            CREATE TABLE profiles (
                tg_id      INTEGER PRIMARY KEY,
                username   TEXT,
                nick       TEXT UNIQUE,
                zbucks     INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE inventory (
                tg_id INTEGER,
                item  TEXT,
                qty   INTEGER DEFAULT 0,
                PRIMARY KEY (tg_id, item)
            );
            INSERT INTO profiles (tg_id, username, nick, zbucks)
            VALUES (101, 'legacy_user', 'LegacyNick', 175);
            INSERT INTO inventory (tg_id, item, qty)
            VALUES (101, 'diamond', 3);
            """
        )
        legacy.commit()
        legacy.close()

        await storage.init()
        first_round = await lottery.ensure_current_round(STARTS_AT)
        await storage.init()
        same_round = await lottery.ensure_current_round(STARTS_AT + timedelta(minutes=1))

        self.assertEqual(first_round, same_round)
        self.assertEqual(
            (101, "legacy_user", "LegacyNick", 175, 0, 0),
            await storage.get_profile(101),
        )
        self.assertEqual({"diamond": 3}, await storage.get_inventory(101))

        profile_columns = {
            row[1] for row in await self._fetchall("PRAGMA table_info(profiles)")
        }
        self.assertTrue(
            {"xp", "level", "thefts", "honest", "dirty", "self_employed"}
            <= profile_columns
        )
        lottery_tables = {
            row[0]
            for row in await self._fetchall(
                """SELECT name FROM sqlite_master
                   WHERE type = 'table' AND name LIKE 'lottery_%'"""
            )
        }
        self.assertEqual(
            {"lottery_rounds", "lottery_tickets", "lottery_notifications"},
            lottery_tables,
        )
        self.assertEqual(
            (1,), await self._fetchone("SELECT COUNT(*) FROM lottery_rounds")
        )


class LotteryStorageTests(_TemporaryStorageCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await storage.init()
        self.round_id = await lottery.ensure_current_round(STARTS_AT)

    async def _create_profile(
        self, tg_id: int, *, balance: int = 0, dirty: int = 0
    ) -> None:
        created = await storage.create_profile(tg_id, f"user{tg_id}", f"Nick{tg_id}")
        self.assertTrue(created)
        if balance:
            await storage.add_zbucks(tg_id, balance)
        if dirty:
            await storage.add_dirty(tg_id, dirty)

    async def test_buy_ok_duplicate_insufficient_no_profile_and_exact_deadline(
        self,
    ) -> None:
        await self._create_profile(1, balance=80)

        bought = await storage.buy_lottery_ticket(
            self.round_id, 1, "request-one", STARTS_AT.isoformat()
        )
        self.assertEqual("ok", bought.status)
        self.assertEqual(1, bought.ticket_number)
        self.assertEqual(1, bought.total_tickets)
        self.assertEqual(1, bought.own_tickets)
        self.assertEqual(50, bought.gross_pool)
        self.assertEqual(45, bought.prize_amount)
        self.assertEqual(30, bought.balance)

        duplicate = await storage.buy_lottery_ticket(
            self.round_id,
            1,
            "request-one",
            (STARTS_AT + timedelta(seconds=1)).isoformat(),
        )
        self.assertEqual("duplicate", duplicate.status)
        self.assertEqual(bought.ticket_id, duplicate.ticket_id)
        self.assertEqual(bought.ticket_number, duplicate.ticket_number)
        self.assertEqual(30, duplicate.balance)

        insufficient = await storage.buy_lottery_ticket(
            self.round_id,
            1,
            "request-two",
            (STARTS_AT + timedelta(seconds=2)).isoformat(),
        )
        self.assertEqual("insufficient", insufficient.status)

        no_profile = await storage.buy_lottery_ticket(
            self.round_id,
            999,
            "missing-profile",
            (STARTS_AT + timedelta(seconds=2)).isoformat(),
        )
        self.assertEqual("no_profile", no_profile.status)

        at_deadline = await storage.buy_lottery_ticket(
            self.round_id, 1, "at-deadline", CLOSES_AT.isoformat()
        )
        self.assertEqual("closed", at_deadline.status)
        self.assertEqual(
            (1, 50),
            await self._fetchone(
                """SELECT COUNT(*), COALESCE(SUM(paid_amount), 0)
                   FROM lottery_tickets WHERE round_id = ?""",
                (self.round_id,),
            ),
        )
        self.assertEqual(30, (await storage.get_profile(1))[3])

    async def test_hidden_money_is_unavailable_and_dirty_money_is_spent_first(
        self,
    ) -> None:
        await self._create_profile(1, balance=100, dirty=80)
        await storage.set_cooldown_until(
            1, storage.HIDE_KEY, (CLOSES_AT + timedelta(hours=1)).isoformat()
        )
        await storage.set_meta(storage.hidden_meta_key(1), "60")

        unavailable = await storage.buy_lottery_ticket(
            self.round_id, 1, "hidden-too-much", STARTS_AT.isoformat()
        )
        self.assertEqual("insufficient", unavailable.status)
        self.assertEqual(100, (await storage.get_profile(1))[3])
        self.assertEqual(80, await storage.get_dirty(1))

        await storage.set_meta(storage.hidden_meta_key(1), "20")
        bought = await storage.buy_lottery_ticket(
            self.round_id,
            1,
            "dirty-purchase",
            (STARTS_AT + timedelta(seconds=1)).isoformat(),
        )
        self.assertEqual("ok", bought.status)
        self.assertEqual(50, (await storage.get_profile(1))[3])
        self.assertEqual(30, await storage.get_dirty(1))
        self.assertEqual(
            (50, 50),
            await self._fetchone(
                """SELECT paid_amount, dirty_amount FROM lottery_tickets
                   WHERE request_key = 'dirty-purchase'"""
            ),
        )

    async def test_hiding_and_ticket_purchase_share_one_atomic_writer(self) -> None:
        await self._create_profile(1, balance=100, dirty=100)

        purchase, hidden = await asyncio.gather(
            storage.buy_lottery_ticket(
                self.round_id, 1, "purchase-vs-hide", STARTS_AT.isoformat()
            ),
            storage.activate_hidden_money(
                1,
                60,
                (STARTS_AT + timedelta(hours=1)).isoformat(),
                (STARTS_AT + timedelta(hours=2)).isoformat(),
                STARTS_AT.isoformat(),
            ),
        )

        balance = (await storage.get_profile(1))[3]
        dirty = await storage.get_dirty(1)
        self.assertIn((purchase.status, hidden), {("ok", 50), ("insufficient", 60)})
        self.assertLessEqual(hidden, balance)
        self.assertLessEqual(hidden, dirty)
        self.assertEqual(1 if purchase.status == "ok" else 0, purchase.total_tickets)

    async def test_two_concurrent_buys_cannot_overspend_one_balance(self) -> None:
        await self._create_profile(1, balance=50)

        results = await asyncio.gather(
            storage.buy_lottery_ticket(
                self.round_id, 1, "concurrent-a", STARTS_AT.isoformat()
            ),
            storage.buy_lottery_ticket(
                self.round_id, 1, "concurrent-b", STARTS_AT.isoformat()
            ),
        )

        self.assertCountEqual(["ok", "insufficient"], [r.status for r in results])
        self.assertEqual(0, (await storage.get_profile(1))[3])
        view = await storage.get_lottery_view(1, STARTS_AT.isoformat())
        self.assertEqual(1, view.total_tickets)
        self.assertEqual(1, view.own_tickets)

    async def test_purchase_racing_settlement_has_one_consistent_outcome(self) -> None:
        await self._create_profile(1, balance=50)
        next_close = CLOSES_AT + timedelta(hours=24)

        purchase, settled = await asyncio.gather(
            storage.buy_lottery_ticket(
                self.round_id,
                1,
                "purchase-vs-close",
                (CLOSES_AT - timedelta(microseconds=1)).isoformat(),
            ),
            storage.settle_lottery_round(
                self.round_id,
                CLOSES_AT.isoformat(),
                next_close.isoformat(),
                randbelow=lambda size: 0,
            ),
        )

        self.assertIsNotNone(settled)
        if purchase.status == "ok":
            self.assertEqual(1, settled.ticket_count)
            self.assertEqual(45, settled.prize_amount)
            self.assertEqual(45, (await storage.get_profile(1))[3])
        else:
            self.assertEqual("closed", purchase.status)
            self.assertEqual(0, settled.ticket_count)
            self.assertEqual(0, settled.prize_amount)
            self.assertEqual(50, (await storage.get_profile(1))[3])

    async def test_ticket_and_existing_spend_share_one_atomic_economy_path(self) -> None:
        await self._create_profile(1, balance=50)

        purchase, ordinary_spend = await asyncio.gather(
            storage.buy_lottery_ticket(
                self.round_id, 1, "purchase-vs-spend", STARTS_AT.isoformat()
            ),
            storage.spend_zbucks(1, 50),
        )

        self.assertEqual(0, (await storage.get_profile(1))[3])
        self.assertIn(
            (purchase.status, ordinary_spend),
            {("ok", False), ("insufficient", True)},
        )
        view = await storage.get_lottery_view(1, STARTS_AT.isoformat())
        self.assertEqual(1 if purchase.status == "ok" else 0, view.total_tickets)

    async def test_handled_unique_errors_release_the_main_write_lock(self) -> None:
        await self._create_profile(1, balance=50)
        self.assertFalse(await storage.create_profile(1, "duplicate", "OtherNick"))
        self.assertTrue(
            await storage.create_business(
                1, "shop", "small", CLOSES_AT.isoformat(), CLOSES_AT.isoformat()
            )
        )
        self.assertFalse(
            await storage.create_business(
                1, "shop", "small", CLOSES_AT.isoformat(), CLOSES_AT.isoformat()
            )
        )

        purchase = await storage.buy_lottery_ticket(
            self.round_id, 1, "after-integrity-error", STARTS_AT.isoformat()
        )
        self.assertEqual("ok", purchase.status)
        self.assertEqual(0, (await storage.get_profile(1))[3])

    async def test_one_ticket_settlement_expires_ticket_and_creates_durable_work(
        self,
    ) -> None:
        await self._create_profile(1, balance=50)
        await storage.buy_lottery_ticket(
            self.round_id, 1, "only-ticket", STARTS_AT.isoformat()
        )
        # Покупка и активный виртуальный билет переживают перезапуск storage.
        await storage.init()
        self.assertEqual(
            storage.LotteryTicketCounts(active_tickets=1, expired_tickets=0),
            await storage.get_lottery_ticket_counts(1),
        )

        next_close = CLOSES_AT + timedelta(hours=24)
        settled = await storage.settle_due_lottery(
            CLOSES_AT.isoformat(),
            next_close.isoformat(),
            randbelow=lambda size: 0,
        )

        self.assertIsNotNone(settled)
        self.assertEqual(1, settled.ticket_count)
        self.assertEqual(50, settled.gross_pool)
        self.assertEqual(5, settled.house_cut)
        self.assertEqual(45, settled.prize_amount)
        self.assertEqual(1, settled.winner_tg_id)
        self.assertEqual(1, settled.winner_ticket_number)
        self.assertEqual(0, settled.winner_balance_before)
        self.assertEqual(45, settled.winner_balance_after)

        # Выплата, результат, следующий тираж, tax и outbox также durable.
        await storage.init()
        self.assertEqual(settled, await storage.get_lottery_settlement(self.round_id))
        self.assertEqual(45, (await storage.get_profile(1))[3])
        self.assertEqual(
            storage.LotteryTicketCounts(active_tickets=0, expired_tickets=1),
            await storage.get_lottery_ticket_counts(1),
        )

        next_round = await storage.get_lottery_view(1, CLOSES_AT.isoformat())
        self.assertNotEqual(self.round_id, next_round.round_id)
        self.assertEqual(CLOSES_AT.isoformat(), next_round.starts_at)
        self.assertEqual(next_close.isoformat(), next_round.closes_at)
        self.assertEqual(0, next_round.total_tickets)

        pending_tax = await storage.pending_lottery_tax()
        self.assertEqual([self.round_id], [row.round_id for row in pending_tax])
        claimed_tax = await storage.claim_pending_lottery_tax(
            "tax-test-claim",
            CLOSES_AT.isoformat(),
            (CLOSES_AT + timedelta(minutes=5)).isoformat(),
        )
        self.assertEqual([self.round_id], [row.round_id for row in claimed_tax])
        self.assertTrue(
            await storage.mark_lottery_tax_processed(
                self.round_id, "tax-test-claim", CLOSES_AT.isoformat()
            )
        )
        self.assertFalse(
            await storage.mark_lottery_tax_processed(
                self.round_id, "tax-test-claim", CLOSES_AT.isoformat()
            )
        )
        self.assertEqual([], await storage.pending_lottery_tax())

        notifications = await storage.pending_lottery_notifications(
            CLOSES_AT.isoformat()
        )
        self.assertEqual(
            {"winner_private", "result_public"},
            {notification.kind for notification in notifications},
        )
        self.assertTrue(all(notification.prize_amount == 45 for notification in notifications))

    async def test_two_ticket_settlement_has_deterministic_winner_and_is_idempotent(
        self,
    ) -> None:
        await self._create_profile(1, balance=50)
        await self._create_profile(2, balance=50)
        await storage.buy_lottery_ticket(
            self.round_id, 1, "first-ticket", STARTS_AT.isoformat()
        )
        await storage.buy_lottery_ticket(
            self.round_id,
            2,
            "second-ticket",
            (STARTS_AT + timedelta(seconds=1)).isoformat(),
        )
        next_close = CLOSES_AT + timedelta(hours=24)

        attempts = await asyncio.gather(
            storage.settle_lottery_round(
                self.round_id,
                CLOSES_AT.isoformat(),
                next_close.isoformat(),
                randbelow=lambda size: 1,
            ),
            storage.settle_lottery_round(
                self.round_id,
                CLOSES_AT.isoformat(),
                next_close.isoformat(),
                randbelow=lambda size: 1,
            ),
        )
        successful = [result for result in attempts if result is not None]

        self.assertEqual(1, len(successful))
        settled = successful[0]
        self.assertEqual(2, settled.ticket_count)
        self.assertEqual(100, settled.gross_pool)
        self.assertEqual(10, settled.house_cut)
        self.assertEqual(90, settled.prize_amount)
        self.assertEqual(2, settled.winner_ticket_number)
        self.assertEqual(2, settled.winner_tg_id)
        self.assertEqual(0, (await storage.get_profile(1))[3])
        self.assertEqual(90, (await storage.get_profile(2))[3])
        self.assertIsNone(
            await storage.settle_lottery_round(
                self.round_id,
                CLOSES_AT.isoformat(),
                next_close.isoformat(),
                randbelow=lambda size: 0,
            )
        )
        self.assertEqual(
            [("settled", None), ("open", 1)],
            await self._fetchall(
                "SELECT status, active_slot FROM lottery_rounds ORDER BY id"
            ),
        )
        self.assertEqual(
            (2,),
            await self._fetchone(
                "SELECT COUNT(*) FROM lottery_notifications WHERE round_id = ?",
                (self.round_id,),
            ),
        )

    async def test_old_round_never_redirects_and_expired_history_accumulates(self) -> None:
        await self._create_profile(1, balance=100)
        await storage.buy_lottery_ticket(
            self.round_id, 1, "history-round-one", STARTS_AT.isoformat()
        )
        second_close = CLOSES_AT + timedelta(hours=24)
        await storage.settle_due_lottery(
            CLOSES_AT.isoformat(),
            second_close.isoformat(),
            randbelow=lambda size: 0,
        )

        second_round = await storage.get_lottery_view(
            1, (CLOSES_AT + timedelta(seconds=1)).isoformat()
        )
        self.assertIsNotNone(second_round)
        stale = await storage.buy_lottery_ticket(
            self.round_id,
            1,
            "unused-token-for-old-round",
            (CLOSES_AT + timedelta(seconds=1)).isoformat(),
        )
        self.assertEqual("closed", stale.status)
        self.assertEqual(95, (await storage.get_profile(1))[3])

        current = await storage.buy_lottery_ticket(
            second_round.round_id,
            1,
            "history-round-two",
            (CLOSES_AT + timedelta(seconds=1)).isoformat(),
        )
        self.assertEqual("ok", current.status)
        await storage.settle_due_lottery(
            second_close.isoformat(),
            (second_close + timedelta(hours=24)).isoformat(),
            randbelow=lambda size: 0,
        )
        self.assertEqual(
            storage.LotteryTicketCounts(active_tickets=0, expired_tickets=2),
            await storage.get_lottery_ticket_counts(1),
        )

    async def test_empty_round_settles_without_winner_tax_or_notifications(self) -> None:
        await self._create_profile(1)
        next_close = CLOSES_AT + timedelta(hours=24)

        def unexpected_random(_: int) -> int:
            self.fail("randbelow must not be called for an empty lottery")

        settled = await storage.settle_due_lottery(
            CLOSES_AT.isoformat(),
            next_close.isoformat(),
            randbelow=unexpected_random,
        )

        self.assertIsNotNone(settled)
        self.assertEqual(0, settled.ticket_count)
        self.assertEqual(0, settled.gross_pool)
        self.assertEqual(0, settled.house_cut)
        self.assertEqual(0, settled.prize_amount)
        self.assertIsNone(settled.winner_tg_id)
        self.assertEqual([], await storage.pending_lottery_tax())
        self.assertEqual(
            [], await storage.pending_lottery_notifications(CLOSES_AT.isoformat())
        )
        next_round = await storage.get_lottery_view(1, CLOSES_AT.isoformat())
        self.assertEqual(CLOSES_AT.isoformat(), next_round.starts_at)
        self.assertEqual(next_close.isoformat(), next_round.closes_at)


class _FakeBot:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.calls: list[tuple[str, tuple, dict]] = []

    async def send_message(self, *args, **kwargs) -> None:
        self.calls.append(("message", args, kwargs))
        if self.fail:
            raise RuntimeError("Telegram unavailable")

    async def send_photo(self, *args, **kwargs) -> None:
        self.calls.append(("photo", args, kwargs))
        if self.fail:
            raise RuntimeError("Telegram unavailable")


class LotterySchedulerTests(_TemporaryStorageCase):
    async def test_public_result_sends_generated_photo_to_channel_thread(self) -> None:
        notification = SimpleNamespace(
            kind=lottery.PUBLIC_NOTIFICATION,
            round_id=9,
            winner_tg_id=1,
            winner_nick="Winner",
            winner_ticket_number=44,
            prize_amount=12_345,
        )
        bot = _FakeBot(fail=False)
        identity = AsyncMock(
            return_value=(
                "Winner",
                '<a href="tg://user?id=1">@Winner</a>',
            )
        )

        with (
            patch.object(lottery, "_winner_identity", identity),
            patch.object(lottery, "render_winner_png", return_value=b"png") as render,
            patch.object(config, "channel_id", -100123),
            patch.object(config, "thread_id", 456),
        ):
            await lottery._send_notification(bot, notification)

        identity.assert_awaited_once_with(notification)
        render.assert_called_once_with("Winner")
        self.assertEqual(1, len(bot.calls))
        kind, args, kwargs = bot.calls[0]
        self.assertEqual("photo", kind)
        self.assertEqual((), args)
        self.assertEqual(-100123, kwargs["chat_id"])
        self.assertEqual(456, kwargs["message_thread_id"])
        self.assertEqual(b"png", kwargs["photo"].data)
        self.assertEqual("lottery_winner_9.png", kwargs["photo"].filename)
        self.assertIn("@Winner", kwargs["caption"])
        self.assertIn("12 345 Z", kwargs["caption"])
        self.assertIn("№44</b> — «стульчики»", kwargs["caption"])

    async def test_parallel_ticks_claim_post_commit_work_once(self) -> None:
        await storage.init()
        round_id = await lottery.ensure_current_round(STARTS_AT)
        self.assertTrue(await storage.create_profile(1, "winner", "Winner"))
        await storage.add_zbucks(1, 50)
        await storage.buy_lottery_ticket(
            round_id, 1, "parallel-tick-ticket", STARTS_AT.isoformat()
        )
        await storage.settle_due_lottery(
            CLOSES_AT.isoformat(),
            (CLOSES_AT + timedelta(hours=24)).isoformat(),
            randbelow=lambda size: 0,
        )

        bot = _FakeBot(fail=False)
        gustav = AsyncMock()
        with patch.object(lottery, "maybe_gustav", gustav):
            await asyncio.gather(
                lottery._tick(bot, now=CLOSES_AT, randbelow=lambda size: 0),
                lottery._tick(bot, now=CLOSES_AT, randbelow=lambda size: 0),
            )

        gustav.assert_awaited_once_with(bot, 1, 0, 45)
        self.assertEqual(2, len(bot.calls))
        self.assertCountEqual(["message", "photo"], [call[0] for call in bot.calls])
        self.assertEqual([], await storage.pending_lottery_tax())
        self.assertEqual(
            [],
            await storage.pending_lottery_notifications(
                (CLOSES_AT + timedelta(days=1)).isoformat()
            ),
        )

    async def test_gustav_failure_retries_without_repeating_prize(self) -> None:
        await storage.init()
        round_id = await lottery.ensure_current_round(STARTS_AT)
        self.assertTrue(await storage.create_profile(1, "winner", "Winner"))
        await storage.add_zbucks(1, 50)
        await storage.buy_lottery_ticket(
            round_id, 1, "gustav-retry-ticket", STARTS_AT.isoformat()
        )
        await storage.settle_due_lottery(
            CLOSES_AT.isoformat(),
            (CLOSES_AT + timedelta(hours=24)).isoformat(),
            randbelow=lambda size: 0,
        )

        bot = _FakeBot(fail=False)
        gustav = AsyncMock(side_effect=[RuntimeError("Gustav unavailable"), None])
        with patch.object(lottery, "maybe_gustav", gustav):
            with self.assertLogs("game.lottery", level="ERROR"):
                await lottery._tick(bot, now=CLOSES_AT, randbelow=lambda size: 0)
            await lottery._tick(
                bot,
                now=CLOSES_AT + timedelta(seconds=30),
                randbelow=lambda size: 0,
            )

        self.assertEqual(2, gustav.await_count)
        self.assertEqual(2, len(bot.calls))
        self.assertCountEqual(["message", "photo"], [call[0] for call in bot.calls])
        self.assertEqual(45, (await storage.get_profile(1))[3])
        self.assertEqual([], await storage.pending_lottery_tax())

    async def test_notification_failure_is_retried_without_repeating_tax_or_prize(
        self,
    ) -> None:
        await storage.init()
        round_id = await lottery.ensure_current_round(STARTS_AT)
        self.assertTrue(await storage.create_profile(1, "winner", "Winner"))
        await storage.add_zbucks(1, 50)
        await storage.buy_lottery_ticket(
            round_id, 1, "winning-ticket", STARTS_AT.isoformat()
        )
        await storage.settle_due_lottery(
            CLOSES_AT.isoformat(),
            (CLOSES_AT + timedelta(hours=24)).isoformat(),
            randbelow=lambda size: 0,
        )
        self.assertEqual(45, (await storage.get_profile(1))[3])

        failing_bot = _FakeBot(fail=True)
        gustav = AsyncMock()
        with patch.object(lottery, "maybe_gustav", gustav):
            with self.assertLogs("game.lottery", level="ERROR") as retry_logs:
                await lottery._tick(
                    failing_bot, now=CLOSES_AT, randbelow=lambda size: 0
                )

            gustav.assert_awaited_once_with(failing_bot, 1, 0, 45)
            self.assertEqual(
                2,
                sum("не доставлено уведомление" in line for line in retry_logs.output),
            )
            self.assertEqual([], await storage.pending_lottery_tax())
            self.assertEqual(2, len(failing_bot.calls))
            self.assertCountEqual(
                ["message", "photo"], [call[0] for call in failing_bot.calls]
            )
            self.assertEqual(
                [],
                await storage.pending_lottery_notifications(
                    (CLOSES_AT + timedelta(seconds=29)).isoformat()
                ),
            )
            retrying = await storage.pending_lottery_notifications(
                (CLOSES_AT + timedelta(seconds=30)).isoformat()
            )
            self.assertEqual(2, len(retrying))
            self.assertTrue(all(notification.attempts == 1 for notification in retrying))

            successful_bot = _FakeBot(fail=False)
            await lottery._tick(
                successful_bot,
                now=CLOSES_AT + timedelta(seconds=30),
                randbelow=lambda size: 0,
            )

        self.assertEqual(1, gustav.await_count)
        self.assertEqual(2, len(successful_bot.calls))
        self.assertCountEqual(
            ["message", "photo"], [call[0] for call in successful_bot.calls]
        )
        self.assertEqual(
            [],
            await storage.pending_lottery_notifications(
                (CLOSES_AT + timedelta(days=7)).isoformat()
            ),
        )
        self.assertEqual(45, (await storage.get_profile(1))[3])


class LotteryRetryDelayTests(unittest.TestCase):
    def test_retry_delay_is_exponential_and_capped_at_one_hour(self) -> None:
        self.assertEqual(30, lottery._notification_retry_delay(0))
        self.assertEqual(60, lottery._notification_retry_delay(1))
        self.assertEqual(120, lottery._notification_retry_delay(2))
        self.assertEqual(3600, lottery._notification_retry_delay(100))


class LotteryUiContractTests(unittest.TestCase):
    def test_buy_callback_is_strict_and_fits_telegram_limit(self) -> None:
        owner = 9_223_372_036_854_775_807
        round_id = 9_223_372_036_854_775_807
        token = "AbCdEf_123-"
        callback = f"lot:buy:{round_id}:{token}:{owner}"

        self.assertLessEqual(len(callback.encode("utf-8")), 64)
        self.assertEqual(
            (round_id, token, owner), lottery_handler._buy_args(callback)
        )
        self.assertIsNone(lottery_handler._buy_args(callback + ":tail"))
        self.assertIsNone(
            lottery_handler._buy_args(f"lot:buy:{round_id}:too-short:{owner}")
        )

    def test_round_screen_fits_photo_caption(self) -> None:
        view = SimpleNamespace(
            round_id=9_223_372_036_854_775_807,
            closes_at=CLOSES_AT.isoformat(),
            ticket_price=50,
            fee_bps=1_000,
            total_tickets=9_223_372_036_854_775_807,
            own_tickets=9_223_372_036_854_775_807,
            gross_pool=9_223_372_036_854_775_807,
            prize_amount=8_301_034_833_169_298_226,
            balance=9_223_372_036_854_775_807,
        )
        caption = lottery_content.round_screen(view, STARTS_AT, sales_closed=False)
        self.assertLessEqual(len(caption), 1_024)


if __name__ == "__main__":
    unittest.main()
