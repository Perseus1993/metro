from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


LAYOUT_RECIPE_SCHEMA_VERSION = "layout_recipe.v1"
SCENARIO_CORPUS_SCHEMA_VERSION = "scenario_corpus.v1"
LAYOUT_GENERATOR_VERSION = "constraint_layout_generator.v2"

ARCHETYPES = (
    "single_terminal",
    "two_level_island",
    "two_level_multi_access",
    "three_level_transfer",
)
ASSET_DENSITIES = ("sparse", "standard", "dense")
OPERATION_PROFILES = (
    "normal",
    "congested",
    "facility_closure",
    "train_full",
    "train_outage",
)
TOPOLOGY_FOOTPRINTS = ("RECT", "L", "T", "NECK", "U")
VERTICAL_TOPOLOGIES = ("FULL", "CHAIN", "DUAL_CLUSTER")
FARE_TOPOLOGIES = ("BIDIRECTIONAL", "SPLIT_ENTRY_EXIT")


@dataclass(frozen=True)
class LayoutRecipe:
    recipe_id: str
    seed: int
    archetype: str
    entrance_count: int
    gate_count: int
    elevator_count: int
    stairs_count: int
    escalator_pair_count: int
    mirror: bool
    asset_density: str
    geometry_variant: int
    operation_profile: str = "normal"
    topology_footprint: str = "RECT"
    vertical_topology: str = "FULL"
    requested_vertical_topology: str | None = None
    fare_topology: str = "BIDIRECTIONAL"
    schema_version: str = LAYOUT_RECIPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LAYOUT_RECIPE_SCHEMA_VERSION:
            raise ValueError(f"unsupported layout recipe schema {self.schema_version!r}")
        if self.archetype not in ARCHETYPES:
            raise ValueError(f"unknown layout archetype {self.archetype!r}")
        if self.asset_density not in ASSET_DENSITIES:
            raise ValueError(f"unknown asset density {self.asset_density!r}")
        if self.operation_profile not in OPERATION_PROFILES:
            raise ValueError(f"unknown operation profile {self.operation_profile!r}")
        if self.topology_footprint not in TOPOLOGY_FOOTPRINTS:
            raise ValueError(f"unknown topology footprint {self.topology_footprint!r}")
        if self.vertical_topology not in VERTICAL_TOPOLOGIES:
            raise ValueError(f"unknown vertical topology {self.vertical_topology!r}")
        if (
            self.requested_vertical_topology is not None
            and self.requested_vertical_topology not in VERTICAL_TOPOLOGIES
        ):
            raise ValueError(
                "unknown requested vertical topology "
                f"{self.requested_vertical_topology!r}"
            )
        if self.fare_topology not in FARE_TOPOLOGIES:
            raise ValueError(f"unknown fare topology {self.fare_topology!r}")
        if not 1 <= self.entrance_count <= 4:
            raise ValueError("entrance_count must be between 1 and 4")
        if not 1 <= self.gate_count <= 2:
            raise ValueError("gate_count must be between 1 and 2")
        if self.level_count == 1 and self.elevator_count != 0:
            raise ValueError("single-level recipes cannot contain elevators")
        if self.level_count > 1 and not 1 <= self.elevator_count <= 6:
            raise ValueError("multi-level elevator_count must be between 1 and 6")
        if not 0 <= self.stairs_count <= 1:
            raise ValueError("stairs_count must be 0 or 1")
        if not 0 <= self.escalator_pair_count <= 1:
            raise ValueError("escalator_pair_count must be 0 or 1")
        if self.level_count == 1 and (self.stairs_count or self.escalator_pair_count):
            raise ValueError("single-level recipes cannot contain vertical connectors")
        if not 0 <= self.geometry_variant <= 8:
            raise ValueError("geometry_variant must be between 0 and 8")
        if self.vertical_topology == "CHAIN" and not (
            self.level_count == 3 and self.elevator_count >= 2
        ):
            raise ValueError("CHAIN topology requires three levels and at least two elevators")
        if self.vertical_topology == "DUAL_CLUSTER" and not (
            self.level_count > 1 and self.elevator_count >= 4
        ):
            raise ValueError("DUAL_CLUSTER topology requires multiple levels and at least four elevators")
        if self.fare_topology == "SPLIT_ENTRY_EXIT" and self.gate_count != 2:
            raise ValueError("SPLIT_ENTRY_EXIT topology requires two gates")

    @property
    def level_count(self) -> int:
        return {
            "single_terminal": 1,
            "two_level_island": 2,
            "two_level_multi_access": 2,
            "three_level_transfer": 3,
        }[self.archetype]

    @property
    def semantic_fingerprint(self) -> str:
        return _fingerprint(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "recipe_id": self.recipe_id,
            "seed": self.seed,
            "archetype": self.archetype,
            "level_count": self.level_count,
            "entrance_count": self.entrance_count,
            "gate_count": self.gate_count,
            "elevator_count": self.elevator_count,
            "stairs_count": self.stairs_count,
            "escalator_pair_count": self.escalator_pair_count,
            "mirror": self.mirror,
            "asset_density": self.asset_density,
            "geometry_variant": self.geometry_variant,
            "operation_profile": self.operation_profile,
            "topology_footprint": self.topology_footprint,
            "vertical_topology": self.vertical_topology,
            "requested_vertical_topology": self.requested_vertical_topology,
            "fare_topology": self.fare_topology,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LayoutRecipe:
        values = dict(payload)
        values.pop("level_count", None)
        return cls(**values)


@dataclass(frozen=True)
class ScenarioCorpus:
    corpus_id: str
    seed: int
    recipes: tuple[LayoutRecipe, ...]
    generator_version: str = LAYOUT_GENERATOR_VERSION
    schema_version: str = SCENARIO_CORPUS_SCHEMA_VERSION

    @property
    def semantic_fingerprint(self) -> str:
        return _fingerprint(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "recipe_count": len(self.recipes),
            "recipes": [recipe.as_dict() for recipe in self.recipes],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ScenarioCorpus:
        values = dict(payload)
        values.pop("recipe_count", None)
        values["recipes"] = tuple(LayoutRecipe.from_dict(item) for item in values["recipes"])
        return cls(**values)


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
