"""Узкие проверки теневого дела комарих и его durable-таймлайна."""
import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from config import config
from db import storage
from game import business
from content import illegal_business as illegal_text


class _StorageCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._old_db_path = config.db_path
        self._temp_dir = tempfile.TemporaryDirectory()
        config.db_path = str(Path(self._temp_dir.name) / "illegal.sqlite3")
        await storage.close()
        storage._economy_lock = asyncio.Lock()
        await storage.init()

    async def asyncTearDown(self) -> None:
        await storage.close()
        config.db_path = self._old_db_path
        self._temp_dir.cleanup()

    async def _profile(self, balance: int = 100_000, tg_id: int = 1) -> None:
        self.assertTrue(await storage.create_profile(tg_id, f"user{tg_id}", f"Nick{tg_id}"))
        if balance:
            await storage.add_zbucks(tg_id, balance)

    async def _parent(self, tg_id: int = 1, now: datetime | None = None) -> None:
        now = now or datetime(2026, 7, 24, 12, 0)
        self.assertTrue(await storage.create_business(
            tg_id,
            business.BIZ_MOSQUITO,
            business.TIER_SMALL,
            (now + timedelta(hours=1)).isoformat(),
            (now + timedelta(days=1)).isoformat(),
        ))

    async def _illegal(
        self,
        now: datetime,
        *,
        balance: int = 100_000,
        upkeep_at: datetime | None = None,
    ) -> None:
        await self._profile(balance)
        await self._parent(now=now)
        self.assertEqual(
            "ok",
            await storage.buy_illegal_business_atomic(
                1,
                business.BIZ_ILLEGAL_MOSQUITO,
                business.ILLEGAL_MOSQUITO_PARENT,
                business.ILLEGAL_MOSQUITO_PRICE,
                (now + timedelta(hours=1)).isoformat(),
                (upkeep_at or now + timedelta(days=1)).isoformat(),
            ),
        )


class IllegalStageTests(unittest.TestCase):
    def test_stage_table_messages_cash_and_probability_boundaries(self) -> None:
        expected = (
            (1, 50, 50, 3),
            (2, 100, 150, 5),
            (3, 200, 350, 10),
            (4, 400, 750, 15),
            (5, 800, 1_550, 30),
            (6, 1_600, 3_150, 50),
            (7, 3_200, 6_350, 60),
            (8, 6_400, 12_750, 100),
        )
        self.assertEqual(expected, tuple(
            (entry.hour, entry.income, entry.cash, entry.theft_chance)
            for entry in business.ILLEGAL_STAGES.values()
        ))
        self.assertEqual(illegal_text.STAGE_MESSAGES[8], business.illegal_stage_message(8))

        first = business.advance_illegal_stage(0, 0)
        self.assertEqual(("advanced", 1, 50, 0),
                         (first.kind, first.to_stage, first.cash_after, first.theft_chance))
        for stage, _income, cash, chance in expected[:-1]:
            stolen = business.advance_illegal_stage(stage, cash, roll=chance)
            self.assertTrue(stolen.stolen)
            self.assertEqual(0, stolen.cash_after)
            survived = business.advance_illegal_stage(stage, cash, roll=chance + 1)
            self.assertEqual("advanced", survived.kind)
            self.assertEqual(cash + expected[stage][1], survived.cash_after)
        self.assertTrue(business.advance_illegal_stage(8, 12_750, roll=100).stolen)


class IllegalBusinessStorageTests(_StorageCase):
    async def test_purchase_requires_parent_and_parallel_purchase_charges_once(self) -> None:
        now = datetime(2026, 7, 24, 12, 0)
        await self._profile(balance=60_000)
        args = (
            1, business.BIZ_ILLEGAL_MOSQUITO, business.ILLEGAL_MOSQUITO_PARENT,
            business.ILLEGAL_MOSQUITO_PRICE, (now + timedelta(hours=1)).isoformat(),
            (now + timedelta(days=1)).isoformat(),
        )
        self.assertEqual("parent_not_owned", await storage.buy_illegal_business_atomic(*args))
        await self._parent(now=now)
        results = await asyncio.gather(
            storage.buy_illegal_business_atomic(*args),
            storage.buy_illegal_business_atomic(*args),
        )
        self.assertEqual(["already_owned", "ok"], sorted(results))
        self.assertEqual(30_000, (await storage.get_profile(1))[3])
        row = await storage.get_illegal_business(1, business.BIZ_ILLEGAL_MOSQUITO)
        self.assertEqual((business.ILLEGAL_MOSQUITO_PARENT, 1, 0, 0),
                         (row.parent_biz, row.level, row.stage, row.accrued))

    async def test_timeline_accumulates_eight_hours_then_ninth_is_guaranteed_theft(self) -> None:
        start = datetime(2026, 7, 24, 12, 0)
        await self._illegal(start)
        with patch.object(business.random, "randint", return_value=100):
            await business.settle_illegal_timeline(
                None, 1, business.BIZ_ILLEGAL_MOSQUITO, start + timedelta(hours=8),
            )
        row = await storage.get_illegal_business(1, business.BIZ_ILLEGAL_MOSQUITO)
        self.assertEqual((8, 12_750), (row.stage, row.accrued))

        with patch.object(business.random, "randint", return_value=100):
            await business.settle_illegal_timeline(
                None, 1, business.BIZ_ILLEGAL_MOSQUITO, start + timedelta(hours=9),
            )
        row = await storage.get_illegal_business(1, business.BIZ_ILLEGAL_MOSQUITO)
        self.assertEqual((0, 0), (row.stage, row.accrued))
        self.assertEqual((start + timedelta(hours=10)).isoformat(), row.next_hour_at)

    async def test_long_downtime_replays_hours_before_daily_salary(self) -> None:
        start = datetime(2026, 7, 24, 12, 0)
        await self._illegal(start)
        # На 25-м часу сначала должны проиграться 23 старых часа, затем
        # зарплата на 24-м, и только потом ещё два часа нового дня.
        with patch.object(business.random, "randint", return_value=100):
            await business.settle_illegal_timeline(
                None, 1, business.BIZ_ILLEGAL_MOSQUITO, start + timedelta(hours=25),
            )
        row = await storage.get_illegal_business(1, business.BIZ_ILLEGAL_MOSQUITO)
        self.assertEqual((7, 6_350), (row.stage, row.accrued))
        self.assertEqual((start + timedelta(hours=26)).isoformat(), row.next_hour_at)
        self.assertEqual((start + timedelta(days=2)).isoformat(), row.upkeep_at)
        self.assertEqual(69_700, (await storage.get_profile(1))[3])

    async def test_collect_is_dirty_single_use_and_refuses_to_skip_due_hour(self) -> None:
        start = datetime(2026, 7, 24, 12, 0)
        await self._illegal(start)
        await business.settle_illegal_timeline(
            None, 1, business.BIZ_ILLEGAL_MOSQUITO, start + timedelta(hours=1),
        )
        row = await storage.get_illegal_business(1, business.BIZ_ILLEGAL_MOSQUITO)
        self.assertEqual((1, 50), (row.stage, row.accrued))
        due = datetime.fromisoformat(row.next_hour_at)
        self.assertEqual(
            "hour_due",
            (await storage.collect_illegal_income_atomic(
                1, row.biz, due.isoformat(), (due + timedelta(hours=1)).isoformat(),
            )).status,
        )

        collect_now = start + timedelta(hours=1, minutes=1)
        reset_at = collect_now + timedelta(hours=1)
        results = await asyncio.gather(
            storage.collect_illegal_income_atomic(1, row.biz, collect_now.isoformat(), reset_at.isoformat()),
            storage.collect_illegal_income_atomic(1, row.biz, collect_now.isoformat(), reset_at.isoformat()),
        )
        self.assertEqual(["empty", "ok"], sorted(result.status for result in results))
        self.assertEqual(50, [result.amount for result in results if result.status == "ok"][0])
        self.assertEqual(50, await storage.get_dirty(1))
        self.assertEqual(70_050, (await storage.get_profile(1))[3])
        row = await storage.get_illegal_business(1, business.BIZ_ILLEGAL_MOSQUITO)
        self.assertEqual((0, 0, reset_at.isoformat()), (row.stage, row.accrued, row.next_hour_at))

    async def test_progress_cas_and_future_salary_are_rejected(self) -> None:
        start = datetime(2026, 7, 24, 12, 0)
        await self._illegal(start)
        row = await storage.get_illegal_business(1, business.BIZ_ILLEGAL_MOSQUITO)
        stale = await storage.advance_illegal_business_atomic(
            1,
            row.biz,
            row.revision + 1,
            row.next_hour_at,
            1,
            50,
            (start + timedelta(hours=2)).isoformat(),
            (start + timedelta(hours=1)).isoformat(),
        )
        self.assertEqual("stale", stale.status)
        self.assertEqual((0, 0), ((await storage.get_illegal_business(1, row.biz)).stage,
                                  (await storage.get_illegal_business(1, row.biz)).accrued))

        before = (await storage.get_profile(1))[3]
        future = await storage.settle_illegal_upkeep_atomic(
            1,
            row.biz,
            300,
            start.isoformat(),
            row.upkeep_at,
            (datetime.fromisoformat(row.upkeep_at) + timedelta(days=1)).isoformat(),
            None,
        )
        self.assertEqual("not_due", future.status)
        self.assertEqual(before, (await storage.get_profile(1))[3])

    async def test_unpaid_salary_pauses_without_losing_pot_and_resume_restarts_hour(self) -> None:
        start = datetime(2026, 7, 24, 12, 0)
        # После покупки денег не остаётся: в момент зарплаты ей нечем платить.
        await self._illegal(start, balance=30_000, upkeep_at=start + timedelta(hours=2))
        await storage.set_business_paused(1, business.BIZ_MOSQUITO, True)
        # Пауза родителя не влияет: первый час теневой схемы всё равно проходит.
        await business.settle_illegal_timeline(
            None, 1, business.BIZ_ILLEGAL_MOSQUITO, start + timedelta(hours=1),
        )
        before_pause = await storage.get_illegal_business(1, business.BIZ_ILLEGAL_MOSQUITO)
        self.assertEqual((False, 1, 50), (before_pause.paused, before_pause.stage, before_pause.accrued))

        with patch.object(business.random, "randint", return_value=100):
            await business.settle_illegal_timeline(
                None, 1, business.BIZ_ILLEGAL_MOSQUITO, start + timedelta(hours=2),
            )
        paused = await storage.get_illegal_business(1, business.BIZ_ILLEGAL_MOSQUITO)
        self.assertEqual((True, 1, 50), (paused.paused, paused.stage, paused.accrued))

        await storage.add_zbucks(1, 300)
        resume_at = datetime.fromisoformat(paused.upkeep_at)
        await business.settle_illegal_timeline(None, 1, business.BIZ_ILLEGAL_MOSQUITO, resume_at)
        resumed = await storage.get_illegal_business(1, business.BIZ_ILLEGAL_MOSQUITO)
        self.assertEqual((False, 1, 50), (resumed.paused, resumed.stage, resumed.accrued))
        self.assertEqual((resume_at + timedelta(hours=1)).isoformat(), resumed.next_hour_at)


class IllegalBusinessMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_init_adds_illegal_business_table_to_legacy_database(self) -> None:
        old_path = config.db_path
        temp_dir = tempfile.TemporaryDirectory()
        path = Path(temp_dir.name) / "legacy.sqlite3"
        config.db_path = str(path)
        legacy = sqlite3.connect(path)
        legacy.executescript(
            """
            CREATE TABLE profiles (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                nick TEXT UNIQUE,
                zbucks INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )
        legacy.commit()
        legacy.close()
        try:
            await storage.close()
            storage._economy_lock = asyncio.Lock()
            await storage.init()
            self.assertEqual([], await storage.list_illegal_businesses(1))
            await storage.close()
            check = sqlite3.connect(path)
            tables = {row[0] for row in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )}
            check.close()
            self.assertIn("illegal_businesses", tables)
        finally:
            await storage.close()
            config.db_path = old_path
            temp_dir.cleanup()
