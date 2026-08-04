from __future__ import annotations

import unittest
from types import SimpleNamespace

from shapely.geometry import box

from sandbox.metro_station_sandbox.movement.jps_adapter import JuPedSimWalkingSession
from metro_station.adapters.simulation.movement.jps_adapter import (
    JuPedSimPlacementBlocked,
    JuPedSimRelocationRejected,
    JuPedSimRemovalRejected,
    _JourneyTarget,
)


class _Simulation:
    def __init__(self, positions: tuple[tuple[float, float], ...]) -> None:
        self._agents = tuple(
            SimpleNamespace(id=index + 1, position=position)
            for index, position in enumerate(positions)
        )
        self.mark_result = True
        self.marked_ids: list[int] = []
        self.direct_lookup_available = True
        self.switch_calls: list[tuple[int, int, int]] = []

    def agents(self):
        return self._agents

    def agent(self, sim_id: int):
        if not self.direct_lookup_available:
            raise RuntimeError("direct lookup unavailable at this boundary")
        return next(agent for agent in self._agents if agent.id == sim_id)

    def agent_count(self) -> int:
        return len(self._agents)

    def mark_agent_for_removal(self, sim_id: int) -> bool:
        self.marked_ids.append(int(sim_id))
        return self.mark_result

    def switch_agent_journey(self, sim_id: int, journey_id: int, stage_id: int) -> None:
        self.switch_calls.append((int(sim_id), int(journey_id), int(stage_id)))


class JuPedSimPlacementTests(unittest.TestCase):
    def session(self, positions=()) -> JuPedSimWalkingSession:
        session = object.__new__(JuPedSimWalkingSession)
        session.agent_radius = 0.2
        session.geometry = box(-10.0, -10.0, 10.0, 10.0)
        session._simulation = _Simulation(tuple(positions))
        session._agent_ids = {index + 10: index + 1 for index in range(len(positions))}
        session._passenger_ids = {index + 1: index + 10 for index in range(len(positions))}
        session._last_positions = {}
        session._agent_targets = {}
        session._agent_target_positions = {}
        session._agent_desired_speeds = {}
        session._active_episode_ids = {}
        session._removal_records = {}
        session._pending_removals = {}
        session.dt_seconds = 0.01
        session.target_radius = 0.3
        return session

    def test_candidate_clearance_rejects_overlapping_agent(self) -> None:
        session = self.session(((1.0, 1.0),))

        self.assertFalse(session._candidate_has_agent_clearance((1.1, 1.0)))
        self.assertTrue(session._candidate_has_agent_clearance((1.5, 1.0)))

    def test_dense_placement_search_extends_beyond_two_metres(self) -> None:
        session = self.session()

        candidates = list(session._placement_candidates((0.0, 0.0), passenger_id=167))
        max_distance = max((x * x + y * y) ** 0.5 for x, y in candidates)

        self.assertGreater(max_distance, 5.0)
        self.assertGreater(len(candidates), 500)

    def test_read_only_placement_resolution_never_creates_an_agent(self) -> None:
        session = self.session(((1.0, 1.0),))
        before = session.agent_count

        resolved = session.resolve_placement(
            passenger_id=99,
            position=(1.1, 1.0),
        )

        self.assertEqual(before, session.agent_count)
        self.assertGreaterEqual(
            ((resolved[0] - 1.0) ** 2 + (resolved[1] - 1.0) ** 2) ** 0.5,
            session.agent_radius * 2.05,
        )

    def test_unowned_native_body_still_blocks_resolution(self) -> None:
        session = self.session(((1.0, 1.0),))
        session._agent_ids = {}
        session._passenger_ids = {}

        with self.assertRaises(JuPedSimPlacementBlocked):
            session.resolve_placement(
                passenger_id=99,
                position=(1.0, 1.0),
                allow_relocation=False,
            )

    def test_pending_removal_keeps_owner_and_clearance_until_confirmed(self) -> None:
        session = self.session(((1.0, 1.0),))

        session.remove_passenger(10)

        self.assertEqual({10: 1}, session._agent_ids)
        self.assertEqual({1: 10}, session._passenger_ids)
        self.assertEqual({10: 1}, session._pending_removals)
        self.assertEqual({10}, session.active_passenger_ids())
        self.assertFalse(session._candidate_has_agent_clearance((1.1, 1.0)))

        session._simulation._agents = ()
        session._capture_removed_agents({10: (1.0, 1.0)}, iteration=1)

        self.assertEqual({}, session._agent_ids)
        self.assertEqual({}, session._passenger_ids)
        self.assertEqual({}, session._pending_removals)

    def test_removal_rejection_preserves_bidirectional_identity(self) -> None:
        session = self.session(((1.0, 1.0),))
        session._simulation.mark_result = False

        with self.assertRaises(JuPedSimRemovalRejected):
            session.remove_passenger(10)

        self.assertEqual({10: 1}, session._agent_ids)
        self.assertEqual({1: 10}, session._passenger_ids)
        self.assertEqual({}, session._pending_removals)

    def test_native_id_fallback_never_uses_coordinate_as_identity(self) -> None:
        session = self.session(((1.0, 1.0),))
        session._simulation.direct_lookup_available = False

        agent = session._agent_for_id(1)

        self.assertIsNotNone(agent)
        self.assertEqual(1, agent.id)

    def test_far_place_rejects_teleport_without_marking_native_body(self) -> None:
        session = self.session(((1.0, 1.0),))

        with self.assertRaises(JuPedSimRelocationRejected):
            session.place_agent(
                passenger_id=10,
                position=(5.0, 5.0),
                target=(6.0, 5.0),
            )

        self.assertEqual([], session._simulation.marked_ids)
        self.assertEqual({10: 1}, session._agent_ids)
        self.assertEqual({}, session._pending_removals)

    def test_ensure_agent_repairs_large_mesa_drift_from_native_authority(self) -> None:
        session = self.session(((1.0, 1.0),))
        session._journey_for_target = lambda _target, _arrival_radius: _JourneyTarget(
            stage_id=3,
            journey_id=4,
            position=(9.0, 1.0),
        )
        session._set_desired_speed = lambda _agent, _speed: None

        position = session.ensure_agent(
            passenger_id=10,
            position=(8.0, 8.0),
            target=(9.0, 1.0),
            desired_speed_mps=1.2,
        )

        self.assertEqual((1.0, 1.0), position)
        self.assertEqual([], session._simulation.marked_ids)
        self.assertEqual({10: 1}, session._agent_ids)
        self.assertEqual([(1, 4, 3)], session._simulation.switch_calls)


if __name__ == "__main__":
    unittest.main()
