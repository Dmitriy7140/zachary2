import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from db.storage import (
    CubeDirectionView,
    CubeMapRoomView,
    CubeRoommateView,
    CubeView,
)
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

    def test_action_accepts_only_known_cube_item(self):
        self.assertEqual(
            cube._action_args("c:a:42:0:lockpicks"),
            (42, 0, "lockpicks"),
        )
        self.assertIsNone(cube._action_args("c:a:42:0:iphone"))
        self.assertIsNone(cube._action_args("c:a:42:0:1"))

    def test_retreat_requires_generation_and_version(self):
        self.assertEqual(cube._retreat_args("c:ar:42:0"), (42, 0))
        self.assertIsNone(cube._retreat_args("c:ar:42:-1"))
        self.assertIsNone(cube._retreat_args("c:ar:42:0:tail"))

    def test_longest_documented_callback_fits_telegram_limit(self):
        maximum = 9_223_372_036_854_775_807
        callbacks = [
            f"c:e:{maximum}:abcdefghijk",
            f"c:m:{maximum}:{maximum}:n",
            f"c:o:{maximum}:{maximum}:n",
            f"c:a:{maximum}:{maximum}:lockpicks",
            f"c:ar:{maximum}:{maximum}",
            f"c:v:{maximum}",
            f"c:ns:{maximum}:abcdefghijk",
            f"c:nc:{maximum}:{maximum}",
        ]
        for value in callbacks:
            with self.subTest(value=value):
                data = cube._callback_data(value)
                self.assertLessEqual(len(data.encode("utf-8")), 64)


class CubeRenderingTests(unittest.TestCase):
    @staticmethod
    def _view(**changes):
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
        inventory = {key: 2 for key in cube._HAZARD_ITEM_KEYS}
        text = cube._room_text(view, inventory=inventory)
        self.assertLessEqual(len(text), 1024)
        self.assertNotIn("Нужен предмет", text)
        self.assertNotIn("Отмычки", text)
        self.assertIn("расходник тратится", text)
        self.assertIn("инструмент сломается", text)
        keyboard = cube._room_keyboard(
            view,
            9_223_372_036_854_775_807,
            inventory=inventory,
        )
        action_buttons = [
            button
            for row in keyboard.inline_keyboard
            for button in row
            if (button.callback_data or "").startswith("c:a:")
        ]
        self.assertEqual(8, len(action_buttons))
        for row in keyboard.inline_keyboard:
            for button in row:
                self.assertLessEqual(len((button.callback_data or "").encode("utf-8")), 64)

    def test_hazard_choice_shows_only_items_in_inventory(self):
        view = self._view()
        keyboard = cube._room_keyboard(
            view,
            777,
            inventory={"bucket": 1, "bait_1": 3, "iphone": 1},
        )
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if (button.callback_data or "").startswith("c:a:")
        ]
        self.assertEqual(
            ["c:a:42:0:bucket", "c:a:42:0:bait_1"], callbacks
        )
        labels = {
            button.callback_data: button.text
            for row in keyboard.inline_keyboard
            for button in row
            if (button.callback_data or "").startswith("c:a:")
        }
        self.assertIn("⚠️", labels["c:a:42:0:bucket"])
        self.assertIn("−1", labels["c:a:42:0:bait_1"])
        self.assertTrue(any(
            button.callback_data == "c:ar:42:0"
            for row in keyboard.inline_keyboard
            for button in row
        ))

    def test_each_hazard_has_a_distinct_wrong_item_comment(self):
        for item_key, item in (
            ("lockpicks", "🗝 Отмычки"),
            ("bait_1", "🪱 Приманка на 🐟"),
        ):
            comments = {
                kind: cube.cube_content.wrong_hazard_item(
                    kind, item, item_key=item_key
                )
                for kind in cube.cube_content.HAZARD_TEXTS
            }
            self.assertEqual(8, len(comments))
            self.assertEqual(8, len(set(comments.values())))
            for kind, comment in comments.items():
                with self.subTest(kind=kind, item_key=item_key):
                    self.assertIn("обратно", comment)
                    self.assertIn("исчез из инвентаря", comment)
                    self.assertLessEqual(len(comment), 200)

    def test_roommates_are_escaped_and_long_list_is_compact(self):
        view = self._view(
            pending_hazard_room_id=None,
            pending_hazard_kind=None,
            roommates=(
                CubeRoommateView(11, 101, "<Алиса>", 2),
                CubeRoommateView(12, 102, "Борис", 3),
                CubeRoommateView(13, 103, "Вика", 4),
                CubeRoommateView(14, 104, "Гриша", 5),
            ),
        )

        text = cube._room_text(view)

        self.assertIn("&lt;Алиса&gt;", text)
        self.assertNotIn("<Алиса>", text)
        self.assertIn("и ещё 1", text)
        self.assertNotIn("Гриша", text)

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

    def test_map_snapshot_preserves_geometry_exits_and_room_categories(self):
        view = self._view(
            current_room_id=101,
            map_size=4,
            map_rooms=(
                CubeMapRoomView(
                    room_id=100,
                    row=1,
                    column=0,
                    kind="hazard",
                    effect_kind=None,
                    exits=frozenset({"e"}),
                ),
                CubeMapRoomView(
                    room_id=101,
                    row=1,
                    column=1,
                    kind="neutral",
                    effect_kind=None,
                    exits=frozenset({"e", "w"}),
                ),
                CubeMapRoomView(
                    room_id=102,
                    row=1,
                    column=2,
                    kind="neutral",
                    effect_kind="archive",
                    exits=frozenset({"w"}),
                ),
            ),
        )

        snapshot = cube._map_snapshot(view)

        self.assertEqual(4, snapshot.size)
        self.assertEqual(101, snapshot.current_room_id)
        self.assertEqual(
            [
                (100, 1, 0, frozenset({"e"}), "dangerous"),
                (101, 1, 1, frozenset({"e", "w"}), "neutral"),
                (102, 1, 2, frozenset({"w"}), "useful"),
            ],
            [
                (
                    room.room_id,
                    room.row,
                    room.column,
                    room.exits,
                    room.category,
                )
                for room in snapshot.rooms
            ],
        )


class CubeRenderCurrentTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _callback():
        return SimpleNamespace(
            from_user=SimpleNamespace(id=777),
            message=object(),
        )

    @staticmethod
    def _active_view():
        return CubeRenderingTests._view(
            pending_hazard_room_id=None,
            pending_hazard_kind=None,
            map_rooms=(
                CubeMapRoomView(
                    room_id=0,
                    row=1,
                    column=1,
                    kind="start",
                    effect_kind=None,
                    exits=frozenset(),
                ),
            ),
        )

    async def test_active_view_renders_in_thread_and_shows_dynamic_photo(self):
        cb = self._callback()
        view = self._active_view()
        payload = b"deterministic png"
        get_view = AsyncMock(return_value=view)
        to_thread = AsyncMock(return_value=payload)
        show_dynamic_photo = AsyncMock()
        show_screen = AsyncMock()

        with (
            patch.object(cube.storage, "get_cube_view", get_view),
            patch.object(cube.asyncio, "to_thread", to_thread),
            patch.object(cube, "show_dynamic_photo", show_dynamic_photo),
            patch.object(cube, "show_screen", show_screen),
        ):
            await cube._render_current(cb, observe=True)

        get_view.assert_awaited_once_with(777)
        to_thread.assert_awaited_once_with(
            cube.render_map_png,
            cube._map_snapshot(view),
        )
        show_dynamic_photo.assert_awaited_once()
        args = show_dynamic_photo.await_args.args
        self.assertIs(cb.message, args[0])
        self.assertEqual(payload, args[1])
        self.assertEqual("cube-map-42-7-0.png", args[2])
        self.assertEqual(cube._room_text(view, observe=True), args[3])
        self.assertEqual(
            cube._room_keyboard(view, 777, observe=True),
            args[4],
        )
        show_screen.assert_not_awaited()

    async def test_renderer_error_replaces_stale_map_with_static_photo(self):
        cb = self._callback()
        view = self._active_view()
        get_view = AsyncMock(return_value=view)
        to_thread = AsyncMock(side_effect=RuntimeError("broken renderer"))
        show_dynamic_photo = AsyncMock()
        show_screen = AsyncMock()
        show_photo_menu = AsyncMock()

        with self.assertLogs(cube.log.name, level="ERROR"):
            with (
                patch.object(cube.storage, "get_cube_view", get_view),
                patch.object(cube.asyncio, "to_thread", to_thread),
                patch.object(cube, "show_dynamic_photo", show_dynamic_photo),
                patch.object(cube, "show_screen", show_screen),
                patch.object(cube, "show_photo_menu", show_photo_menu),
            ):
                await cube._render_current(cb)

        to_thread.assert_awaited_once_with(
            cube.render_map_png,
            cube._map_snapshot(view),
        )
        show_dynamic_photo.assert_not_awaited()
        show_screen.assert_not_awaited()
        show_photo_menu.assert_awaited_once_with(
            cb.message,
            cube._GAMES_PHOTO,
            cube._GAMES_PHOTO_META,
            cube._room_text(view),
            cube._room_keyboard(view, 777),
        )


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
