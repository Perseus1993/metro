"""JSON serialization for routing-plugin contracts."""

from __future__ import annotations

import json
from typing import Any, Callable, TypeVar

from .contracts import EvacuationRoutingRequest, EvacuationRoutingResponse
from .manifest import AlgorithmManifest


T = TypeVar("T")


def manifest_to_json(manifest: AlgorithmManifest, *, indent: int | None = 2) -> str:
    return _to_json(manifest.as_dict(), indent)


def manifest_from_json(source: str | bytes) -> AlgorithmManifest:
    return _from_json(source, AlgorithmManifest.from_dict, "algorithm manifest")


def routing_request_to_json(
    request: EvacuationRoutingRequest,
    *,
    indent: int | None = None,
) -> str:
    return _to_json(request.as_dict(), indent)


def routing_request_from_json(source: str | bytes) -> EvacuationRoutingRequest:
    return _from_json(source, EvacuationRoutingRequest.from_dict, "routing request")


def routing_response_to_json(
    response: EvacuationRoutingResponse,
    *,
    indent: int | None = None,
) -> str:
    return _to_json(response.as_dict(), indent)


def routing_response_from_json(source: str | bytes) -> EvacuationRoutingResponse:
    return _from_json(source, EvacuationRoutingResponse.from_dict, "routing response")


def _to_json(payload: dict[str, Any], indent: int | None) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        indent=indent,
        sort_keys=True,
        separators=(",", ":") if indent is None else None,
    ) + ("\n" if indent is not None else "")


def _from_json(source: str | bytes, factory: Callable[[dict[str, Any]], T], label: str) -> T:
    try:
        payload: Any = json.loads(source)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label} JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must contain an object")
    return factory(payload)
