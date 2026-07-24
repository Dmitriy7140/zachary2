"""Узкие проверки легальных бизнесов, слизней и палеты рынка."""
import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from config import config
from db import storage
from game import business
from game.items import ITEMS, sellable_items


class _StorageCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._old_db_path = config.db_path
        self._temp_dir = tempfile.TemporaryDirectory()
        config.db_path = str(Path(self._temp_dir.name) / "business.sqlite3")
        await storage.close()
        storage._economy_lock = asyncio.Lock()
        await storage.init()

    async def asyncTearDown(self) -> None:
        await storage.close()
        config.db_path = self._old_db_path
        self._temp_dir.cleanup()

    async def _profile(self, tg_id: int = 1, balance: int = 0) -> None:
        self.assertTrue(await storage.create_profile(tg_id, f"user{tg_id}", f"Nick{tg_id}"))
        if balance:
            await storage.add_zbucks(tg_id, balance)

    async def _slug_business(self, tg_id: int = 1, balance: int = 100_000) -> None:
        await self._profile(tg_id, balance)
        await storage.set_self_employed(tg_id)
        now = datetime(2026, 7, 24, 12, 0, 0)
        self.assertEqual(
            "ok",
            await storage.buy_business_atomic(
                tg_id,
                business.BIZ_SLUGS,
                business.TIER_SMALL,
                business.SLUG_PRICE,
                None,
                (now + timedelta(days=1)).isoformat(),
            ),
        )


class ItemRegistryTests(unittest.TestCase):
    def test_slug_products_are_market_only_and_have_requested_limits(self) -> None:
        expected = {
            "slime_pie": ("«Пирожок» с яйцом", 200, 230),
            "slime_pita": ("«Пита» с кукурузой", 240, 270),
            "slime_dranik": ("«Дранник» с картошкой", 270, 300),
        }
        sellable = {item.key for item in sellable_items()}
        for key, (name, low, high) in expected.items():
            item = ITEMS[key]
            self.assertEqual(name, item.name)
            self.assertEqual(99, item.max_qty)
            self.assertIsNone(item.price)
            self.assertEqual((low, high, 10),
                             (item.sell_min, item.sell_max, item.sell_minutes_per_z))
            self.assertIn(key, sellable)


class BusinessStorageTests(_StorageCase):
    async def test_buy_and_upgrade_are_single_use(self) -> None:
        await self._profile(balance=100_000)
        await storage.set_self_employed(1)
        now = datetime.now()
        bought = await storage.buy_business_atomic(
            1, business.BIZ_SLUGS, business.TIER_SMALL, business.SLUG_PRICE,
            None, (now + timedelta(days=1)).isoformat(),
        )
        self.assertEqual("ok", bought)
        self.assertEqual(
            "already_owned",
            await storage.buy_business_atomic(
                1, business.BIZ_SLUGS, business.TIER_SMALL, business.SLUG_PRICE,
                None, (now + timedelta(days=1)).isoformat(),
            ),
        )
        self.assertEqual(
            "ok",
            await storage.upgrade_business_atomic(
                1, business.BIZ_SLUGS, expected_level=1,
                price=business.SLUG_UPGRADE2_PRICE,
            ),
        )
        self.assertEqual(
            "stale",
            await storage.upgrade_business_atomic(
                1, business.BIZ_SLUGS, expected_level=1,
                price=business.SLUG_UPGRADE2_PRICE,
            ),
        )
        row = await storage.get_business(1, business.BIZ_SLUGS)
        self.assertEqual(2, row[1])
        self.assertEqual(
            "ok",
            await storage.upgrade_business_atomic(
                1, business.BIZ_SLUGS, expected_level=2,
                price=business.SLUG_UPGRADE3_PRICE,
            ),
        )
        self.assertEqual(
            "max_level",
            await storage.upgrade_business_atomic(
                1, business.BIZ_SLUGS, expected_level=3, price=1,
            ),
        )
        self.assertEqual(3, (await storage.get_business(1, business.BIZ_SLUGS))[1])

    async def test_slug_cooking_limits_ingredients_and_delivery(self) -> None:
        await self._slug_business()
        await storage.add_item(1, "egg", 25, ITEMS["egg"].max_qty)
        ready_at = (datetime.now() - timedelta(seconds=1)).isoformat()
        recipe = business.get_slug_recipe("slime_pie")
        self.assertEqual(
            "ok",
            await storage.start_slug_cooking_atomic(
                1, recipe.item, recipe.ingredient, recipe.ingredient_qty,
                recipe.unlock_level, 5, ready_at,
            ),
        )
        self.assertEqual(0, await storage.get_item_qty(1, "egg"))
        self.assertEqual(
            "limit",
            await storage.start_slug_cooking_atomic(
                1, recipe.item, recipe.ingredient, recipe.ingredient_qty,
                recipe.unlock_level, 1, ready_at,
            ),
        )
        self.assertEqual([(1, "slime_pie", 5)], await storage.settle_due_slug_cooks(
            datetime.now().isoformat()))
        self.assertEqual(5, await storage.get_item_qty(1, "slime_pie"))
        self.assertEqual([], await storage.settle_due_slug_cooks(datetime.now().isoformat()))

    async def test_slug_cooking_reserves_inventory_space(self) -> None:
        await self._slug_business()
        await storage.add_item(1, "slime_pie", 98, ITEMS["slime_pie"].max_qty)
        await storage.add_item(1, "egg", 10, ITEMS["egg"].max_qty)
        recipe = business.get_slug_recipe("slime_pie")
        ready_at = (datetime.now() + timedelta(minutes=15)).isoformat()
        self.assertEqual(
            "inventory_full",
            await storage.start_slug_cooking_atomic(
                1, recipe.item, recipe.ingredient, recipe.ingredient_qty,
                recipe.unlock_level, 2, ready_at,
            ),
        )
        self.assertEqual(
            "ok",
            await storage.start_slug_cooking_atomic(
                1, recipe.item, recipe.ingredient, recipe.ingredient_qty,
                recipe.unlock_level, 1, ready_at,
            ),
        )

    async def test_slug_recipes_have_levels_shared_queue_and_independent_timers(self) -> None:
        await self._slug_business()
        pie = business.get_slug_recipe("slime_pie")
        pita = business.get_slug_recipe("slime_pita")
        dranik = business.get_slug_recipe("slime_dranik")
        now = datetime.now()

        # Второй и третий рецепт не обходят уровни даже при прямом storage-вызове.
        self.assertEqual(
            "locked",
            await storage.start_slug_cooking_atomic(
                1, pita.item, pita.ingredient, pita.ingredient_qty,
                pita.unlock_level, 1, (now + timedelta(minutes=20)).isoformat(),
            ),
        )
        self.assertEqual(
            "locked",
            await storage.start_slug_cooking_atomic(
                1, dranik.item, dranik.ingredient, dranik.ingredient_qty,
                dranik.unlock_level, 1, (now + timedelta(minutes=25)).isoformat(),
            ),
        )
        self.assertEqual(
            "ok",
            await storage.upgrade_business_atomic(
                1, business.BIZ_SLUGS, 1, business.SLUG_UPGRADE2_PRICE,
            ),
        )
        await storage.add_item(1, "egg", 15, ITEMS["egg"].max_qty)
        await storage.add_item(1, "corn", 12, ITEMS["corn"].max_qty)
        early = (now - timedelta(seconds=1)).isoformat()
        later = (now + timedelta(minutes=20)).isoformat()
        self.assertEqual(
            "ok",
            await storage.start_slug_cooking_atomic(
                1, pie.item, pie.ingredient, pie.ingredient_qty,
                pie.unlock_level, 2, early,
            ),
        )
        self.assertEqual(
            "ok",
            await storage.start_slug_cooking_atomic(
                1, pita.item, pita.ingredient, pita.ingredient_qty,
                pita.unlock_level, 3, later,
            ),
        )
        # Пять мест общие: третий рецепт или другой вид не получает шестое.
        self.assertEqual(
            "limit",
            await storage.start_slug_cooking_atomic(
                1, pie.item, pie.ingredient, pie.ingredient_qty,
                pie.unlock_level, 1, later,
            ),
        )
        self.assertEqual(
            [(1, "slime_pie", 2)],
            await storage.settle_due_slug_cooks(now.isoformat()),
        )
        self.assertEqual(2, await storage.get_item_qty(1, "slime_pie"))
        self.assertEqual(0, await storage.get_item_qty(1, "slime_pita"))
        self.assertEqual(
            [(1, "slime_pita", 3)],
            await storage.settle_due_slug_cooks((now + timedelta(minutes=21)).isoformat()),
        )
        self.assertEqual(3, await storage.get_item_qty(1, "slime_pita"))
        # На уровне 2 «Дранник» остаётся закрытым.
        self.assertEqual(
            "locked",
            await storage.start_slug_cooking_atomic(
                1, dranik.item, dranik.ingredient, dranik.ingredient_qty,
                dranik.unlock_level, 1, later,
            ),
        )
        self.assertEqual(
            "ok",
            await storage.upgrade_business_atomic(
                1, business.BIZ_SLUGS, 2, business.SLUG_UPGRADE3_PRICE,
            ),
        )
        await storage.add_item(1, "potato", 3, ITEMS["potato"].max_qty)
        self.assertEqual(
            "ok",
            await storage.start_slug_cooking_atomic(
                1, dranik.item, dranik.ingredient, dranik.ingredient_qty,
                dranik.unlock_level, 1, later,
            ),
        )

    async def test_paused_slug_business_blocks_new_cooking_but_finishes_old(self) -> None:
        await self._slug_business()
        recipe = business.get_slug_recipe("slime_pie")
        await storage.add_item(1, "egg", 10, ITEMS["egg"].max_qty)
        ready_at = (datetime.now() - timedelta(seconds=1)).isoformat()
        self.assertEqual(
            "ok",
            await storage.start_slug_cooking_atomic(
                1, recipe.item, recipe.ingredient, recipe.ingredient_qty,
                recipe.unlock_level, 1, ready_at,
            ),
        )
        await storage.set_business_paused(1, business.BIZ_SLUGS, True)
        self.assertEqual(
            "paused",
            await storage.start_slug_cooking_atomic(
                1, recipe.item, recipe.ingredient, recipe.ingredient_qty,
                recipe.unlock_level, 1, ready_at,
            ),
        )
        self.assertEqual(
            [(1, "slime_pie", 1)],
            await storage.settle_due_slug_cooks(datetime.now().isoformat()),
        )

    async def test_concurrent_slug_cooking_uses_only_five_shared_slots(self) -> None:
        await self._slug_business()
        recipe = business.get_slug_recipe("slime_pie")
        await storage.add_item(1, "egg", 30, ITEMS["egg"].max_qty)
        ready_at = (datetime.now() + timedelta(minutes=15)).isoformat()
        results = await asyncio.gather(
            storage.start_slug_cooking_atomic(
                1, recipe.item, recipe.ingredient, recipe.ingredient_qty,
                recipe.unlock_level, 3, ready_at,
            ),
            storage.start_slug_cooking_atomic(
                1, recipe.item, recipe.ingredient, recipe.ingredient_qty,
                recipe.unlock_level, 3, ready_at,
            ),
        )
        self.assertEqual(["limit", "ok"], sorted(results))
        self.assertEqual(3, len(await storage.list_slug_cooks(1)))

    async def test_scoped_laundering_and_dranik_spend_are_atomic(self) -> None:
        await self._slug_business()
        await storage.add_zbucks(1, 5_000)
        await storage.add_dirty(1, 5_000)
        ready_at = (datetime.now() - timedelta(seconds=1)).isoformat()
        self.assertEqual(
            "ok",
            await storage.start_laundering_atomic(
                1, business.BIZ_SLUGS, 1_000, ready_at, business.launder_cap_for(1),
            ),
        )
        self.assertEqual(1_000, await storage.laundering_active_sum(1, business.BIZ_SLUGS))
        self.assertEqual(0, await storage.laundering_active_sum(1, business.BIZ_MOSQUITO))
        self.assertEqual([(1, business.BIZ_SLUGS, 1_000)],
                         await storage.settle_due_laundering(datetime.now().isoformat()))

        await storage.add_item(1, "slime_dranik", 1, ITEMS["slime_dranik"].max_qty)
        before = (await storage.get_profile(1))[3]
        self.assertEqual("ok", await storage.consume_item_for_zbucks(1, "slime_dranik", 100))
        self.assertEqual(0, await storage.get_item_qty(1, "slime_dranik"))
        self.assertEqual(before - 100, (await storage.get_profile(1))[3])
        self.assertEqual("no_item", await storage.consume_item_for_zbucks(1, "slime_dranik", 100))

        await self._profile(tg_id=2, balance=99)
        await storage.add_item(2, "slime_dranik", 1, ITEMS["slime_dranik"].max_qty)
        self.assertEqual(
            "insufficient",
            await storage.consume_item_for_zbucks(2, "slime_dranik", 100),
        )
        self.assertEqual(1, await storage.get_item_qty(2, "slime_dranik"))
        self.assertEqual(99, (await storage.get_profile(2))[3])

    async def test_laundering_details_keep_sequential_balance_snapshots(self) -> None:
        await self._slug_business()
        await storage.add_dirty(1, 2_000)
        ready_at = (datetime.now() - timedelta(seconds=1)).isoformat()
        before = (await storage.get_profile(1))[3]
        for _ in range(2):
            self.assertEqual(
                "ok",
                await storage.start_laundering_atomic(
                    1, business.BIZ_SLUGS, 1_000, ready_at, business.launder_cap_for(1),
                ),
            )
        settlements = await storage.settle_due_laundering_details(datetime.now().isoformat())
        self.assertEqual([before - 2_000, before - 1_000],
                         [entry.balance_before for entry in settlements])
        self.assertEqual([before - 1_000, before],
                         [entry.balance_after for entry in settlements])

    async def test_upkeep_settlement_is_single_use(self) -> None:
        await self._slug_business()
        now = datetime.now()
        await storage.set_upkeep_at(
            1, business.BIZ_SLUGS, (now - timedelta(seconds=1)).isoformat(),
        )
        before = (await storage.get_profile(1))[3]
        results = await asyncio.gather(
            storage.settle_business_upkeep_atomic(
                1, business.BIZ_SLUGS, 300, now.isoformat(),
                (now + timedelta(days=1)).isoformat(),
            ),
            storage.settle_business_upkeep_atomic(
                1, business.BIZ_SLUGS, 300, now.isoformat(),
                (now + timedelta(days=1)).isoformat(),
            ),
        )
        self.assertEqual(["not_due", "paid"], sorted(result.status for result in results))
        self.assertEqual(before - 300, (await storage.get_profile(1))[3])


class MarketPalletStorageTests(_StorageCase):
    async def test_pallet_upgrades_once_and_lifts_listing_capacity(self) -> None:
        await self._profile(balance=10_000)
        self.assertEqual(20, await storage.market_sell_limit(1))
        self.assertEqual("upgraded", await storage.upgrade_market_pallet(1))
        self.assertEqual(40, await storage.market_sell_limit(1))
        self.assertEqual("already_upgraded", await storage.upgrade_market_pallet(1))

        await storage.add_item(1, "egg", 41, ITEMS["egg"].max_qty)
        ready_at = (datetime.now() + timedelta(minutes=1)).isoformat()
        self.assertEqual("ok", await storage.create_market_listing(1, "egg", 20, ready_at, 40))
        self.assertEqual("limit", await storage.create_market_listing(1, "egg", 20, ready_at, 1))

    async def test_pallet_upgrade_is_safe_on_double_click(self) -> None:
        await self._profile(balance=10_000)
        results = await asyncio.gather(
            storage.upgrade_market_pallet(1),
            storage.upgrade_market_pallet(1),
        )
        self.assertEqual(["already_upgraded", "upgraded"], sorted(results))
        self.assertEqual(40, await storage.market_sell_limit(1))
        self.assertEqual(0, (await storage.get_profile(1))[3])


class BusinessMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_laundering_and_pallet_migrate(self) -> None:
        old_db_path = config.db_path
        temp_dir = tempfile.TemporaryDirectory()
        config.db_path = str(Path(temp_dir.name) / "legacy.sqlite3")
        legacy = sqlite3.connect(config.db_path)
        legacy.executescript(
            """
            CREATE TABLE profiles (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                nick TEXT UNIQUE,
                zbucks INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE laundering (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                amount INTEGER,
                ready_at TEXT
            );
            INSERT INTO profiles (tg_id, username, nick, zbucks)
            VALUES (1, 'legacy', 'Legacy', 10);
            INSERT INTO laundering (tg_id, amount, ready_at)
            VALUES (1, 500, '2030-01-01T00:00:00');
            """
        )
        legacy.commit()
        legacy.close()
        try:
            await storage.close()
            storage._economy_lock = asyncio.Lock()
            await storage.init()
            self.assertEqual(20, await storage.market_sell_limit(1))
            self.assertEqual([(500, "2030-01-01T00:00:00")],
                             await storage.get_launderings(1, business.BIZ_MOSQUITO))
        finally:
            await storage.close()
            config.db_path = old_db_path
            temp_dir.cleanup()
