from __future__ import annotations


def runtime_event_id(
    passenger_id: int,
    kind: str,
    value: str,
    time_seconds: float,
) -> str:
    return f"p{int(passenger_id)}:{kind}:{value}:t{float(time_seconds):.6f}"
