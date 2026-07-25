from __future__ import annotations

import unittest
from collections import deque
from dataclasses import FrozenInstanceError, asdict
import hashlib
import json

from content import cube as cube_content
from game import cube
from game import cube_catalog


def _adjacency(spec: cube.CubeSpec, *, blocked: set[int] | None = None):
    blocked = blocked or set()
    result = {room.room_id: set() for room in spec.rooms if room.room_id not in blocked}
    for passage in spec.passages:
        if passage.room_a in blocked or passage.room_b in blocked:
            continue
        result[passage.room_a].add(passage.room_b)
        result[passage.room_b].add(passage.room_a)
    return result


def _reachable(
    spec: cube.CubeSpec,
    *,
    blocked: set[int] | None = None,
    apply_transfers: bool = False,
) -> set[int]:
    blocked = blocked or set()
    if spec.start_room_id in blocked:
        return set()
    adjacency = _adjacency(spec, blocked=blocked)
    seen = {spec.start_room_id}
    queue = deque([spec.start_room_id])
    while queue:
        source = queue.popleft()
        for entered in adjacency[source]:
            if entered == spec.prize_room_id:
                seen.add(entered)
                continue
            room = spec.room(entered)
            target = entered
            if apply_transfers and room.effect_kind in cube.TRANSFER_EFFECTS:
                target = room.effect_target_room_id
            if target is None or target in blocked or target in seen:
                continue
            seen.add(target)
            queue.append(target)
    return seen


def _distance(spec: cube.CubeSpec) -> int:
    adjacency = _adjacency(spec)
    distance = {spec.start_room_id: 0}
    queue = deque([spec.start_room_id])
    while queue:
        source = queue.popleft()
        if source == spec.prize_room_id:
            return distance[source]
        for target in adjacency[source]:
            if target not in distance:
                distance[target] = distance[source] + 1
                queue.append(target)
    raise AssertionError("prize is not reachable")


def _component_map_without(spec: cube.CubeSpec, blocked_room: int) -> dict[int, int]:
    adjacency = _adjacency(spec, blocked={blocked_room})
    result = {}
    for first in adjacency:
        if first in result:
            continue
        component_id = len(result) + 1
        result[first] = component_id
        queue = deque([first])
        while queue:
            source = queue.popleft()
            for target in adjacency[source]:
                if target not in result:
                    result[target] = component_id
                    queue.append(target)
    return result


class CubeGeneratorTests(unittest.TestCase):
    def test_layout_v1_matches_golden_fingerprints(self) -> None:
        expected = {
            0: "fb60ab139df18e48debabe28354ee01d89674b40c8d8f25ccd1a9ba89410b6eb",
            1: "0addd001b21a2b31c6751fc8c0ea9d0dca7d3ee207121c2f5829d6a5129eb4a5",
            2: "561610ccfa8a38397ad0983456ccf98a8522917c9a0cb9cbd8dc0f2f807d087c",
            42: "47918635378c279cbb7899080a24522713a3cf9ccfa5ebcaf96b6329d0a1aef5",
            77: "4828f79e9d171c4da1d19a7992e5fef89ddd467004b43630a8db856c85e1efa5",
        }
        for seed, fingerprint in expected.items():
            with self.subTest(seed=seed):
                payload = json.dumps(
                    asdict(cube.generate_cube(seed, layout_version=1)),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self.assertEqual(
                    fingerprint,
                    hashlib.sha256(payload.encode()).hexdigest(),
                )

    def test_room_catalog_is_complete_and_versioned(self) -> None:
        policy = cube_catalog.layout_policy(1)
        self.assertEqual(1, policy.version)
        self.assertLessEqual(
            set(policy.hazard_keys),
            set(cube_catalog.HAZARD_BY_KIND),
        )
        self.assertEqual(
            set(cube_catalog.HAZARD_BY_KIND),
            set(cube_content.HAZARD_TEXTS),
        )
        self.assertEqual(
            set(cube_catalog.EFFECT_BY_KIND),
            set(cube_content.EFFECT_TEXTS),
        )
        self.assertLessEqual(
            set(cube_catalog.layout_item_keys(1)),
            set(cube_catalog.CUBE_ITEM_BY_KEY),
        )
        for item_key in cube_catalog.layout_item_keys(1):
            with self.subTest(item_key=item_key):
                self.assertIn(item_key, cube.ITEM_CONSUMPTION)
                self.assertLessEqual(len(item_key.encode()), 20)
                self.assertEqual(
                    1,
                    cube_catalog.cube_item_use(item_key).wrong_consume_qty,
                )

    def test_every_generated_special_room_resolves_through_catalog(self) -> None:
        for seed in range(64):
            for room in cube.generate_cube(seed).rooms:
                with self.subTest(seed=seed, room_id=room.room_id):
                    if room.hazard_kind:
                        definition = cube_catalog.hazard_definition(room.hazard_kind)
                        self.assertIsNotNone(definition)
                        self.assertEqual(definition.description_key, room.description_key)
                    if room.effect_kind:
                        definition = cube_catalog.effect_definition(room.effect_kind)
                        self.assertIsNotNone(definition)
                        self.assertEqual(definition.description_key, room.description_key)
                    self.assertIn(room.description_key, cube_content.ROOM_DESCRIPTIONS)

    def test_same_seed_produces_same_frozen_spec(self) -> None:
        first = cube.generate_cube(20260723)
        second = cube.generate_cube(20260723)

        self.assertEqual(first, second)
        with self.assertRaises(FrozenInstanceError):
            first.seed = 1
        with self.assertRaises(FrozenInstanceError):
            first.rooms[0].code = 999

    def test_many_seeds_preserve_topology_and_hazard_invariants(self) -> None:
        for seed in range(256):
            with self.subTest(seed=seed):
                spec = cube.generate_cube(seed)
                self.assertEqual(4, spec.size)
                self.assertEqual(set(range(16)), {room.room_id for room in spec.rooms})
                self.assertEqual(16, len({(room.row, room.column) for room in spec.rooms}))
                self.assertEqual(16, len({room.code for room in spec.rooms}))
                self.assertGreaterEqual(_distance(spec), 6)

                edges = {(p.room_a, p.room_b) for p in spec.passages}
                self.assertEqual(len(edges), len(spec.passages))
                self.assertEqual(15, sum(not p.is_extra for p in spec.passages))
                self.assertIn(sum(p.is_extra for p in spec.passages), range(2, 5))
                for passage in spec.passages:
                    self.assertLess(passage.room_a, passage.room_b)
                    self.assertEqual(
                        1,
                        abs(spec.room(passage.room_a).row - spec.room(passage.room_b).row)
                        + abs(spec.room(passage.room_a).column - spec.room(passage.room_b).column),
                    )

                start = spec.room(spec.start_room_id)
                prize = spec.room(spec.prize_room_id)
                self.assertEqual(cube.ROOM_START, start.kind)
                self.assertEqual(cube.ROOM_PRIZE, prize.kind)
                self.assertIsNone(start.effect_kind)
                self.assertIsNone(prize.effect_kind)

                hazards = [room for room in spec.rooms if room.hazard_kind]
                required = [room for room in hazards if room.is_required]
                self.assertEqual([spec.mandatory_room_id], [room.room_id for room in required])
                self.assertIn(len(hazards), range(1, 4))
                self.assertEqual(len(hazards), len({room.hazard_kind for room in hazards}))
                for room in hazards:
                    rule = cube.HAZARD_BY_KIND[room.hazard_kind]
                    self.assertEqual(rule.item_key, room.required_item_key)
                    self.assertEqual(rule.consume_qty, room.consume_qty)

                self.assertNotIn(
                    spec.prize_room_id,
                    _reachable(spec, blocked={spec.mandatory_room_id}, apply_transfers=True),
                )
                optional = {room.room_id for room in hazards if not room.is_required}
                self.assertIn(
                    spec.prize_room_id,
                    _reachable(spec, blocked=optional, apply_transfers=True),
                )

    def test_transfer_anomalies_stay_on_their_side_of_mandatory_room(self) -> None:
        for seed in range(128):
            spec = cube.generate_cube(seed)
            components = _component_map_without(spec, spec.mandatory_room_id)
            transfer_rooms = [
                room
                for room in spec.rooms
                if room.effect_kind in cube.TRANSFER_EFFECTS
            ]
            self.assertEqual(3, len(transfer_rooms))
            for room in transfer_rooms:
                self.assertIsNotNone(room.effect_target_room_id)
                self.assertEqual(
                    components[room.room_id],
                    components[room.effect_target_room_id],
                )
                target = spec.room(room.effect_target_room_id)
                self.assertNotEqual(cube.ROOM_PRIZE, target.kind)
                self.assertNotEqual(cube.ROOM_HAZARD, target.kind)
                self.assertEqual(str(target.code), room.effect_arg)

            tunnels = [room for room in transfer_rooms if room.effect_kind == cube.EFFECT_TUNNEL]
            self.assertEqual(2, len(tunnels))
            self.assertEqual(tunnels[0].room_id, tunnels[1].effect_target_room_id)
            self.assertEqual(tunnels[1].room_id, tunnels[0].effect_target_room_id)

    def test_item_whitelist_matches_canonical_registry_contract(self) -> None:
        self.assertEqual(
            {
                "bucket": 0,
                "rod": 0,
                "znak": 0,
                "lockpicks": 0,
                "bait_1": 1,
                "bait_3": 1,
                "milk_can": 1,
                "egg": 1,
            },
            cube.ITEM_CONSUMPTION,
        )
        self.assertEqual(set(cube.HAZARD_BY_KIND), set(cube_content.HAZARD_TEXTS))
        spec = cube.generate_cube(77)
        for room in spec.rooms:
            self.assertIn(room.description_key, cube_content.ROOM_DESCRIPTIONS)

    def test_direction_helpers_respect_grid_edges(self) -> None:
        self.assertEqual(1, cube.grid_neighbor(0, cube.Direction.EAST))
        self.assertEqual(4, cube.grid_neighbor(0, cube.Direction.SOUTH))
        self.assertIsNone(cube.grid_neighbor(0, cube.Direction.NORTH))
        self.assertIsNone(cube.grid_neighbor(3, cube.Direction.EAST))
        self.assertEqual(cube.Direction.WEST, cube.opposite_direction("e"))
        self.assertEqual(cube.Direction.NORTH, cube.direction_between(5, 1))

    def test_new_spec_accepts_injected_entropy_and_version_is_strict(self) -> None:
        self.assertEqual(cube.generate_cube(42), cube.new_cube_spec(randbits=lambda _: 42))
        with self.assertRaises(ValueError):
            cube.generate_cube(42, layout_version=2)


if __name__ == "__main__":
    unittest.main()
