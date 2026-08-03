from __future__ import annotations

from typing import Any


def evict_ownerless_session(
    sessions: dict[str | None, Any],
    session_keys_by_passenger: dict[int, str | None],
    active_episode_ids: dict[int, str],
    session_key: str | None,
    session: Any,
) -> None:
    """Discard simulator-local ghosts once a session has no mapped agents."""

    if session.positions_by_passenger():
        return
    sessions.pop(session_key, None)
    for passenger_id, mapped_key in tuple(session_keys_by_passenger.items()):
        if mapped_key != session_key:
            continue
        session_keys_by_passenger.pop(passenger_id, None)
        active_episode_ids.pop(passenger_id, None)
