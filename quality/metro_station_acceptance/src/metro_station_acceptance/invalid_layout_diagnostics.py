from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from metro_station.adapters.simulation.compilation.validation import validate_station_design
from metro_station_testkit.invalid_layout_cases import invalid_layout_cases


@dataclass(frozen=True)
class InvalidLayoutDiagnosticRecord:
    case_id: str
    expected_code: str
    expected_codes: tuple[str, ...]
    actual_codes: tuple[str, ...]

    @property
    def status(self) -> str:
        return (
            "ok"
            if self.expected_code in self.actual_codes
            and set(self.actual_codes) == set(self.expected_codes)
            else "review"
        )

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, **asdict(self)}


@dataclass(frozen=True)
class InvalidLayoutDiagnosticsReport:
    records: tuple[InvalidLayoutDiagnosticRecord, ...]

    @property
    def status(self) -> str:
        return (
            "ok"
            if self.records and all(record.status == "ok" for record in self.records)
            else "review"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "records": [record.as_dict() for record in self.records],
        }


def inspect_invalid_layout_diagnostics() -> InvalidLayoutDiagnosticsReport:
    records = tuple(
        InvalidLayoutDiagnosticRecord(
            case_id=case.case_id,
            expected_code=case.expected_code,
            expected_codes=case.expected_codes,
            actual_codes=tuple(issue.code for issue in validate_station_design(case.document)),
        )
        for case in invalid_layout_cases()
    )
    return InvalidLayoutDiagnosticsReport(records)
