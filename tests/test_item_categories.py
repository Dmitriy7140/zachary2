"""Проверки полного и стабильного разбиения предметов по инвентарю."""
import unittest

from game.items import (INVENTORY_CATEGORIES, ITEM_CATEGORY, ITEMS, categorized_items,
                        categorized_inventory_items, shop_items)


class ItemCategoriesTests(unittest.TestCase):
    def test_every_item_has_exactly_one_category(self):
        category_keys = {key for key, _label in INVENTORY_CATEGORIES}

        self.assertEqual(set(ITEM_CATEGORY), set(ITEMS))
        self.assertTrue(set(ITEM_CATEGORY.values()) <= category_keys)

    def test_categorized_items_are_filtered_and_follow_catalog_order(self):
        categories = categorized_inventory_items({
            "car_panos": 1,
            "bait_1": 5,
            "egg": 3,
            "unknown": 10,
            "samsung": 0,
        })

        self.assertEqual(categories["transport"], [("car_panos", 1)])
        self.assertEqual(categories["tools"], [("bait_1", 5)])
        self.assertEqual(categories["food"], [("egg", 3)])
        self.assertEqual(categories["sins"], [])
        self.assertEqual(categories["tech"], [])

    def test_shop_uses_only_categories_with_regular_store_goods(self):
        categories = categorized_items(shop_items())

        self.assertEqual([], categories["sins"])
        self.assertEqual([], categories["food"])
        self.assertEqual(
            ["bike", "car_merch", "car_panos", "car_mubiesi"],
            [item.key for item in categories["transport"]],
        )
        self.assertEqual(
            ["bucket", "znak", "crowbar", "rod", "bait_1", "bait_2", "bait_3"],
            [item.key for item in categories["tools"]],
        )
        self.assertEqual(
            ["iphone", "samsung"],
            [item.key for item in categories["tech"]],
        )


if __name__ == "__main__":
    unittest.main()
