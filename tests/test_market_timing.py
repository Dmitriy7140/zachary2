"""Правила сроков продажи продуктов на рынке."""
import unittest

from game.items import ITEMS, MARKET_MAX_WAIT_MINUTES, market_wait_minutes, sellable_items


class MarketTimingTests(unittest.TestCase):
    def test_every_product_reaches_same_cap_at_maximum_price(self):
        for item in sellable_items():
            with self.subTest(item=item.key):
                self.assertEqual(0, market_wait_minutes(item, item.sell_min))
                self.assertEqual(
                    MARKET_MAX_WAIT_MINUTES,
                    market_wait_minutes(item, item.sell_max),
                )

    def test_milk_range_and_product_specific_time_steps(self):
        milk = ITEMS["milk_can"]
        fish = ITEMS["fish_2"]
        pie = ITEMS["slime_pie"]

        self.assertEqual((400, 600), (milk.sell_min, milk.sell_max))
        self.assertEqual(1, market_wait_minutes(milk, 401))
        self.assertEqual(4, market_wait_minutes(fish, 151))
        self.assertEqual(6, market_wait_minutes(pie, 201))

    def test_price_outside_product_range_is_rejected(self):
        with self.assertRaises(ValueError):
            market_wait_minutes(ITEMS["milk_can"], 399)


if __name__ == "__main__":
    unittest.main()
