from __future__ import annotations

import torch
from pathlib import Path

from metro_torch_p1.calibration import run_autograd_gradient_check, run_real_data_like_calibration
from metro_torch_p1.scenarios import run_validation_scenarios


def test_p1_validation_scenarios_contract() -> None:
    outcomes = run_validation_scenarios("cpu")
    assert len(outcomes) >= 10
    assert all(item.name for item in outcomes)
    joint_contact = next(item for item in outcomes if item.name == "P1-01_joint_contact_300")
    assert joint_contact.passed
    assert joint_contact.metrics["minimum_agent_gap_m"] >= -0.001


def test_p1_autograd_gate_runs() -> None:
    result = run_autograd_gradient_check("cpu")
    assert result is not None


def test_cpu_available_for_experiment() -> None:
    assert torch.device("cpu") == torch.device("cpu")


def test_json_real_data_loading_fallback(tmp_path: Path) -> None:
    dataset = tmp_path / "traj.json"
    dataset.write_text(
        """
        {
          "trajectory": [
            [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]],
            [[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]],
            [[0.0, 2.0], [1.0, 3.0], [2.0, 4.0]]
          ]
        }
        """,
        encoding="utf-8",
    )
    results = run_real_data_like_calibration(
        device="cpu",
        dataset_path=str(dataset),
        steps=3,
        budgets=[8],
    )
    assert len(results) == 1
    assert results[0].train_steps > 0
    assert torch.isfinite(torch.tensor(results[0].holdout_loss))
    assert "from-dataset" in results[0].notes


def test_csv_real_data_loading_and_fallback(tmp_path: Path) -> None:
    dataset = tmp_path / "traj.csv"
    dataset.write_text(
        "frame,id,x,y\n0,1,0,0\n1,1,1,1\n2,1,2,2\n"
        "0,2,0,1\n1,2,1,2\n2,2,2,3\n",
        encoding="utf-8",
    )
    results = run_real_data_like_calibration(
        device="cpu",
        dataset_path=str(dataset),
        steps=3,
        budgets=[8],
        seed=11,
    )
    assert len(results) == 1
    assert results[0].holdout_steps == 1
    assert torch.isfinite(torch.tensor(results[0].holdout_loss))
    assert results[0].dataset.endswith("traj.csv")


def test_juelich_txt_real_data_loader(tmp_path: Path) -> None:
    dataset = tmp_path / "fd1_n14.txt"
    dataset.write_text(
        "1 0 100 0\n1 1 101 0.2\n1 2 102 0.3\n1 3 103 0.4\n"
        "2 0 100 1\n2 1 101 1.2\n2 2 102 1.3\n2 3 103 1.4\n",
        encoding="utf-8",
    )
    results = run_real_data_like_calibration(
        device="cpu",
        dataset_path=str(dataset),
        steps=4,
        budgets=[4],
        seed=13,
    )
    assert len(results) == 1
    assert "txt:juelich" in results[0].notes
    assert torch.isfinite(torch.tensor(results[0].holdout_loss))


def test_missing_real_data_falls_back_with_notes() -> None:
    results = run_real_data_like_calibration(
        device="cpu",
        dataset_path="__surely_missing_file__",
        steps=12,
        budgets=[8],
    )
    assert len(results) == 1
    assert "synthetic-fallback" in results[0].notes
    assert results[0].train_macro_loss >= 0.0
