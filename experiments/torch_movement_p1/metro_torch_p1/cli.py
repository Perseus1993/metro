"""Command-line entry point for PM-033 P1 experiments."""

from __future__ import annotations

import argparse
from pathlib import Path

import torch

from .calibration import (
    run_jupedsim_pseudo_fit,
    run_real_data_like_calibration,
    run_synthetic_four_parameter_recovery,
)
from .evidence import generate_evidence
from .scenarios import run_validation_scenarios
from .benchmark import run_benchmarks


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PM-033 P1 experiment suite.")
    sub = parser.add_subparsers(dest="command", required=True)

    evidence = sub.add_parser("evidence", help="run blocker + calibration evidence bundle")
    evidence.add_argument("--out", type=Path, default=Path("evidence"), help="Output directory relative to this project.")
    evidence.add_argument("--device", default="cpu" if not torch.cuda.is_available() else "cuda", help="Evidence run device.")
    evidence.add_argument("--real-dataset", type=str, default=None, help="Optional real dataset file for P1-06.")
    evidence.add_argument("--synthetic-budgets", type=int, nargs="+", default=None, help="Budgets for synthetic recovery.")
    evidence.add_argument("--synthetic-seeds", type=int, nargs="+", default=None, help="Seeds for synthetic recovery.")
    evidence.add_argument("--synthetic-steps", type=int, default=64, help="Rollout length for synthetic recovery.")
    evidence.add_argument("--real-budgets", type=int, nargs="+", default=None, help="Budgets for real-data protocol.")
    evidence.add_argument("--real-steps", type=int, default=120, help="Rollout length for pseudo/real fit tasks.")
    evidence.add_argument(
        "--literature-holdout-baseline",
        type=float,
        default=None,
        help="Required holdout upper-bound for paper-go decision. e.g. 0.8",
    )
    evidence.add_argument(
        "--rp-batch-demand",
        action="store_true",
        help="If set, allow scale-up when calibration gain is not significant and throughput is healthy.",
    )

    blocker = sub.add_parser("blocker", help="run M1-M7 + P1 blocker scenarios")
    blocker.add_argument("--device", default="cpu")

    calibrate = sub.add_parser("calibration", help="run synthetic multi-parameter calibration curve")
    calibrate.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    calibrate.add_argument("--budget", type=int, default=80)
    calibrate.add_argument("--method", default="adam", choices=["adam", "l-bfgs", "cma-es", "black-box", "bayes"])
    calibrate.add_argument("--seeds", type=int, nargs="+", default=[7, 11, 13, 17], help="seed list")

    synthetic = sub.add_parser("synthetic", help="run P1-03/P1-04 synthetic recovery without evidence packaging")
    synthetic.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    synthetic.add_argument("--budgets", type=int, nargs="+", default=[20, 40, 80, 160])
    synthetic.add_argument("--seeds", type=int, nargs="+", default=[7, 11, 13, 17, 19, 23, 29, 31])
    synthetic.add_argument("--max-steps", type=int, default=64)

    pseudo = sub.add_parser("pseudo-fit", help="run P1-05 JuPedSim pseudo-observation fit")
    pseudo.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    pseudo.add_argument("--seed", type=int, default=17)
    pseudo.add_argument("--budget", type=int, default=120)
    pseudo.add_argument("--steps", type=int, default=120)

    real_data = sub.add_parser("real-data", help="run P1-06 synthetic/real dataset calibrations")
    real_data.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    real_data.add_argument("--steps", type=int, default=120)
    real_data.add_argument("--seed", type=int, default=17)
    real_data.add_argument("--dataset", type=str, default=None, help="optional dataset path")
    real_data.add_argument("--budgets", type=int, nargs="+", default=[60, 120, 160])

    throughput = sub.add_parser("throughput", help="run PM-033 throughput probe")
    throughput.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")

    args = parser.parse_args()

    if args.command == "evidence":
        json_path, markdown_path, verdict = generate_evidence(
            args.out,
            device=args.device,
            synthetic_seeds=args.synthetic_seeds,
            synthetic_budgets=args.synthetic_budgets,
            synthetic_steps=args.synthetic_steps,
            real_budgets=args.real_budgets,
            real_steps=args.real_steps,
            real_dataset=args.real_dataset,
            literature_holdout_baseline=args.literature_holdout_baseline,
            rp_batch_infra_demand=args.rp_batch_demand,
        )
    elif args.command == "blocker":
        report = run_validation_scenarios(args.device)
        verdict = "PASS" if all(item.passed for item in report) else "FAIL"
        print(f"PM-033 blocker {verdict}:")
        for item in report:
            status = "PASS" if item.passed else "FAIL"
            print(f" - {item.name}: {status}")
        return
    elif args.command == "throughput":
        for item in run_benchmarks():
            print(
                f"{item.device} | batch={item.batch_size} capacity={item.capacity} | "
                f"agent_steps_per_second={item.agent_steps_per_second:.0f} | peak_mib={item.peak_memory_mib}"
            )
        return
    elif args.command == "synthetic":
        curve = run_synthetic_four_parameter_recovery(
            device=args.device,
            budgets=args.budgets,
            seeds=args.seeds,
            max_steps=args.max_steps,
        )
        print("PM-033 synthetic 4-parameter: curve summary")
        for budget, p50, p95 in zip(curve.budgets, curve.p50_error, curve.p95_error):
            print(f" - budget={budget} p50={p50:.6g} p95={p95:.6g}")
        return
    elif args.command == "pseudo-fit":
        result = run_jupedsim_pseudo_fit(device=args.device, seed=args.seed, budget=args.budget, steps=args.steps)
        print("PM-033 pseudo fit:")
        print(f"seed={result.seed} budget={result.budget_steps} baseline={result.baseline_loss:.6g} fitted={result.calibrated_loss:.6g}")
        print(f"model_gap={result.model_gap:.6g} macro_gap={result.macro_gap:.6g}")
        return
    elif args.command == "real-data":
        results = run_real_data_like_calibration(
            device=args.device,
            steps=args.steps,
            seed=args.seed,
            budgets=args.budgets,
            dataset_path=args.dataset,
        )
        for item in results:
            print(
                f"seed={item.seed} budget={item.budget_steps} notes={item.notes} "
                f"train={item.train_loss:.6g}/{item.train_steps} holdout={item.holdout_loss:.6g}/{item.holdout_steps} "
                f"ratio={item.holdout_ratio_vs_train:.3g} macro_gap={abs(item.holdout_macro_loss-item.train_macro_loss):.3g} "
                f"dataset={item.dataset}"
            )
        return
    elif args.command == "calibration":
        curve = run_synthetic_four_parameter_recovery(
            device=args.device,
            budgets=[args.budget],
            seeds=args.seeds,
            methods=[args.method],
        )
        print("PM-033 calibration:")
        print(f"budgets={curve.budgets}")
        if args.method == "black-box":
            print(f"black_box_p50={curve.black_box_p50_error}")
            print(f"black_box_p95={curve.black_box_p95_error}")
        else:
            print(f"p50={curve.p50_error}")
            print(f"p95={curve.p95_error}")
        print(f"method={args.method}")
        return
    else:
        return
    print(f"{verdict}\nJSON: {json_path}\nReport: {markdown_path}")


def run_evidence() -> None:
    return main()
