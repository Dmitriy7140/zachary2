import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from config import config
from db import storage
from game import cube as cube_game
from game.cube import CubeSpec, PassageSpec, RoomSpec


START = datetime(2026, 7, 23, 12, 0, 0)


def _spec(seed: int) -> CubeSpec:
    rooms = []
    for room_id in range(16):
        kind = "neutral"
        description = "neutral_blue"
        kwargs = {}
        if room_id == 0:
            kind = "start"
            description = "start"
        elif room_id == 1:
            kind = "hazard"
            description = "hazard_mutant_leeches"
            kwargs = {
                "hazard_kind": "mutant_leeches",
                "required_item_key": "bait_1",
                "consume_qty": 1,
                "is_required": True,
            }
        elif room_id == 2:
            kind = "prize"
            description = "prize"
        elif room_id == 4:
            kind = "anomaly"
            description = "anomaly.dark"
            kwargs = {"effect_kind": "dark"}
        elif room_id == 5:
            kind = "anomaly"
            description = "anomaly.echo"
            kwargs = {"effect_kind": "echo"}
        elif room_id == 8:
            kind = "anomaly"
            description = "anomaly.archive"
            kwargs = {
                "effect_kind": "archive",
                "effect_target_room_id": 9,
                "effect_arg": "e",
            }
        elif room_id == 9:
            kind = "anomaly"
            description = "anomaly.tunnel"
            kwargs = {
                "effect_kind": "tunnel",
                "effect_target_room_id": 10,
                "effect_arg": "410",
            }
        elif room_id == 10:
            kind = "anomaly"
            description = "anomaly.tunnel"
            kwargs = {
                "effect_kind": "tunnel",
                "effect_target_room_id": 9,
                "effect_arg": "409",
            }
        elif room_id == 12:
            kind = "anomaly"
            description = "anomaly.vector"
            kwargs = {
                "effect_kind": "vector",
                "effect_target_room_id": 13,
                "effect_arg": "413",
            }
        rooms.append(
            RoomSpec(
                room_id=room_id,
                row=room_id // 4,
                column=room_id % 4,
                code=400 + room_id,
                kind=kind,
                description_key=description,
                **kwargs,
            )
        )
    passages = []
    for room_id in range(16):
        row, column = divmod(room_id, 4)
        if column < 3:
            passages.append(PassageSpec(room_id, room_id + 1))
        if row < 3:
            passages.append(PassageSpec(room_id, room_id + 4))
    return CubeSpec(
        size=4,
        seed=seed,
        layout_version=1,
        start_room_id=0,
        prize_room_id=2,
        mandatory_room_id=1,
        rooms=tuple(rooms),
        passages=tuple(passages),
    )


class CubeMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.old_path = config.db_path
        self.temp_dir = tempfile.TemporaryDirectory()
        config.db_path = str(Path(self.temp_dir.name) / "cube-migration.sqlite3")
        await storage.close()
        storage._economy_lock = asyncio.Lock()

    async def asyncTearDown(self) -> None:
        await storage.close()
        config.db_path = self.old_path
        self.temp_dir.cleanup()

    async def test_lease_columns_are_added_before_dependent_indexes(self) -> None:
        legacy = sqlite3.connect(config.db_path)
        legacy.executescript(
            """
            CREATE TABLE cube_generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                idle_expires_at TEXT NOT NULL,
                recruitment_started_at TEXT,
                lobby_closes_at TEXT,
                roster_locked_at TEXT,
                closes_at TEXT,
                status TEXT NOT NULL,
                active_slot INTEGER UNIQUE,
                seed INTEGER NOT NULL,
                layout_version INTEGER NOT NULL,
                size INTEGER NOT NULL,
                start_room_id INTEGER NOT NULL,
                prize_room_id INTEGER NOT NULL,
                mandatory_room_id INTEGER NOT NULL,
                reset_minutes INTEGER NOT NULL,
                lobby_seconds INTEGER NOT NULL,
                entry_cost INTEGER NOT NULL,
                prize_per_participant INTEGER NOT NULL,
                max_participants INTEGER NOT NULL,
                participant_count INTEGER,
                prize_amount INTEGER,
                winner_tg_id INTEGER,
                winner_balance_before INTEGER,
                winner_balance_after INTEGER,
                finished_at TEXT,
                finish_reason TEXT,
                tax_processed_at TEXT
            );
            CREATE TABLE cube_waitlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL UNIQUE,
                requested_after_generation_id INTEGER NOT NULL,
                request_key TEXT NOT NULL UNIQUE,
                requested_at TEXT NOT NULL
            );
            CREATE TABLE cube_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generation_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                recipient_tg_id INTEGER,
                subscription_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                sent_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        legacy.commit()
        legacy.close()

        await storage.init()
        await storage.init()
        for table, expected in {
            "cube_generations": {"tax_claim_token", "tax_claim_until"},
            "cube_waitlist": {"claim_token", "claim_until"},
            "cube_notifications": {"claim_token", "claim_until"},
        }.items():
            cursor = await storage._db.execute(f"PRAGMA table_info({table})")
            columns = {row[1] for row in await cursor.fetchall()}
            self.assertTrue(expected <= columns)
        cursor = await storage._db.execute(
            """SELECT name FROM sqlite_master
               WHERE type = 'index' AND name IN
                 ('cube_generations_tax_claim_idx',
                  'cube_notifications_due_idx')"""
        )
        self.assertEqual(
            {"cube_generations_tax_claim_idx", "cube_notifications_due_idx"},
            {row[0] for row in await cursor.fetchall()},
        )


class CubeStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.old_path = config.db_path
        self.temp_dir = tempfile.TemporaryDirectory()
        config.db_path = str(Path(self.temp_dir.name) / "cube.sqlite3")
        await storage.close()
        storage._economy_lock = asyncio.Lock()
        await storage.init()
        self.generation = (
            await storage.bootstrap_cube(_spec(1), clock=lambda: START)
        ).generation_id

    async def asyncTearDown(self) -> None:
        await storage.close()
        config.db_path = self.old_path
        self.temp_dir.cleanup()

    async def _profile(
        self, tg_id: int, *, balance: int = 0, dirty: int = 0
    ) -> None:
        self.assertTrue(
            await storage.create_profile(tg_id, f"u{tg_id}", f"Nick{tg_id}")
        )
        if balance:
            await storage.add_zbucks(tg_id, balance)
        if dirty:
            await storage.add_dirty(tg_id, dirty)

    async def test_entry_hazard_win_and_immediate_rebuild_are_atomic(self) -> None:
        await self._profile(1, balance=1000, dirty=700)
        entered = await storage.enter_cube(
            self.generation, 1, "entry-one", _spec(2), clock=lambda: START
        )
        self.assertEqual("entered", entered.status)
        self.assertEqual(500, entered.balance)
        self.assertEqual(200, await storage.get_dirty(1))

        replay = await storage.enter_cube(
            self.generation,
            1,
            "entry-one",
            _spec(3),
            clock=lambda: START + timedelta(seconds=1),
        )
        self.assertEqual("entered", replay.status)
        self.assertEqual(500, replay.balance)
        resumed = await storage.enter_cube(
            self.generation,
            1,
            "entry-two",
            _spec(3),
            clock=lambda: START + timedelta(seconds=2),
        )
        self.assertEqual("resumed", resumed.status)
        self.assertEqual(500, resumed.balance)

        collision = await storage.move_cube(
            self.generation,
            1,
            0,
            "e",
            _spec(4),
            clock=lambda: START + timedelta(seconds=3),
        )
        self.assertEqual("hazard", collision.status)
        self.assertEqual(1, collision.version)
        missing = await storage.resolve_cube_hazard_and_enter(
            self.generation,
            1,
            collision.version,
            1,
            _spec(4),
            clock=lambda: START + timedelta(seconds=4),
        )
        self.assertEqual("missing_item", missing.status)
        self.assertEqual(2, missing.version)

        await storage.add_item(1, "bait_1", 1)
        opened = await storage.resolve_cube_hazard_and_enter(
            self.generation,
            1,
            missing.version,
            1,
            _spec(4),
            clock=lambda: START + timedelta(seconds=5),
        )
        self.assertEqual("resolved_and_moved", opened.status)
        self.assertEqual(0, await storage.get_item_qty(1, "bait_1"))
        resolved_view = await storage.get_cube_view(1)
        self.assertTrue(resolved_view.room_hazard_resolved)
        self.assertEqual("Nick1", resolved_view.room_resolved_by_nick)

        won = await storage.move_cube(
            self.generation,
            1,
            opened.version,
            "e",
            _spec(99),
            clock=lambda: START + timedelta(seconds=6),
        )
        self.assertEqual("won", won.status)
        self.assertEqual(1000, won.prize_amount)
        self.assertIsNotNone(won.next_generation_id)
        self.assertNotEqual(self.generation, won.next_generation_id)
        self.assertEqual(1500, (await storage.get_profile(1))[3])

        duplicate_win = await storage.move_cube(
            self.generation,
            1,
            opened.version,
            "e",
            _spec(100),
            clock=lambda: START + timedelta(seconds=7),
        )
        self.assertEqual("closed", duplicate_win.status)
        self.assertEqual(1500, (await storage.get_profile(1))[3])
        cursor = await storage._db.execute(
            """SELECT COUNT(*) FROM cube_notifications
               WHERE generation_id = ? AND kind = 'winner_public'""",
            (self.generation,),
        )
        self.assertEqual((1,), await cursor.fetchone())
        tax_jobs = await storage.claim_pending_cube_tax(
            "tax-worker",
            (START + timedelta(seconds=7)).isoformat(),
            (START + timedelta(minutes=1)).isoformat(),
        )
        self.assertEqual([self.generation], [job.generation_id for job in tax_jobs])
        self.assertTrue(
            await storage.cube_tax_claim_is_current(
                self.generation,
                "tax-worker",
                (START + timedelta(seconds=8)).isoformat(),
            )
        )
        reclaimed_tax = await storage.claim_pending_cube_tax(
            "tax-worker-new",
            (START + timedelta(minutes=1)).isoformat(),
            (START + timedelta(minutes=2)).isoformat(),
        )
        self.assertEqual([self.generation], [job.generation_id for job in reclaimed_tax])
        self.assertFalse(
            await storage.cube_tax_claim_is_current(
                self.generation,
                "tax-worker",
                (START + timedelta(minutes=1, seconds=1)).isoformat(),
            )
        )
        self.assertTrue(
            await storage.cube_tax_claim_is_current(
                self.generation,
                "tax-worker-new",
                (START + timedelta(minutes=1, seconds=1)).isoformat(),
            )
        )
        self.assertTrue(
            await storage.mark_cube_tax_processed(
                self.generation,
                "tax-worker-new",
                (START + timedelta(minutes=1, seconds=2)).isoformat(),
            )
        )
        notifications = await storage.claim_cube_notifications(
            "notify-worker",
            (START + timedelta(seconds=7)).isoformat(),
            (START + timedelta(minutes=1)).isoformat(),
        )
        public = [job for job in notifications if job.kind == "winner_public"]
        self.assertEqual(1, len(public))
        self.assertEqual("Nick1", public[0].winner_nick)
        self.assertTrue(
            await storage.mark_cube_notification_sent(
                public[0].notification_id,
                "notify-worker",
                (START + timedelta(seconds=8)).isoformat(),
            )
        )

    async def test_two_simultaneous_winners_create_one_payout_and_generation(self) -> None:
        for tg_id in (1, 2):
            await self._profile(tg_id, balance=1000)
            await storage.add_item(tg_id, "bait_1", 1)
        first = await storage.enter_cube(
            self.generation, 1, "race-entry-1", _spec(2), clock=lambda: START
        )
        second = await storage.enter_cube(
            self.generation,
            2,
            "race-entry-2",
            _spec(2),
            clock=lambda: START + timedelta(seconds=1),
        )
        first_collision = await storage.move_cube(
            self.generation,
            1,
            first.version,
            "e",
            _spec(3),
            clock=lambda: START + timedelta(seconds=2),
        )
        second_collision = await storage.move_cube(
            self.generation,
            2,
            second.version,
            "e",
            _spec(3),
            clock=lambda: START + timedelta(seconds=2),
        )
        first_opened = await storage.resolve_cube_hazard_and_enter(
            self.generation,
            1,
            first_collision.version,
            1,
            _spec(3),
            clock=lambda: START + timedelta(seconds=3),
        )
        second_entered = await storage.move_cube(
            self.generation,
            2,
            second_collision.version,
            "e",
            _spec(3),
            clock=lambda: START + timedelta(seconds=3),
        )
        self.assertEqual("resolved_and_moved", first_opened.status)
        self.assertEqual("moved", second_entered.status)

        results = await asyncio.gather(
            storage.move_cube(
                self.generation,
                1,
                first_opened.version,
                "e",
                _spec(101),
                clock=lambda: START + timedelta(seconds=4),
            ),
            storage.move_cube(
                self.generation,
                2,
                second_entered.version,
                "e",
                _spec(102),
                clock=lambda: START + timedelta(seconds=4),
            ),
        )
        self.assertCountEqual(["won", "closed"], [result.status for result in results])
        winner = next(result for result in results if result.status == "won")
        self.assertEqual(2000, winner.prize_amount)
        balances = [(await storage.get_profile(tg_id))[3] for tg_id in (1, 2)]
        self.assertCountEqual([2500, 500], balances)
        old_view = await storage.get_cube_view(1, self.generation)
        self.assertEqual(2, old_view.participant_count)
        self.assertEqual(2000, old_view.prize_amount)
        cursor = await storage._db.execute(
            "SELECT COUNT(*) FROM cube_generations WHERE active_slot = 1"
        )
        self.assertEqual((1,), await cursor.fetchone())
        cursor = await storage._db.execute(
            """SELECT COUNT(*) FROM cube_notifications
               WHERE generation_id = ? AND kind = 'winner_public'""",
            (self.generation,),
        )
        self.assertEqual((1,), await cursor.fetchone())

    async def test_inventory_writers_do_not_lose_parallel_additions(self) -> None:
        await self._profile(1)
        await asyncio.gather(
            *(storage.add_item(1, "egg", 1) for _ in range(40))
        )
        self.assertEqual(40, await storage.get_item_qty(1, "egg"))
        removed = await asyncio.gather(
            *(storage.remove_item(1, "egg", 1) for _ in range(50))
        )
        self.assertEqual(40, sum(removed))
        self.assertEqual(0, await storage.get_item_qty(1, "egg"))

    async def test_observe_warns_about_hazard_but_never_identifies_prize(self) -> None:
        await self._profile(1, balance=500)
        entered = await storage.enter_cube(
            self.generation, 1, "observe-entry", _spec(2), clock=lambda: START
        )
        observed_hazard = await storage.observe_cube(
            self.generation,
            1,
            entered.version,
            "e",
            _spec(2),
            clock=lambda: START + timedelta(seconds=1),
        )
        self.assertEqual("hazard", observed_hazard.category)
        view = await storage.get_cube_view(1)
        east = next(item for item in view.directions if item.direction == "e")
        self.assertIsNone(east.room_code)
        self.assertEqual("hazard", east.category)
        self.assertTrue(east.hazard_active)

        collision = await storage.move_cube(
            self.generation,
            1,
            entered.version,
            "e",
            _spec(2),
            clock=lambda: START + timedelta(seconds=2),
        )
        await storage.add_item(1, "bait_1", 1)
        opened = await storage.resolve_cube_hazard_and_enter(
            self.generation,
            1,
            collision.version,
            1,
            _spec(2),
            clock=lambda: START + timedelta(seconds=3),
        )
        observed_prize = await storage.observe_cube(
            self.generation,
            1,
            opened.version,
            "e",
            _spec(2),
            clock=lambda: START + timedelta(seconds=4),
        )
        self.assertEqual("unreadable", observed_prize.category)

    async def test_dark_room_observe_cannot_leak_neighbor_category(self) -> None:
        await self._profile(1, balance=500)
        entered = await storage.enter_cube(
            self.generation, 1, "dark-entry", _spec(2), clock=lambda: START
        )
        moved = await storage.move_cube(
            self.generation,
            1,
            entered.version,
            "s",
            _spec(2),
            clock=lambda: START + timedelta(seconds=1),
        )
        self.assertEqual("dark", moved.effect_kind)
        observed = await storage.observe_cube(
            self.generation,
            1,
            moved.version,
            "e",
            _spec(2),
            clock=lambda: START + timedelta(seconds=2),
        )
        self.assertEqual("unreadable", observed.category)

    async def test_failed_entry_request_is_sticky_and_foreign_replay_invalid(self) -> None:
        await self._profile(1)
        await self._profile(2, balance=500)
        failed = await storage.enter_cube(
            self.generation, 1, "sticky", _spec(2), clock=lambda: START
        )
        self.assertEqual("insufficient", failed.status)
        await storage.add_zbucks(1, 500)
        replay = await storage.enter_cube(
            self.generation,
            1,
            "sticky",
            _spec(2),
            clock=lambda: START + timedelta(seconds=1),
        )
        self.assertEqual("insufficient", replay.status)
        self.assertEqual(500, replay.balance)
        foreign = await storage.enter_cube(
            self.generation,
            2,
            "sticky",
            _spec(2),
            clock=lambda: START + timedelta(seconds=1),
        )
        self.assertEqual("invalid", foreign.status)
        self.assertEqual(500, foreign.balance)

    async def test_entry_uses_existing_local_clock_contract_for_hidden_money(self) -> None:
        await self._profile(1, balance=1000, dirty=700)
        local_now = datetime.now()
        hidden = await storage.activate_hidden_money(
            1,
            600,
            (local_now + timedelta(minutes=10)).isoformat(),
            (local_now + timedelta(minutes=20)).isoformat(),
            local_now.isoformat(),
        )
        self.assertEqual(600, hidden)

        unavailable = await storage.enter_cube(
            self.generation,
            1,
            "hidden-entry",
            _spec(2),
            # Cube lifecycle deliberately uses UTC; hidden-money state does not.
            clock=lambda: START,
        )
        self.assertEqual("insufficient", unavailable.status)
        self.assertEqual(1000, unavailable.balance)
        self.assertEqual(700, await storage.get_dirty(1))

        await storage.set_cooldown_until(
            1,
            storage.HIDE_KEY,
            (datetime.now() - timedelta(seconds=1)).isoformat(),
        )
        entered = await storage.enter_cube(
            self.generation,
            1,
            "visible-entry",
            _spec(2),
            clock=lambda: START + timedelta(seconds=1),
        )
        self.assertEqual("entered", entered.status)
        self.assertEqual(500, entered.balance)
        self.assertEqual(200, await storage.get_dirty(1))

    async def test_deadline_clock_is_sampled_after_waiting_for_writer_lock(self) -> None:
        await self._profile(1, balance=500)
        mutable_now = [START]
        await storage._economy_lock.acquire()
        try:
            operation = asyncio.create_task(
                storage.enter_cube(
                    self.generation,
                    1,
                    "late-entry",
                    _spec(2),
                    clock=lambda: mutable_now[0],
                )
            )
            await asyncio.sleep(0)
            mutable_now[0] = START + timedelta(minutes=config.cube_reset_minutes)
        finally:
            storage._economy_lock.release()
        result = await operation
        self.assertEqual("closed", result.status)
        self.assertEqual(500, result.balance)
        self.assertNotEqual(
            self.generation, await storage.get_current_cube_generation_id()
        )

    async def test_timeout_expires_runs_and_creates_one_new_generation(self) -> None:
        await self._profile(1, balance=500)
        await storage.enter_cube(
            self.generation, 1, "entry", _spec(2), clock=lambda: START
        )
        result = await storage.advance_cube_lifecycle(
            _spec(3),
            clock=lambda: START + timedelta(minutes=config.cube_reset_minutes),
        )
        self.assertTrue(result.transitioned)
        self.assertEqual(self.generation, result.closed_generation_id)
        view = await storage.get_cube_view(1, self.generation)
        self.assertEqual("expired", view.generation_status)
        self.assertEqual("expired", view.run_status)
        self.assertEqual(1, view.participant_count)
        self.assertEqual(1000, view.prize_amount)
        cursor = await storage._db.execute(
            "SELECT COUNT(*) FROM cube_generations WHERE active_slot = 1"
        )
        self.assertEqual((1,), await cursor.fetchone())

    async def test_subscribe_is_authoritative_and_cancel_is_versioned(self) -> None:
        await self._profile(1, balance=500)
        await self._profile(2)
        await storage.enter_cube(
            self.generation, 1, "entry", _spec(2), clock=lambda: START
        )
        await storage.advance_cube_lifecycle(
            _spec(3),
            clock=lambda: START + timedelta(seconds=config.cube_lobby_seconds),
        )
        subscribed = await storage.subscribe_cube(
            self.generation,
            2,
            "notify-one",
            _spec(4),
            clock=lambda: START + timedelta(seconds=config.cube_lobby_seconds + 1),
        )
        self.assertEqual("subscribed", subscribed.status)
        replay = await storage.subscribe_cube(
            self.generation,
            2,
            "notify-one",
            _spec(4),
            clock=lambda: START + timedelta(seconds=config.cube_lobby_seconds + 2),
        )
        self.assertEqual("already_subscribed", replay.status)
        cancelled = await storage.cancel_cube_subscription(
            self.generation,
            2,
            subscribed.subscription_id,
            _spec(5),
            clock=lambda: START + timedelta(seconds=config.cube_lobby_seconds + 3),
        )
        self.assertEqual("cancelled", cancelled.status)
        stale = await storage.cancel_cube_subscription(
            self.generation + 1,
            2,
            subscribed.subscription_id,
            _spec(5),
            clock=lambda: START + timedelta(seconds=config.cube_lobby_seconds + 4),
        )
        self.assertEqual("invalid", stale.status)

        resubscribed = await storage.subscribe_cube(
            self.generation,
            2,
            "notify-two",
            _spec(6),
            clock=lambda: START + timedelta(seconds=config.cube_lobby_seconds + 5),
        )
        self.assertEqual("subscribed", resubscribed.status)
        lifecycle = await storage.advance_cube_lifecycle(
            _spec(7),
            clock=lambda: START + timedelta(minutes=config.cube_reset_minutes),
        )
        self.assertNotEqual(self.generation, lifecycle.generation_id)
        invitations = await storage.claim_cube_notifications(
            "invite-worker",
            (START + timedelta(minutes=config.cube_reset_minutes)).isoformat(),
            (START + timedelta(minutes=config.cube_reset_minutes, seconds=30)).isoformat(),
        )
        private = [job for job in invitations if job.kind == "lobby_private"]
        self.assertEqual(1, len(private))
        self.assertEqual(2, private[0].recipient_tg_id)
        self.assertTrue(
            await storage.mark_cube_notification_sent(
                private[0].notification_id,
                "invite-worker",
                (START + timedelta(minutes=config.cube_reset_minutes, seconds=1)).isoformat(),
            )
        )
        self.assertIsNone((await storage.get_cube_view(2)).subscription_id)

    async def test_cancelled_or_expired_claim_is_rechecked_before_invite_send(self) -> None:
        await self._profile(1, balance=500)
        await self._profile(2)
        await storage.enter_cube(
            self.generation, 1, "entry", _spec(2), clock=lambda: START
        )
        await storage.advance_cube_lifecycle(
            _spec(3),
            clock=lambda: START + timedelta(seconds=config.cube_lobby_seconds),
        )
        subscribed = await storage.subscribe_cube(
            self.generation,
            2,
            "notify-race",
            _spec(4),
            clock=lambda: START + timedelta(seconds=config.cube_lobby_seconds + 1),
        )
        rebuilt_at = START + timedelta(minutes=config.cube_reset_minutes)
        lifecycle = await storage.advance_cube_lifecycle(
            _spec(5), clock=lambda: rebuilt_at
        )
        jobs = await storage.claim_cube_notifications(
            "invite-race-worker",
            rebuilt_at.isoformat(),
            (rebuilt_at + timedelta(seconds=30)).isoformat(),
        )
        old_invitation = next(job for job in jobs if job.kind == "lobby_private")
        bot = AsyncMock()

        reclaimed_jobs = await storage.claim_cube_notifications(
            "invite-new-worker",
            (rebuilt_at + timedelta(seconds=30)).isoformat(),
            (
                rebuilt_at
                + timedelta(minutes=config.cube_reset_minutes + 1)
            ).isoformat(),
        )
        invitation = next(
            job for job in reclaimed_jobs if job.kind == "lobby_private"
        )
        sent = await cube_game._send_notification(
            bot,
            old_invitation,
            now=rebuilt_at + timedelta(seconds=31),
        )
        self.assertFalse(sent)
        bot.send_message.assert_not_awaited()

        # Even a still-subscribed notification must not be sent at the exact
        # idle deadline when lifecycle status has not yet been advanced.
        sent = await cube_game._send_notification(
            bot,
            invitation,
            now=rebuilt_at + timedelta(minutes=config.cube_reset_minutes),
        )
        self.assertFalse(sent)
        bot.send_message.assert_not_awaited()

        cancelled = await storage.cancel_cube_subscription(
            self.generation,
            2,
            subscribed.subscription_id,
            _spec(6),
            clock=lambda: rebuilt_at + timedelta(seconds=32),
        )
        self.assertEqual("cancelled", cancelled.status)
        sent = await cube_game._send_notification(
            bot,
            invitation,
            now=rebuilt_at + timedelta(seconds=33),
        )
        self.assertFalse(sent)
        bot.send_message.assert_not_awaited()
        self.assertEqual(lifecycle.generation_id, invitation.generation_id)

    async def test_echo_bounces_only_the_first_player(self) -> None:
        await self._profile(1, balance=500)
        await self._profile(2, balance=500)
        first = await storage.enter_cube(
            self.generation, 1, "echo-first", _spec(2), clock=lambda: START
        )
        second = await storage.enter_cube(
            self.generation,
            2,
            "echo-second",
            _spec(2),
            clock=lambda: START + timedelta(seconds=1),
        )
        first_dark = await storage.move_cube(
            self.generation,
            1,
            first.version,
            "s",
            _spec(2),
            clock=lambda: START + timedelta(seconds=2),
        )
        first_echo = await storage.move_cube(
            self.generation,
            1,
            first_dark.version,
            "e",
            _spec(2),
            clock=lambda: START + timedelta(seconds=3),
        )
        self.assertEqual("bounced", first_echo.status)
        self.assertEqual("echo", first_echo.effect_kind)
        self.assertEqual(4, first_echo.final_room_id)

        second_dark = await storage.move_cube(
            self.generation,
            2,
            second.version,
            "s",
            _spec(2),
            clock=lambda: START + timedelta(seconds=4),
        )
        second_echo = await storage.move_cube(
            self.generation,
            2,
            second_dark.version,
            "e",
            _spec(2),
            clock=lambda: START + timedelta(seconds=5),
        )
        self.assertEqual("moved", second_echo.status)
        self.assertIsNone(second_echo.effect_kind)
        self.assertEqual(5, second_echo.final_room_id)

    async def test_archive_and_transfers_apply_once_without_recursive_chain(self) -> None:
        for tg_id in (1, 2):
            await self._profile(tg_id, balance=500)
        entries = []
        for tg_id in (1, 2):
            entries.append(
                await storage.enter_cube(
                    self.generation,
                    tg_id,
                    f"effects-entry-{tg_id}",
                    _spec(2),
                    clock=lambda: START,
                )
            )

        archive_versions = []
        for tg_id, entry in zip((1, 2), entries):
            dark = await storage.move_cube(
                self.generation,
                tg_id,
                entry.version,
                "s",
                _spec(2),
                clock=lambda: START + timedelta(seconds=1),
            )
            archive = await storage.move_cube(
                self.generation,
                tg_id,
                dark.version,
                "s",
                _spec(2),
                clock=lambda: START + timedelta(seconds=2),
            )
            self.assertEqual("archive", archive.effect_kind)
            self.assertEqual(8, archive.final_room_id)
            archive_versions.append(archive.version)

        archive_view = await storage.get_cube_view(1)
        east = next(item for item in archive_view.directions if item.direction == "e")
        self.assertEqual("anomaly", east.category)
        self.assertIsNone(east.room_code)

        tunnel = await storage.move_cube(
            self.generation,
            1,
            archive_versions[0],
            "e",
            _spec(2),
            clock=lambda: START + timedelta(seconds=3),
        )
        self.assertEqual("tunnel", tunnel.effect_kind)
        self.assertEqual("410", tunnel.effect_arg)
        # Room 10 is itself the paired tunnel, but its effect is not recursed.
        self.assertEqual(10, tunnel.final_room_id)

        vector = await storage.move_cube(
            self.generation,
            2,
            archive_versions[1],
            "s",
            _spec(2),
            clock=lambda: START + timedelta(seconds=3),
        )
        self.assertEqual("vector", vector.effect_kind)
        self.assertEqual("413", vector.effect_arg)
        self.assertEqual(13, vector.final_room_id)


if __name__ == "__main__":
    unittest.main()
