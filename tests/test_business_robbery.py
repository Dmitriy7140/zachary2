"""Атомарные правила налётов вора на чужие предприятия."""
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from config import config
from content.thief import business_robbery_chat
from db import storage
from game.business import BIZ_ILLEGAL_MOSQUITO, BIZ_MOSQUITO, BIZ_SLUGS
from game.items import ITEMS
from game.thief import business_robbery_products


class BusinessRobberyAnnouncementTests(unittest.TestCase):
    def test_thread_message_names_every_participant_and_the_loot(self) -> None:
        message = business_robbery_chat(
            thief='<a href="tg://user?id=1">Ворюга</a>',
            owner="Барыга",
            business="АО Мрачные Сосалы",
            loot="<b>1 500 Z</b>",
        )

        self.assertIn("Ворюга", message)
        self.assertIn("Барыга", message)
        self.assertIn("АО Мрачные Сосалы", message)
        self.assertIn("1 500 Z", message)


class BusinessRobberyStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._old_db_path = config.db_path
        self._temp_dir = tempfile.TemporaryDirectory()
        config.db_path = str(Path(self._temp_dir.name) / "business_robbery.sqlite3")
        await storage.close()
        storage._economy_lock = asyncio.Lock()
        await storage.init()
        await self._profile(1, "Thief")
        await self._profile(2, "Owner")

    async def asyncTearDown(self) -> None:
        await storage.close()
        config.db_path = self._old_db_path
        self._temp_dir.cleanup()

    async def _profile(self, tg_id: int, nick: str) -> None:
        self.assertTrue(await storage.create_profile(tg_id, f"user{tg_id}", nick))

    async def _crowbar(self, tg_id: int) -> None:
        await storage.add_item(tg_id, "crowbar", 1, ITEMS["crowbar"].max_qty)

    async def _legal_business(self, biz: str = BIZ_MOSQUITO) -> None:
        now = datetime.now()
        self.assertTrue(await storage.create_business(
            2,
            biz,
            "small",
            (now + timedelta(hours=1)).isoformat(),
            (now + timedelta(days=1)).isoformat(),
        ))

    def _robbery_args(self) -> dict:
        now = datetime.now()
        return {
            "now_iso": now.isoformat(),
            "success_cooldown_until": (now + timedelta(hours=24)).isoformat(),
            "empty_cooldown_until": (now + timedelta(hours=1)).isoformat(),
            "illegal_next_hour_at": (now + timedelta(hours=1)).isoformat(),
        }

    async def _rob(self, owner: int, biz: str, *, products=()):
        return await storage.rob_business_atomic(
            1, owner, biz, legal_products=products, **self._robbery_args(),
        )

    async def test_laundered_money_moves_once_and_increments_thief(self) -> None:
        await self._crowbar(1)
        await self._legal_business()
        await storage.add_laundering(2, 1_500, (datetime.now() + timedelta(days=1)).isoformat(), BIZ_MOSQUITO)

        result = await self._rob(2, BIZ_MOSQUITO, products=business_robbery_products(BIZ_MOSQUITO))

        self.assertEqual("robbed_laundered", result.status)
        self.assertEqual(1_500, result.amount)
        self.assertEqual(0, await storage.laundering_active_sum(2, BIZ_MOSQUITO))
        thief = await storage.get_profile(1)
        self.assertEqual((1_500, 1_500), (thief[3], await storage.get_dirty(1)))
        self.assertEqual(1, await storage.get_thefts(1))
        self.assertEqual(1_500, await storage.player_stat(1, "thief_won"))
        self.assertEqual(1_500, await storage.player_stat(1, "thief_best_score"))

    async def test_products_are_limited_by_thief_inventory_capacity(self) -> None:
        await self._crowbar(1)
        await self._legal_business(BIZ_SLUGS)
        await storage.add_item(1, "slime_pie", 98, ITEMS["slime_pie"].max_qty)
        await storage.add_item(2, "slime_pie", 5, ITEMS["slime_pie"].max_qty)

        result = await self._rob(2, BIZ_SLUGS, products=business_robbery_products(BIZ_SLUGS))

        self.assertEqual("robbed_products", result.status)
        self.assertEqual((("slime_pie", 1),), result.products)
        self.assertEqual(99, await storage.get_item_qty(1, "slime_pie"))
        self.assertEqual(4, await storage.get_item_qty(2, "slime_pie"))

    async def test_empty_business_sets_short_cooldown_without_locking_target(self) -> None:
        await self._crowbar(1)
        await self._legal_business()

        result = await self._rob(2, BIZ_MOSQUITO, products=business_robbery_products(BIZ_MOSQUITO))
        retry = await self._rob(2, BIZ_MOSQUITO, products=business_robbery_products(BIZ_MOSQUITO))

        self.assertEqual("empty", result.status)
        self.assertEqual("cooldown", retry.status)
        self.assertIsNotNone(result.cooldown_until)

    async def test_secret_business_requires_and_then_uses_legal_robbery_access(self) -> None:
        await self._crowbar(1)
        await self._legal_business()
        now = datetime.now()
        await storage.add_zbucks(2, 1)
        self.assertEqual(
            "ok",
            await storage.buy_illegal_business_atomic(
                2,
                BIZ_ILLEGAL_MOSQUITO,
                BIZ_MOSQUITO,
                1,
                (now - timedelta(seconds=1)).isoformat(),
                (now + timedelta(days=1)).isoformat(),
            ),
        )
        illegal = await storage.get_illegal_business(2, BIZ_ILLEGAL_MOSQUITO)
        self.assertEqual(
            "advanced",
            (await storage.advance_illegal_business_atomic(
                2,
                BIZ_ILLEGAL_MOSQUITO,
                illegal.revision,
                illegal.next_hour_at,
                1,
                50,
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
            )).status,
        )
        before = await storage.list_business_robbery_targets(1)
        self.assertNotIn(BIZ_ILLEGAL_MOSQUITO, [target.biz for target in before])

        await storage.add_laundering(2, 100, (now + timedelta(days=1)).isoformat(), BIZ_MOSQUITO)
        self.assertEqual("robbed_laundered", (await self._rob(
            2, BIZ_MOSQUITO, products=business_robbery_products(BIZ_MOSQUITO),
        )).status)
        await storage.set_cooldown_until(1, "business_robbery", (now - timedelta(seconds=1)).isoformat())

        after = await storage.list_business_robbery_targets(1)
        self.assertIn(BIZ_ILLEGAL_MOSQUITO, [target.biz for target in after])
        result = await self._rob(2, BIZ_ILLEGAL_MOSQUITO)

        self.assertEqual("robbed_illegal_cash", result.status)
        self.assertEqual(50, result.amount)
        self.assertEqual(0, (await storage.get_illegal_business(2, BIZ_ILLEGAL_MOSQUITO)).accrued)

    async def test_concurrent_raids_do_not_duplicate_laundered_money(self) -> None:
        await self._profile(3, "SecondThief")
        await self._crowbar(1)
        await self._crowbar(3)
        await self._legal_business()
        await storage.add_laundering(2, 1_000, (datetime.now() + timedelta(days=1)).isoformat(), BIZ_MOSQUITO)

        args = self._robbery_args()
        first, second = await asyncio.gather(
            storage.rob_business_atomic(
                1, 2, BIZ_MOSQUITO,
                legal_products=business_robbery_products(BIZ_MOSQUITO), **args,
            ),
            storage.rob_business_atomic(
                3, 2, BIZ_MOSQUITO,
                legal_products=business_robbery_products(BIZ_MOSQUITO), **args,
            ),
        )

        self.assertEqual(
            ["business_cooldown", "robbed_laundered"],
            sorted((first.status, second.status)),
        )
        self.assertEqual(1_000, (await storage.get_profile(1))[3] + (await storage.get_profile(3))[3])
        self.assertEqual(0, await storage.laundering_active_sum(2, BIZ_MOSQUITO))


if __name__ == "__main__":
    unittest.main()
