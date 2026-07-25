from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import FrozenInstanceError
from io import BytesIO, StringIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from scripts.cube_map_renderer import (
    CATEGORY_DANGEROUS,
    CATEGORY_NEUTRAL,
    CATEGORY_USEFUL,
    CURRENT_OUTLINE,
    DANGEROUS_ROOM_FILL,
    DANGEROUS_ROOM_OUTLINE,
    GRID_STEP,
    LOGICAL_SIZE,
    NEUTRAL_ROOM_FILL,
    NEUTRAL_ROOM_OUTLINE,
    OUTPUT_SIZE,
    PASSAGE_FILL,
    PLAYER_MARKER,
    ROOM_SIZE,
    USEFUL_ROOM_FILL,
    USEFUL_ROOM_OUTLINE,
    KnownRoom,
    MapSnapshot,
    _layout_snapshot,
    render_map,
    render_map_png,
)


def _room(
    room_id: int,
    row: int,
    column: int,
    *exits: str,
    category: str = CATEGORY_NEUTRAL,
) -> KnownRoom:
    return KnownRoom(
        room_id=room_id,
        row=row,
        column=column,
        exits=frozenset(exits),
        category=category,
    )


def _logical_image(snapshot: MapSnapshot) -> Image.Image:
    rendered = render_map(snapshot)
    if rendered.size == LOGICAL_SIZE:
        return rendered
    return rendered.resize(LOGICAL_SIZE, resample=Image.Resampling.NEAREST)


def _rect_size(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    left, top, right, bottom = rect
    return right - left + 1, bottom - top + 1


def _rect_center(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    left, top, right, bottom = rect
    return (left + right) // 2, (top + bottom) // 2


def _layout_center(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """Return the center used by the renderer for an even-sized rectangle."""
    left, top, right, bottom = rect
    return (left + right + 1) // 2, (top + bottom + 1) // 2


def _assert_rect_inside_canvas(
    test: unittest.TestCase,
    rect: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = rect
    test.assertGreaterEqual(left, 0)
    test.assertGreaterEqual(top, 0)
    test.assertLess(right, LOGICAL_SIZE[0])
    test.assertLess(bottom, LOGICAL_SIZE[1])


class CubeMapRendererTests(unittest.TestCase):
    def test_single_room_is_centered_and_uses_current_room_style(self) -> None:
        snapshot = MapSnapshot(
            size=4,
            rooms=(_room(41, 3, 0),),
            current_room_id=41,
        )

        layout = _layout_snapshot(snapshot)
        self.assertEqual((41,), tuple(layout.room_rects))
        self.assertEqual((), layout.corridor_rects)
        self.assertEqual((), layout.stub_rects)

        rect = layout.room_rects[41]
        self.assertEqual(ROOM_SIZE, _rect_size(rect))
        left, top, right, bottom = rect
        self.assertEqual(LOGICAL_SIZE[0], left + right + 1)
        self.assertEqual(LOGICAL_SIZE[1], top + bottom + 1)

        logical = _logical_image(snapshot)
        center = _rect_center(rect)
        self.assertEqual(CURRENT_OUTLINE, logical.getpixel((left, top)))
        self.assertEqual(NEUTRAL_ROOM_FILL, logical.getpixel((left + 2, top + 2)))
        self.assertEqual(PLAYER_MARKER, logical.getpixel(center))

    def test_known_corridor_and_unknown_exit_have_distinct_geometry(self) -> None:
        snapshot = MapSnapshot(
            size=4,
            rooms=(
                _room(10, 0, 0, "e", "s"),
                _room(11, 0, 1, "w"),
            ),
            current_room_id=11,
        )

        layout = _layout_snapshot(snapshot)
        self.assertEqual(1, len(layout.corridor_rects))
        self.assertEqual(1, len(layout.stub_rects))
        first = layout.room_rects[10]
        second = layout.room_rects[11]
        corridor = layout.corridor_rects[0]
        stub = layout.stub_rects[0]

        self.assertEqual(GRID_STEP[0], second[0] - first[0])
        self.assertEqual(_layout_center(first)[0], corridor[0])
        self.assertEqual(_layout_center(second)[0], corridor[2])
        self.assertGreaterEqual(corridor[1], first[1])
        self.assertLessEqual(corridor[3], first[3])

        self.assertLessEqual(stub[1], first[3])
        self.assertGreater(stub[3], first[3])
        unknown_room_top = first[1] + GRID_STEP[1]
        self.assertLess(stub[3], unknown_room_top)
        self.assertGreaterEqual(stub[0], first[0])
        self.assertLessEqual(stub[2], first[2])

        logical = _logical_image(snapshot)
        self.assertEqual(PASSAGE_FILL, logical.getpixel(_rect_center(corridor)))
        self.assertEqual(PASSAGE_FILL, logical.getpixel(_rect_center(stub)))
        unknown_room_center = (
            _rect_center(first)[0],
            _rect_center(first)[1] + GRID_STEP[1],
        )
        room_colors = {
            DANGEROUS_ROOM_FILL,
            DANGEROUS_ROOM_OUTLINE,
            NEUTRAL_ROOM_FILL,
            NEUTRAL_ROOM_OUTLINE,
            CURRENT_OUTLINE,
            USEFUL_ROOM_FILL,
            USEFUL_ROOM_OUTLINE,
            PASSAGE_FILL,
            PLAYER_MARKER,
        }
        self.assertNotIn(logical.getpixel(unknown_room_center), room_colors)

        self.assertEqual(
            NEUTRAL_ROOM_OUTLINE,
            logical.getpixel((first[0], first[1])),
        )
        self.assertEqual(
            NEUTRAL_ROOM_FILL,
            logical.getpixel((first[0] + 2, first[1] + 2)),
        )
        self.assertEqual(CURRENT_OUTLINE, logical.getpixel((second[0], second[1])))
        self.assertEqual(
            NEUTRAL_ROOM_FILL,
            logical.getpixel((second[0] + 2, second[1] + 2)),
        )

    def test_translation_inside_hidden_grid_does_not_change_the_map(self) -> None:
        upper_left = MapSnapshot(
            size=4,
            rooms=(
                _room(7, 0, 0, "e"),
                _room(8, 0, 1, "w"),
            ),
            current_room_id=8,
        )
        lower_right = MapSnapshot(
            size=4,
            rooms=(
                _room(7, 3, 2, "e"),
                _room(8, 3, 3, "w"),
            ),
            current_room_id=8,
        )

        self.assertEqual(
            _layout_snapshot(upper_left).origin,
            _layout_snapshot(lower_right).origin,
        )
        self.assertEqual(render_map_png(upper_left), render_map_png(lower_right))

    def test_room_categories_have_distinct_colors_and_current_keeps_its_fill(
        self,
    ) -> None:
        snapshot = MapSnapshot(
            size=4,
            rooms=(
                _room(1, 1, 0, "e", category=CATEGORY_DANGEROUS),
                _room(2, 1, 1, "w", "e", category=CATEGORY_NEUTRAL),
                _room(3, 1, 2, "w", "e", category=CATEGORY_USEFUL),
                _room(4, 1, 3, "w", category=CATEGORY_USEFUL),
            ),
            current_room_id=4,
        )
        layout = _layout_snapshot(snapshot)
        logical = _logical_image(snapshot)
        dangerous = layout.room_rects[1]
        neutral = layout.room_rects[2]
        useful = layout.room_rects[3]
        current = layout.room_rects[4]

        self.assertEqual(
            DANGEROUS_ROOM_OUTLINE,
            logical.getpixel((dangerous[0], dangerous[1])),
        )
        self.assertEqual(
            DANGEROUS_ROOM_FILL,
            logical.getpixel((dangerous[0] + 2, dangerous[1] + 2)),
        )
        self.assertEqual(
            NEUTRAL_ROOM_OUTLINE,
            logical.getpixel((neutral[0], neutral[1])),
        )
        self.assertEqual(
            NEUTRAL_ROOM_FILL,
            logical.getpixel((neutral[0] + 2, neutral[1] + 2)),
        )
        self.assertEqual(
            USEFUL_ROOM_OUTLINE,
            logical.getpixel((useful[0], useful[1])),
        )
        self.assertEqual(
            USEFUL_ROOM_FILL,
            logical.getpixel((useful[0] + 2, useful[1] + 2)),
        )
        self.assertEqual(
            CURRENT_OUTLINE,
            logical.getpixel((current[0], current[1])),
        )
        self.assertEqual(
            USEFUL_ROOM_FILL,
            logical.getpixel((current[0] + 2, current[1] + 2)),
        )
        self.assertEqual(PLAYER_MARKER, logical.getpixel(_rect_center(current)))

    def test_full_four_by_four_grid_is_centered_and_stays_inside_canvas(self) -> None:
        rooms = []
        for row in range(4):
            for column in range(4):
                exits = []
                if row > 0:
                    exits.append("n")
                if column < 3:
                    exits.append("e")
                if row < 3:
                    exits.append("s")
                if column > 0:
                    exits.append("w")
                room_id = row * 4 + column
                rooms.append(_room(room_id, row, column, *exits))

        snapshot = MapSnapshot(
            size=4,
            rooms=tuple(rooms),
            current_room_id=15,
        )
        layout = _layout_snapshot(snapshot)

        self.assertEqual(16, len(layout.room_rects))
        self.assertEqual(24, len(layout.corridor_rects))
        self.assertEqual((), layout.stub_rects)
        left = min(rect[0] for rect in layout.room_rects.values())
        top = min(rect[1] for rect in layout.room_rects.values())
        right = max(rect[2] for rect in layout.room_rects.values())
        bottom = max(rect[3] for rect in layout.room_rects.values())
        expected_width = ROOM_SIZE[0] + 3 * GRID_STEP[0]
        expected_height = ROOM_SIZE[1] + 3 * GRID_STEP[1]
        self.assertEqual(expected_width, right - left + 1)
        self.assertEqual(expected_height, bottom - top + 1)
        self.assertEqual(LOGICAL_SIZE[0], left + right + 1)
        self.assertEqual(LOGICAL_SIZE[1], top + bottom + 1)
        self.assertGreaterEqual(left, 0)
        self.assertGreaterEqual(top, 0)
        self.assertLess(right, LOGICAL_SIZE[0])
        self.assertLess(bottom, LOGICAL_SIZE[1])

        for room in rooms:
            rect = layout.room_rects[room.room_id]
            self.assertEqual(ROOM_SIZE, _rect_size(rect))
            self.assertEqual(left + room.column * GRID_STEP[0], rect[0])
            self.assertEqual(top + room.row * GRID_STEP[1], rect[1])
            _assert_rect_inside_canvas(self, rect)
        for rect in layout.corridor_rects:
            _assert_rect_inside_canvas(self, rect)

        logical = _logical_image(snapshot)
        current_rect = layout.room_rects[snapshot.current_room_id]
        self.assertEqual(
            NEUTRAL_ROOM_FILL,
            logical.getpixel((current_rect[0] + 2, current_rect[1] + 2)),
        )
        self.assertEqual(
            PLAYER_MARKER,
            logical.getpixel(_rect_center(current_rect)),
        )
        for y in range(logical.height):
            for x in range(logical.width):
                if logical.getpixel((x, y)) != CURRENT_OUTLINE:
                    continue
                self.assertTrue(
                    current_rect[0] <= x <= current_rect[2]
                    and current_rect[1] <= y <= current_rect[3]
                )

    def test_invalid_snapshots_are_rejected(self) -> None:
        invalid_cases = {
            "non-positive size": lambda: MapSnapshot(
                size=0,
                rooms=(_room(1, 0, 0),),
                current_room_id=1,
            ),
            "empty room list": lambda: MapSnapshot(
                size=4,
                rooms=(),
                current_room_id=1,
            ),
            "duplicate room id": lambda: MapSnapshot(
                size=4,
                rooms=(_room(1, 0, 0), _room(1, 0, 1)),
                current_room_id=1,
            ),
            "duplicate coordinates": lambda: MapSnapshot(
                size=4,
                rooms=(_room(1, 0, 0), _room(2, 0, 0)),
                current_room_id=1,
            ),
            "negative coordinate": lambda: MapSnapshot(
                size=4,
                rooms=(_room(1, -1, 0),),
                current_room_id=1,
            ),
            "coordinate outside grid": lambda: MapSnapshot(
                size=4,
                rooms=(_room(1, 0, 4),),
                current_room_id=1,
            ),
            "missing current room": lambda: MapSnapshot(
                size=4,
                rooms=(_room(1, 0, 0),),
                current_room_id=2,
            ),
            "invalid direction": lambda: MapSnapshot(
                size=4,
                rooms=(_room(1, 0, 0, "north"),),
                current_room_id=1,
            ),
            "invalid category": lambda: MapSnapshot(
                size=4,
                rooms=(_room(1, 0, 0, category="mysterious"),),
                current_room_id=1,
            ),
            "exit outside grid": lambda: MapSnapshot(
                size=4,
                rooms=(_room(1, 0, 0, "n"),),
                current_room_id=1,
            ),
            "non-reciprocal known passage": lambda: MapSnapshot(
                size=4,
                rooms=(_room(1, 0, 0, "e"), _room(2, 0, 1)),
                current_room_id=1,
            ),
        }

        for description, make_snapshot in invalid_cases.items():
            with self.subTest(description=description):
                with self.assertRaises(ValueError):
                    render_map(make_snapshot())

    def test_models_are_frozen_and_rendering_does_not_mutate_snapshot(self) -> None:
        source_exits = {"e"}
        room = KnownRoom(
            room_id=1,
            row=1,
            column=1,
            exits=source_exits,
        )
        source_rooms = [room]
        snapshot = MapSnapshot(
            size=4,
            rooms=source_rooms,
            current_room_id=1,
        )
        before = (
            snapshot.size,
            snapshot.current_room_id,
            tuple(
                (
                    known.room_id,
                    known.row,
                    known.column,
                    known.exits,
                    known.category,
                )
                for known in snapshot.rooms
            ),
        )

        source_exits.add("s")
        source_rooms.clear()

        render_map(snapshot)
        render_map_png(snapshot)

        after = (
            snapshot.size,
            snapshot.current_room_id,
            tuple(
                (
                    known.room_id,
                    known.row,
                    known.column,
                    known.exits,
                    known.category,
                )
                for known in snapshot.rooms
            ),
        )
        self.assertEqual(before, after)
        self.assertEqual((room,), snapshot.rooms)
        self.assertEqual(frozenset({"e"}), room.exits)
        with self.assertRaises(FrozenInstanceError):
            room.row = 2  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            snapshot.current_room_id = 2  # type: ignore[misc]

    def test_png_is_deterministic_rgb_and_telegram_sized(self) -> None:
        snapshot = MapSnapshot(
            size=4,
            rooms=(
                _room(3, 1, 1, "e"),
                _room(4, 1, 2, "w", "s"),
            ),
            current_room_id=4,
        )

        first = render_map_png(snapshot)
        second = render_map_png(snapshot)

        self.assertEqual(first, second)
        self.assertTrue(first.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(first)) as image:
            image.load()
            self.assertEqual("PNG", image.format)
            self.assertEqual("RGB", image.mode)
            self.assertEqual(OUTPUT_SIZE, image.size)

    def test_examples_cli_writes_four_states_and_contact_sheet(self) -> None:
        from scripts import cube_map_examples

        expected = {
            "01_start.png": OUTPUT_SIZE,
            "02_first_steps.png": OUTPUT_SIZE,
            "03_branch_and_loop.png": OUTPUT_SIZE,
            "04_full_map.png": OUTPUT_SIZE,
            "contact_sheet.png": (OUTPUT_SIZE[0] * 2, OUTPUT_SIZE[1] * 2),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with redirect_stdout(StringIO()):
                exit_code = cube_map_examples.main(
                    ["--output-dir", temp_dir]
                )

            self.assertEqual(0, exit_code)
            output_dir = Path(temp_dir)
            self.assertEqual(
                set(expected),
                {path.name for path in output_dir.glob("*.png")},
            )
            for filename, size in expected.items():
                with self.subTest(filename=filename):
                    with Image.open(output_dir / filename) as image:
                        image.load()
                        self.assertEqual("PNG", image.format)
                        self.assertEqual("RGB", image.mode)
                        self.assertEqual(size, image.size)

    def test_example_walk_and_adapter_use_only_real_cube_passages(self) -> None:
        from scripts import cube_map_examples

        spec = cube_map_examples.generate_cube(cube_map_examples.DEMO_SEED)
        walk = cube_map_examples.depth_first_walk(spec)
        self.assertEqual(spec.start_room_id, walk[0])
        self.assertEqual(
            {room.room_id for room in spec.rooms},
            set(walk),
        )
        for source, target in zip(walk, walk[1:]):
            self.assertTrue(spec.has_passage(source, target))

        snapshots = cube_map_examples._milestone_snapshots(spec)
        self.assertEqual([1, 4, 9, 16], [len(item.rooms) for item in snapshots])
        previous_ids: set[int] = set()
        for snapshot in snapshots:
            known_ids = {room.room_id for room in snapshot.rooms}
            self.assertTrue(previous_ids <= known_ids)
            self.assertIn(snapshot.current_room_id, known_ids)
            for room in snapshot.rooms:
                expected_exits = {
                    direction.value
                    for direction, _target in spec.neighbors(room.room_id)
                }
                self.assertEqual(expected_exits, set(room.exits))
                source = spec.room(room.room_id)
                if source.kind == "hazard" or source.effect_kind in {"echo", "dark"}:
                    expected_category = CATEGORY_DANGEROUS
                elif source.kind == "prize" or source.effect_kind == "archive":
                    expected_category = CATEGORY_USEFUL
                else:
                    expected_category = CATEGORY_NEUTRAL
                self.assertEqual(expected_category, room.category)
            previous_ids = known_ids


if __name__ == "__main__":
    unittest.main()
