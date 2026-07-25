"""Прогрессии и надбавки нелегальных работ."""
import unittest

from game.illegal_jobs import (
    SCAMMER_RANKS,
    VPN_RANKS,
    reward_with_rank_bonus,
    scammer_rank,
    vpn_rank,
)


class IllegalJobLevelTests(unittest.TestCase):
    def test_phone_ranks_require_20_then_25_30_and_35_more_calls(self) -> None:
        self.assertEqual((1, "Обманщик детей в Роблоксе", 0),
                         (scammer_rank(0)[0], scammer_rank(0)[1].name, scammer_rank(0)[1].bonus_pct))
        self.assertEqual((2, "Аферист из магазина косметики", 10),
                         (scammer_rank(20)[0], scammer_rank(20)[1].name, scammer_rank(20)[1].bonus_pct))
        self.assertEqual(3, scammer_rank(45)[0])
        self.assertEqual(4, scammer_rank(75)[0])
        self.assertEqual((5, "Человек-созвон", 100),
                         (scammer_rank(110)[0], scammer_rank(110)[1].name, scammer_rank(110)[1].bonus_pct))

    def test_vpn_starts_with_ten_percent_bonus(self) -> None:
        self.assertEqual((1, "Впариватель сомнительных конфигов", 10),
                         (vpn_rank(0)[0], vpn_rank(0)[1].name, vpn_rank(0)[1].bonus_pct))
        self.assertEqual((4, "Кибербезопасник", 40),
                         (vpn_rank(150)[0], vpn_rank(150)[1].name, vpn_rank(150)[1].bonus_pct))
        self.assertEqual((5, "Хакер инсультов", 100),
                         (vpn_rank(220)[0], vpn_rank(220)[1].name, vpn_rank(220)[1].bonus_pct))

    def test_bonus_rounds_down_to_whole_zbucks(self) -> None:
        self.assertEqual(160, reward_with_rank_bonus(160, SCAMMER_RANKS[0].bonus_pct))
        self.assertEqual(176, reward_with_rank_bonus(160, SCAMMER_RANKS[1].bonus_pct))
        self.assertEqual(330, reward_with_rank_bonus(300, VPN_RANKS[0].bonus_pct))
        self.assertEqual(275, reward_with_rank_bonus(250, VPN_RANKS[0].bonus_pct))


if __name__ == "__main__":
    unittest.main()
