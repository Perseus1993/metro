from __future__ import annotations


def runtime_event_id(
    passenger_id: int,
    kind: str,
    value: str,
    time_seconds: float,
) -> str:
    return f"p{int(passenger_id)}:{kind}:{value}:t{float(time_seconds):.6f}"


def runtime_episode_event_id(
    passenger_id: int,
    kind: str,
    value: str,
    episode: str,
) -> str:
    """Identify a fact once per external lifecycle episode.

    Unlike interval observations, train availability/capacity facts describe
    one train run and should not become distinct domain events merely because
    the coordinator polls them again on the next simulation tick.
    """

    return f"p{int(passenger_id)}:{kind}:{value}:episode:{episode}"
