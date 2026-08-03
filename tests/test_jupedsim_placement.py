from __future__ import annotations

import unittest
from types import SimpleNamespace

from shapely.geometry import box

from sandbox.metro_station_sandbox.movement.jps_adapter import JuPedSimWalkingSession


class _Simulation:
    def __init__(self, positions: tuple[tuple[float, float], ...]) -> None:
        self._agents = tuple(
            SimpleNamespace(id=index + 1, position=position)
            for index, position in enumerate(positions)
        )

    def agents(self):
        return self._agents

    def agent(self, sim_id: int):
        return next(agent for agent in self._agents if agent.id == sim_id)

    def agent_count(self) -> int:
        return len(self._agents)


class JuPedSimPlacementTests(unittest.TestCase):
    def session(self, positions=()) -> JuPedSimWalkingSession:
        session = object.__new__(JuPedSimWalkingSession)
        session.agent_radius = 0.2
        session.geometry = box(-10.0, -10.0, 10.0, 10.0)
        session._simulation = _Simulation(tuple(positions))
        session._agent_ids = {index + 10: index + 1 for index in range(len(positions))}
        session._passenger_ids = {index + 1: index + 10 for index in range(len(positions))}
        session._last_positions = {}
        session._removal_records = {}
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

    def test_pending_removed_simulation_agent_does_not_block_resolution(self) -> None:
        session = self.session(((1.0, 1.0),))
        session._agent_ids = {}
        session._passenger_ids = {}

        self.assertEqual(
            (1.0, 1.0),
            session.resolve_placement(passenger_id=99, position=(1.0, 1.0)),
        )


if __name__ == "__main__":
    unittest.main()
