from __future__ import annotations

import torch

from metro_torch_p0.calibration import run_calibration_evidence
from metro_torch_p0.integration import run_metro_boundary_smoke
from metro_torch_p0.scenarios import run_validation_scenarios


def test_micro_scenarios_pass_on_cpu() -> None:
    outcomes = run_validation_scenarios("cpu")
    assert len(outcomes) == 7
    assert all(outcome.passed for outcome in outcomes)


def test_relaxation_time_is_differentiable_and_recoverable() -> None:
    evidence = run_calibration_evidence("cpu")
    assert evidence.passed
    assert evidence.relative_gradient_error < 0.03


def test_metro_accepts_experimental_backend_through_existing_boundary() -> None:
    evidence = run_metro_boundary_smoke("cpu")
    assert evidence.passed


def test_cuda_is_available_for_the_p0_environment() -> None:
    assert torch.cuda.is_available()
