from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .formal_contract import canonical_sha256

FINAL_LADDER_PROFILE_ID = "alignment_step5_final.v1"
MULTI_SEED_NIGHTLY_PROFILE_ID = "alignment_step5_multiseed_nightly.v1"
MULTI_SEED_NIGHTLY_SEEDS = tuple(range(41, 51))

ControlKind = Literal["exit_only", "entry_only", "saturated_flow", "mixed"]
ControlRole = Literal["ladder_rung", "qualification_control"]


@dataclass(frozen=True)
class SaturatedFlowRegistration:
    registration_id: str
    coordinate_frame: str
    line_start_m: tuple[float, float]
    line_end_m: tuple[float, float]
    crossing_direction: Literal["negative_to_positive"]
    effective_width_m: float
    window_start_s: float
    window_end_s: float
    continuity_bin_s: float
    minimum_active_bin_fraction: float
    minimum_specific_flow_p_m_s: float
    maximum_specific_flow_p_m_s: float
    physical_mapping: str


@dataclass(frozen=True)
class FormalControlSpec:
    control_id: str
    kind: ControlKind
    role: ControlRole
    minutes: int
    horizon_steps: int
    demand_minutes: int
    entry_count_hour: int
    exit_count_hour: int
    seed: int
    require_final_acceptance: bool
    expected_departed_trains: int | None
    saturated_flow: SaturatedFlowRegistration | None = None

    def __post_init__(self) -> None:
        if self.minutes <= 0 or self.horizon_steps <= 0 or self.demand_minutes <= 0:
            raise ValueError("formal control durations must be positive")
        if self.horizon_steps > self.minutes * 60:
            raise ValueError("formal horizon cannot exceed the registered scenario horizon")
        if self.demand_minutes > self.minutes:
            raise ValueError("formal demand duration cannot exceed the scenario horizon")
        if min(self.entry_count_hour, self.exit_count_hour, self.seed) < 0:
            raise ValueError("formal demand and seed values must be non-negative")
        is_qualifier = self.role == "qualification_control"
        if is_qualifier != (self.saturated_flow is not None):
            raise ValueError("qualification controls require saturated-flow registration")
        if self.kind == "mixed" and not self.require_final_acceptance:
            raise ValueError("mixed publication control requires final acceptance")
        if self.require_final_acceptance and self.recovery_window_steps <= 0:
            raise ValueError(
                "final-acceptance controls require a positive recovery window"
            )

    @property
    def recovery_window_steps(self) -> int:
        """Steps after the registered demand window used only for system drain."""

        return self.horizon_steps - self.demand_minutes * 60

    def as_payload(self) -> dict:
        payload = asdict(self)
        payload["recovery_window_steps"] = self.recovery_window_steps
        return payload

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.as_payload())


@dataclass(frozen=True)
class FormalControlProfile:
    profile_id: str
    scene_id: str
    controls: tuple[FormalControlSpec, ...]
    publication_control_id: str | None
    publication_scope: Literal["active_simulation_v5", "nightly_seed_bundle"]

    def __post_init__(self) -> None:
        ids = tuple(control.control_id for control in self.controls)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("formal profile requires unique controls")
        if self.publication_scope == "active_simulation_v5":
            if ids != (
                "exit-only-350",
                "entry-only-600",
                "entry-tail-saturated-flow",
                "mixed-600",
            ):
                raise ValueError("Step 5 final profile order is frozen")
            if self.publication_control_id != ids[-1]:
                raise ValueError("only the final mixed control may publish")
        elif self.publication_control_id is not None:
            raise ValueError("nightly seed bundles do not switch the active manifest")

    def as_payload(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "scene_id": self.scene_id,
            "controls": [control.as_payload() for control in self.controls],
            "publication_control_id": self.publication_control_id,
            "publication_scope": self.publication_scope,
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.as_payload())


ENTRY_TAIL_SATURATED_FLOW = SaturatedFlowRegistration(
    registration_id="platform_boarding.entry_tail.v1",
    coordinate_frame="station_model_meters",
    line_start_m=(8.0, 19.0),
    line_end_m=(8.0, 17.4),
    crossing_direction="negative_to_positive",
    effective_width_m=1.6,
    window_start_s=120.0,
    window_end_s=300.0,
    continuity_bin_s=10.0,
    minimum_active_bin_fraction=0.8,
    minimum_specific_flow_p_m_s=1.2,
    maximum_specific_flow_p_m_s=1.5,
    physical_mapping=(
        "Vertical section x=8.0m across the 1.6m entry-tail corridor between "
        "entrance_a and entry_gate_bank_a in alignment_platform_proxy_v1; endpoint order "
        "makes station-positive-x travel negative-to-positive."
    ),
)


def final_ladder_profile() -> FormalControlProfile:
    controls = (
        FormalControlSpec(
            "exit-only-350",
            "exit_only",
            "ladder_rung",
            6,
            350,
            5,
            0,
            4404,
            42,
            True,
            1,
        ),
        FormalControlSpec(
            "entry-only-600",
            "entry_only",
            "ladder_rung",
            15,
            900,
            10,
            2500,
            0,
            42,
            True,
            3,
        ),
        FormalControlSpec(
            "entry-tail-saturated-flow",
            "saturated_flow",
            "qualification_control",
            5,
            300,
            5,
            7200,
            0,
            42,
            False,
            None,
            ENTRY_TAIL_SATURATED_FLOW,
        ),
        FormalControlSpec(
            "mixed-600",
            "mixed",
            "ladder_rung",
            15,
            900,
            10,
            2500,
            2200,
            42,
            True,
            3,
        ),
    )
    return FormalControlProfile(
        FINAL_LADDER_PROFILE_ID,
        "platform_boarding",
        controls,
        "mixed-600",
        "active_simulation_v5",
    )


def multi_seed_nightly_profile(seed: int) -> FormalControlProfile:
    if seed not in MULTI_SEED_NIGHTLY_SEEDS:
        raise ValueError(f"nightly seed must be one of {MULTI_SEED_NIGHTLY_SEEDS}")
    control = FormalControlSpec(
        "mixed-600",
        "mixed",
        "ladder_rung",
        15,
        900,
        10,
        2500,
        2200,
        seed,
        True,
        3,
    )
    return FormalControlProfile(
        MULTI_SEED_NIGHTLY_PROFILE_ID,
        "platform_boarding",
        (control,),
        None,
        "nightly_seed_bundle",
    )
