"""Versioned manifest for evacuation-routing plugins."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


ALGORITHM_PLUGIN_SCHEMA_VERSION = "algorithm-plugin/v1"
EVACUATION_ROUTING_API_VERSION = "evacuation-routing/v1"
EVACUATION_ROUTING_KIND = "evacuation_routing"
SUPPORTED_CAPABILITIES = frozenset({"closures", "deterministic_seed", "diagnostics", "group_facts"})
_PLUGIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class AlgorithmManifest:
    plugin_id: str
    plugin_version: str
    entry_point: tuple[str, ...]
    parameter_schema: dict[str, Any]
    capabilities: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    kind: str = EVACUATION_ROUTING_KIND
    api_version: str = EVACUATION_ROUTING_API_VERSION
    schema_version: str = ALGORITHM_PLUGIN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ALGORITHM_PLUGIN_SCHEMA_VERSION:
            raise ValueError(f"unsupported algorithm manifest schema: {self.schema_version!r}")
        if self.kind != EVACUATION_ROUTING_KIND:
            raise ValueError(f"unsupported algorithm plugin kind: {self.kind!r}")
        if self.api_version != EVACUATION_ROUTING_API_VERSION:
            raise ValueError(f"unsupported evacuation routing API: {self.api_version!r}")
        if not _PLUGIN_ID_PATTERN.fullmatch(self.plugin_id):
            raise ValueError(f"invalid plugin_id: {self.plugin_id!r}")
        if not self.plugin_version.strip():
            raise ValueError("plugin_version must not be blank")
        if not self.entry_point or any(not item.strip() for item in self.entry_point):
            raise ValueError("entry_point must contain non-blank command arguments")
        unknown = sorted(set(self.capabilities) - SUPPORTED_CAPABILITIES)
        if unknown:
            raise ValueError("unsupported plugin capabilities: " + ", ".join(unknown))
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("plugin capabilities must not contain duplicates")
        _require_json_compatible(self.parameter_schema, "plugin parameter_schema")
        _require_json_compatible(self.metadata, "plugin metadata")
        self._validate_parameter_schema()

    def validate_parameters(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        canonical = deepcopy(dict(parameters))
        try:
            Draft202012Validator(self.parameter_schema).validate(canonical)
        except ValidationError as exc:
            location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
            raise ValueError(f"invalid plugin parameters at {location}: {exc.message}") from exc
        _require_json_compatible(canonical, "plugin parameters")
        return canonical

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "api_version": self.api_version,
            "entry_point": list(self.entry_point),
            "parameter_schema": deepcopy(self.parameter_schema),
            "capabilities": list(self.capabilities),
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AlgorithmManifest:
        values = dict(payload)
        entry_point = values.get("entry_point", ())
        capabilities = values.get("capabilities", ())
        parameter_schema = values.get("parameter_schema", {})
        metadata = values.get("metadata", {})
        if not isinstance(entry_point, list | tuple):
            raise ValueError("manifest entry_point must be an array")
        if not isinstance(capabilities, list | tuple):
            raise ValueError("manifest capabilities must be an array")
        if not isinstance(parameter_schema, dict) or not isinstance(metadata, dict):
            raise ValueError("manifest parameter_schema and metadata must be objects")
        values["entry_point"] = tuple(str(item) for item in entry_point)
        values["capabilities"] = tuple(str(item) for item in capabilities)
        values["parameter_schema"] = deepcopy(parameter_schema)
        values["metadata"] = deepcopy(metadata)
        return cls(**values)

    def _validate_parameter_schema(self) -> None:
        if self.parameter_schema.get("type") != "object":
            raise ValueError("plugin parameter_schema must describe an object")
        try:
            Draft202012Validator.check_schema(self.parameter_schema)
        except SchemaError as exc:
            raise ValueError(f"invalid plugin parameter_schema: {exc.message}") from exc


def _require_json_compatible(value: Any, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite JSON-compatible data") from exc
