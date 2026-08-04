from __future__ import annotations


def intermediate_waypoint_radius(
    *,
    agent_radius: float,
    final_target_radius: float,
) -> float:
    """Return the arrival tolerance for a tactical, non-final waypoint.

    A final semantic destination may deliberately use a generous region
    tolerance.  Reusing that tolerance at a navigation-mesh corner lets an
    agent advance to the next segment before it has cleared the obstacle.
    Keep tactical waypoints precise while retaining a small numerical and
    integration tolerance.
    """

    body_radius = max(0.0, float(agent_radius))
    final_radius = max(0.001, float(final_target_radius))
    # Social-force wall repulsion settles a body a few centimetres outside its
    # geometric radius.  Five centimetres covers that physical equilibrium
    # while remaining far below both a pedestrian radius and the semantic
    # destination tolerance (typically 0.45 m).
    return min(final_radius, max(0.05, body_radius * 0.25))


def tactical_route_clearance(
    *,
    agent_radius: float,
    final_target_radius: float,
) -> float:
    """Return the body-centre clearance shared by compiler and runtime.

    JuPedSim enforces the body radius continuously.  The small tactical-stage
    tolerance is an arrival detector, not an extra body radius; adding it to
    the navigation erosion would incorrectly reject corridors that are
    physically wide enough for the configured body.
    """

    del final_target_radius
    return max(0.0, float(agent_radius))
