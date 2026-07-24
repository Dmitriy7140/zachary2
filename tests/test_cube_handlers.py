import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from db.storage import CubeDirectionView, CubeView
from handlers import cube


class CubeCallbackParserTests(unittest.TestCase):
    def test_entry_callback_requires_full_urlsafe_token(self):
        self.assertEqual(cube._entry_args("c:e:42:abcdefghijk"), (42, "abcdefghijk"))
        self.assertIsNone(cube._entry_args("c:e:42:short"))
        self.assertIsNone(cube._entry_args("c:e:42:abcdefghijk:tail"))
        self.assertIsNone(cube._entry_args("c:e:042:abcdefghijk"))

    def test_move_accepts_initial_zero_version(self):
        self.assertEqual(cube._versioned_direction_args("c:m:42:0:n", "m"), (42, 0, "n"))
        self.assertIsNone(cube._versioned_direction_args("c:m:42:0:q", "m"))
        self.assertIsNone(cube._versioned_direction_args("c:m:42:+1:n", "m"))

    def test_action_accepts_zero_based_room_id(self):
        self.assertEqual(cube._action_args("c:a:42:0:0"), (42, 0, 0))
        self.assertIsNone(cube._action_args("c:a:42:0:-1"))
        self.assertIsNone(cube._action_args("c:a:42:0:00"))

    def test_longest_documented_callback_fits_telegram_limit(self):
        maximum = 9_223_372_036_854_775_807
        callbacks = [
            f"c:e:{maximum}:abcdefghijk",
            f"c:m:{maximum}:{maximum}:n",
            f"c:o:{maximum}:{maximum}:n",
            f"c:a:{maximum}:{maximum}:{maximum}",
            f"c:v:{maximum}",
            f"c:ns:{maximum}:abcdefghijk",
            f"c:nc:{maximum}:{maximum}",
        ]
        for value in callbacks:
            with self.subTest(value=value):
                data = cube._callback_data(value)
                self.assertLessEqual(len(data.encode("utf-8")), 64)


class CubeRenderingTests(unittest.TestCase):
    def _view(self, **changes):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        values = dict(
            generation_id=42,
            generation_status="lobby",
            created_at=now.isoformat(),
            idle_expires_at=(now + timedelta(hours=1)).isoformat(),
            lobby_closes_at=(now + timedelta(minutes=3)).isoformat(),
            closes_at=(now + timedelta(hours=1)).isoformat(),
            roster_locked=False,
            participant_count=4,
            prize_amount=4000,
            entry_cost=500,
            prize_per_participant=1000,
            max_participants=16,
            balance=5000,
            run_id=7,
            run_status="active",
            run_version=0,
            current_room_id=0,
            room_code="407",
            room_kind="start",
            room_description_key="start",
            room_effect_kind=None,
            room_effect_arg=None,
            room_hazard_kind=None,
            room_hazard_resolved=False,
            room_resolved_by_nick=None,
            subscription_id=None,
            subscription_generation_id=None,
            pending_hazard_room_id=1,
            pending_hazard_kind="wire_net",
            pending_required_item_key="znak",
            pending_consume_qty=0,
            explored_count=6,
            directions=(
                CubeDirectionView("n", False),
                CubeDirectionView("e", True, 1, "512", "hazard", True),
                CubeDirectionView("s", True, 4, None, None, False),
                CubeDirectionView("w", False),
            ),
        )
        values.update(changes)
        return CubeView(**values)

    def test_room_caption_and_all_callbacks_fit(self):
        view = self._view()
        self.assertLessEqual(len(cube._room_text(view)), 1024)
        keyboard = cube._room_keyboard(view, 9_223_372_036_854_775_807)
        for row in keyboard.inline_keyboard:
            for button in row:
                self.assertLessEqual(len((button.callback_data or "").encode("utf-8")), 64)

    def test_lobby_caption_and_callbacks_fit(self):
        view = self._view(run_id=None, run_status=None, run_version=None, current_room_id=None)
        self.assertLessEqual(len(cube._lobby_text(view)), 1024)
        keyboard = cube._lobby_keyboard(view, 9_223_372_036_854_775_807)
        for row in keyboard.inline_keyboard:
            for button in row:
                self.assertLessEqual(len((button.callback_data or "").encode("utf-8")), 64)

    def test_observed_category_remains_visible_before_room_is_revealed(self):
        view = self._view(
            directions=(
                CubeDirectionView("n", False),
                CubeDirectionView("e", True, 1, None, "hazard", False),
                CubeDirectionView("s", False),
                CubeDirectionView("w", False),
            )
        )
        text = cube._room_text(view)
        self.assertIn("неизвестная комната · предметная ловушка", text)

    def test_transfer_notice_uses_opaque_room_code(self):
        notice = cube._effect_notice("vector", "407")
        self.assertIn("комната 407", notice)
        self.assertNotIn("room_id", notice)

    def test_resolver_name_is_shown_and_html_escaped(self):
        view = self._view(
            room_kind="hazard",
            room_hazard_kind="wire_net",
            room_hazard_resolved=True,
            room_resolved_by_nick="<Спаситель>",
            pending_hazard_room_id=None,
        )
        text = cube._room_text(view)
        self.assertIn("&lt;Спаситель&gt;", text)
        self.assertNotIn("<Спаситель>", text)


class CubeResultNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_generation_reports_winner(self):
        winner = SimpleNamespace(winner_nick="Nick\nInjected", prize_amount=3000)
        with patch.object(
            cube.storage,
            "get_cube_winner",
            AsyncMock(return_value=winner),
        ):
            notice = await cube._closed_generation_notice(42)
        self.assertIn("Nick Injected", notice)
        self.assertIn("3000 Z", notice)
        self.assertLessEqual(len(notice), 200)


if __name__ == "__main__":
    unittest.main()
