from __future__ import annotations

from dataclasses import asdict, dataclass


UNCALIBRATED = "uncalibrated"
CALIBRATED = "calibrated"
VALIDATED = "validated"
SUPPORTED_CALIBRATION_STATUSES = frozenset({UNCALIBRATED, CALIBRATED, VALIDATED})


@dataclass(frozen=True)
class CalibrationProfile:
    """Evidence metadata for parameters; it does not pretend to be the calibration itself."""

    profile_id: str = "default_uncalibrated"
    status: str = UNCALIBRATED
    calibration_dataset_id: str | None = None
    validation_dataset_id: str | None = None
    notes: str = "Default parameters have not been calibrated against station observations."

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("calibration profile_id must not be empty")
        if self.status not in SUPPORTED_CALIBRATION_STATUSES:
            choices = ", ".join(sorted(SUPPORTED_CALIBRATION_STATUSES))
            raise ValueError(f"calibration status must be one of {choices}; got {self.status!r}")
        if self.status in {CALIBRATED, VALIDATED} and not self.calibration_dataset_id:
            raise ValueError("calibrated profiles require calibration_dataset_id")
        if self.status == VALIDATED and not self.validation_dataset_id:
            raise ValueError("validated profiles require validation_dataset_id")
        if (
            self.calibration_dataset_id
            and self.validation_dataset_id
            and self.calibration_dataset_id == self.validation_dataset_id
        ):
            raise ValueError("calibration and validation datasets must be independent")

    @property
    def research_ready(self) -> bool:
        return self.status == VALIDATED

    def as_dict(self) -> dict[str, str | bool | None]:
        return {**asdict(self), "research_ready": self.research_ready}
