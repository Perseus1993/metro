"""PM-033 calibration scaffolding for gradient-first recovery and baselines.

The module is intentionally self-contained to `experiments/torch_movement_p1`.
It does not touch `metro_station` runtime behavior.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import json
import math

import torch
from torch.nn import functional as functional

from .contracts import Bounds, KernelConfig, KernelParameters, PopulationState
from .geometry import (
    build_demo_station_polygon,
    build_polygon_walls,
    filter_points_in_polygon,
)
from .kernel import advance
from .state import SlotPopulation


@dataclass(frozen=True)
class CalibrationResult:
    method: str
    seed: int
    budget_steps: int
    loss: float
    relative_error: float
    recovered_parameters: dict[str, float]
    terms: dict[str, float]
    passed: bool
    iterations: int


@dataclass(frozen=True)
class GradientCompare:
    autograd: float
    finite_difference: float
    relative_error: float
    recovered: float
    passed: bool


@dataclass(frozen=True)
class MultiSeedBudgetCurve:
    budgets: list[int]
    p50_error: list[float]
    p95_error: list[float]
    black_box_p50_error: list[float]
    black_box_p95_error: list[float]
    best_recovered: list[tuple[int, list[float], float]]
    black_box_best: list[tuple[int, list[float], float]]
    autograd_to_black_box_ratio: list[float]


@dataclass(frozen=True)
class PseudoObservationResult:
    method: str
    seed: int
    budget_steps: int
    baseline_loss: float
    calibrated_loss: float
    model_gap: float
    macro_gap: float
    passed: bool


@dataclass(frozen=True)
class RealDataResult:
    dataset: str
    budget_steps: int
    seed: int
    train_loss: float
    holdout_loss: float
    train_steps: int
    holdout_steps: int
    train_macro_loss: float
    holdout_macro_loss: float
    relative_parameter_error: float
    holdout_ratio_vs_train: float
    passed: bool
    notes: str


@dataclass(frozen=True)
class LossWeights:
    trajectory_mse: float = 1.0
    checkpoint_position_mse: float = 0.25
    checkpoint_velocity_mse: float = 0.15
    density_proxy_mse: float = 0.10
    section_flow_mse: float = 0.05

    def clamp(self) -> "LossWeights":
        return LossWeights(
            trajectory_mse=max(0.0, float(self.trajectory_mse)),
            checkpoint_position_mse=max(0.0, float(self.checkpoint_position_mse)),
            checkpoint_velocity_mse=max(0.0, float(self.checkpoint_velocity_mse)),
            density_proxy_mse=max(0.0, float(self.density_proxy_mse)),
            section_flow_mse=max(0.0, float(self.section_flow_mse)),
        )


@dataclass(frozen=True)
class LossProfile:
    trajectory_mse: torch.Tensor
    checkpoint_position_mse: torch.Tensor
    checkpoint_velocity_mse: torch.Tensor
    density_proxy_mse: torch.Tensor
    section_flow_mse: torch.Tensor

    def total(self, weights: LossWeights) -> torch.Tensor:
        w = weights.clamp()
        return (
            w.trajectory_mse * self.trajectory_mse
            + w.checkpoint_position_mse * self.checkpoint_position_mse
            + w.checkpoint_velocity_mse * self.checkpoint_velocity_mse
            + w.density_proxy_mse * self.density_proxy_mse
            + w.section_flow_mse * self.section_flow_mse
        )


DEFAULT_LOSS_WEIGHTS = LossWeights()

SUPPORTED_OPTIMIZERS = {
    "adam": "adam",
    "l-bfgs": "l-bfgs",
    "cma-es": "cma-es",
    "cma": "cma-es",
    "black-box": "black-box",
    "bayes": "bayes",
    "bayesian": "bayes",
    "auto": "auto",
}


def run_autograd_gradient_check(
    device: torch.device | str,
    seed: int = 7,
    *,
    steps: int = 56,
    parameter_base: float = 0.50,
    weights: LossWeights | None = None,
) -> GradientCompare:
    """Check gradient consistency under the P1 contact solver."""
    state, walls, config, bounds = _build_single_agent_scene(device, world="rectangle")
    weights = _normalize_weights(weights)
    torch.manual_seed(seed)
    reference = _roll_positions(
        state,
        walls,
        config,
        bounds,
        KernelParameters(relaxation_time_seconds=0.38),
        steps=steps,
    ).detach()
    candidate = torch.tensor(parameter_base, device=device, requires_grad=True)
    loss, _ = _trajectory_loss(
        state,
        walls,
        config,
        bounds,
        reference,
        KernelParameters(relaxation_time_seconds=candidate),
        weights=weights,
    )
    autograd_value = float(torch.autograd.grad(loss, candidate, retain_graph=True)[0].item())
    finite = _finite_difference(
        state,
        walls,
        config,
        bounds,
        reference,
        centre=parameter_base,
        steps=steps,
    )
    relative = abs(autograd_value - finite) / max(abs(finite), 1e-8)
    recovered = _fit_relaxation_with_adam(
        state,
        walls,
        config,
        bounds,
        reference,
        seed=seed,
    )
    return GradientCompare(
        autograd=autograd_value,
        finite_difference=finite,
        relative_error=relative,
        recovered=recovered,
        passed=(relative < 0.06 and abs(recovered - 0.38) < 0.08),
    )


def run_synthetic_four_parameter_recovery(
    *,
    device: torch.device | str,
    seeds: list[int] | None = None,
    budgets: list[int] | None = None,
    max_steps: int = 64,
    methods: list[str] | None = None,
    weights: LossWeights | None = None,
) -> MultiSeedBudgetCurve:
    """4-parameter synthetic recovery with autograd vs random black-box baseline.

    Returns per-budget p50/p95 curves of relative parameter error.
    """
    if seeds is None:
        seeds = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41]
    if budgets is None:
        budgets = [20, 40, 80, 160]
    if methods is None:
        methods = ["adam", "black-box"]
    else:
        methods = [SUPPORTED_OPTIMIZERS.get(method, method) for method in methods]
    methods = list(dict.fromkeys(methods))
    weights = _normalize_weights(weights)

    true_params = KernelParameters(
        agent_repulsion_strength=2.2,
        wall_repulsion_strength=3.2,
        relaxation_time_seconds=0.41,
        agent_repulsion_range_m=0.50,
        desired_speed_scale=1.05,
    )

    state, walls, config, bounds = _build_poly_world(device)
    target = _roll_positions(
        state=state,
        walls=walls,
        config=config,
        bounds=bounds,
        parameters=true_params,
        steps=max_steps,
    ).detach()

    autograd_by_budget: dict[int, list[float]] = {budget: [] for budget in budgets}
    black_box_by_budget: dict[int, list[float]] = {budget: [] for budget in budgets}
    autograd_best: dict[int, tuple[tuple[float, float, float, float], float]] = {
        budget: (tuple(), float("inf")) for budget in budgets
    }
    black_box_best: dict[int, tuple[tuple[float, float, float, float], float]] = {
        budget: (tuple(), float("inf")) for budget in budgets
    }

    requested_black_box = "black-box" in methods
    requested_autograd = any(method != "black-box" for method in methods)

    for budget in budgets:
        if budget < 1:
            raise ValueError("budget must be >= 1")
        for seed in seeds:
            for method in methods:
                result = run_parameter_recovery(
                    method=method,
                    state=state,
                    walls=walls,
                    config=config,
                    bounds=bounds,
                    target_positions=target,
                    true_params=true_params,
                    budget=budget,
                    seed=seed,
                    weights=weights,
                )
                if SUPPORTED_OPTIMIZERS.get(method, method) == "black-box":
                    black_box_by_budget[budget].append(result.relative_error)
                    if result.relative_error < black_box_best[budget][1]:
                        black_box_best[budget] = (
                            tuple(result.recovered_parameters[k] for k in _ordered_keys()),
                            result.relative_error,
                        )
                else:
                    autograd_by_budget[budget].append(result.relative_error)
                    if result.relative_error < autograd_best[budget][1]:
                        autograd_best[budget] = (
                            tuple(result.recovered_parameters[k] for k in _ordered_keys()),
                            result.relative_error,
                        )

    p50: list[float] = []
    p95: list[float] = []
    bb_p50: list[float] = []
    bb_p95: list[float] = []
    best: list[tuple[int, list[float], float]] = []
    bb_best: list[tuple[int, list[float], float]] = []
    ratios: list[float] = []

    for budget in budgets:
        auto_errors = sorted(autograd_by_budget[budget])
        black_errors = sorted(black_box_by_budget[budget])
        best_vals = autograd_best[budget]
        black_vals = black_box_best[budget]

        if not auto_errors and not black_errors:
            p50.append(float("inf"))
            p95.append(float("inf"))
            bb_p50.append(float("inf"))
            bb_p95.append(float("inf"))
            ratios.append(float("inf"))
            best.append((budget, [], float("inf")))
            bb_best.append((budget, [], float("inf")))
            continue

        auto_q50 = float("inf")
        auto_q95 = float("inf")
        if auto_errors:
            auto_q50 = float(torch.quantile(torch.tensor(auto_errors), 0.50).item())
            auto_q95 = float(torch.quantile(torch.tensor(auto_errors), 0.95).item())
            best.append((budget, list(best_vals[0]), best_vals[1]))
        elif requested_autograd:
            best.append((budget, list(best_vals[0]), best_vals[1]))

        black_q50 = float("inf")
        black_q95 = float("inf")
        if black_errors:
            black_q50 = float(torch.quantile(torch.tensor(black_errors), 0.50).item())
            black_q95 = float(torch.quantile(torch.tensor(black_errors), 0.95).item())
            bb_best.append((budget, list(black_vals[0]), black_vals[1]))
        elif requested_black_box:
            bb_best.append((budget, list(black_vals[0]), black_vals[1]))

        p50.append(auto_q50)
        p95.append(auto_q95)
        bb_p50.append(black_q50)
        bb_p95.append(black_q95)
        if auto_errors and black_errors:
            ratios.append(float(auto_q50 / black_q50))
        else:
            ratios.append(float("inf"))

    return MultiSeedBudgetCurve(
        budgets=budgets,
        p50_error=p50,
        p95_error=p95,
        black_box_p50_error=bb_p50,
        black_box_p95_error=bb_p95,
        best_recovered=best,
        black_box_best=bb_best,
        autograd_to_black_box_ratio=ratios,
    )


def run_parameter_recovery(
    *,
    method: str,
    state: PopulationState,
    walls,
    config: KernelConfig,
    bounds: Bounds,
    target_positions: torch.Tensor,
    true_params: KernelParameters,
    budget: int,
    seed: int,
    weights: LossWeights | None = None,
) -> CalibrationResult:
    """Recover four tunable parameters under one budget/seed/method condition."""
    if budget < 1:
        raise ValueError("budget must be >= 1")
    canonical = SUPPORTED_OPTIMIZERS.get(method, method)
    weights = _normalize_weights(weights)

    if canonical == "l-bfgs":
        return _recover_four_parameters_with_grad(
            state=state,
            walls=walls,
            config=config,
            bounds=bounds,
            target_positions=target_positions,
            true_params=true_params,
            budget=budget,
            seed=seed,
            use_lbfgs=True,
            method="autograd-lbfgs",
            weights=weights,
        )
    if canonical == "black-box":
        return _recover_four_parameters_black_box(
            state=state,
            walls=walls,
            config=config,
            bounds=bounds,
            target_positions=target_positions,
            true_params=true_params,
            budget=budget,
            seed=seed,
            weights=weights,
        )
    if canonical in {"cma-es", "cma"}:
        return _recover_four_parameters_cma_es(
            state=state,
            walls=walls,
            config=config,
            bounds=bounds,
            target_positions=target_positions,
            true_params=true_params,
            budget=budget,
            seed=seed,
            weights=weights,
        )
    if canonical in {"bayes", "bayesian"}:
        return _recover_four_parameters_bayesian(
            state=state,
            walls=walls,
            config=config,
            bounds=bounds,
            target_positions=target_positions,
            true_params=true_params,
            budget=budget,
            seed=seed,
            weights=weights,
        )

    return _recover_four_parameters_with_grad(
        state=state,
        walls=walls,
        config=config,
        bounds=bounds,
        target_positions=target_positions,
        true_params=true_params,
        budget=budget,
        seed=seed,
        use_lbfgs=False,
        method="autograd-adam",
        weights=weights,
    )


def run_jupedsim_pseudo_fit(
    *,
    device: torch.device | str,
    seed: int = 17,
    steps: int = 120,
    budget: int = 120,
    weights: LossWeights | None = None,
    seed_target: float = 2.2,
) -> PseudoObservationResult:
    """Use synthetic thin-slice trajectories as JuPedSim-like pseudo observations.

    This keeps experiments closed to the P1 folder and avoids touching JuPedSim
    model internals. The function explicitly reports this as model-class gap.
    """
    weights = _normalize_weights(weights)
    state, walls, config, bounds = _build_poly_world(device)
    state = _ensure_seeded_population(state, seed, target_scale=1.0)

    target = _roll_positions(
        state,
        walls,
        config,
        bounds,
        KernelParameters(agent_repulsion_strength=seed_target),
        steps=steps,
    ).detach()

    baseline_loss, baseline_terms = _trajectory_loss(
        state,
        walls,
        config,
        bounds,
        target,
        KernelParameters(),
        weights=weights,
    )
    truth = KernelParameters(
        agent_repulsion_strength=seed_target,
        wall_repulsion_strength=3.2,
        relaxation_time_seconds=0.41,
        agent_repulsion_range_m=0.50,
        desired_speed_scale=1.05,
    )

    result = _recover_four_parameters_with_grad(
        state=state,
        walls=walls,
        config=config,
        bounds=bounds,
        target_positions=target,
        true_params=truth,
        budget=budget,
        seed=seed,
        use_lbfgs=False,
        method="autograd-adam",
        weights=weights,
    )
    calibrated_loss = result.loss
    gap = abs(result.relative_error)

    baseline_macro = _macro_proxy(
        state,
        walls,
        config,
        bounds,
        target,
        KernelParameters(),
        steps=steps,
    )
    fitted_params = KernelParameters(
        agent_repulsion_strength=result.recovered_parameters["agent_repulsion_strength"],
        wall_repulsion_strength=result.recovered_parameters["wall_repulsion_strength"],
        relaxation_time_seconds=result.recovered_parameters["relaxation_time_seconds"],
        agent_repulsion_range_m=result.recovered_parameters["agent_repulsion_range_m"],
        desired_speed_scale=result.recovered_parameters["desired_speed_scale"],
    )
    calibrated_macro = _macro_proxy(
        state,
        walls,
        config,
        bounds,
        target,
        fitted_params,
        steps=steps,
    )
    macro_gap = float(abs(calibrated_macro - baseline_macro))

    return PseudoObservationResult(
        method="jupedsim-pseudo",
        seed=seed,
        budget_steps=budget,
        baseline_loss=float(baseline_loss.item()),
        calibrated_loss=calibrated_loss,
        model_gap=float(gap),
        macro_gap=macro_gap,
        passed=bool(calibrated_loss <= baseline_loss),
    )


def run_real_data_like_calibration(
    *,
    device: torch.device | str,
    seed: int = 17,
    steps: int = 120,
    budgets: list[int] | None = None,
    weights: LossWeights | None = None,
    dataset_path: str | None = None,
    train_ratio: float = 0.7,
) -> list[RealDataResult]:
    """Run train/holdout protocol for real-data-like calibration.

    If `dataset_path` exists and is loadable, fit to it; otherwise run a
    deterministic synthetic stand-in and report fallback reasons.
    """
    if budgets is None:
        budgets = [60, 120, 160]
    weights = _normalize_weights(weights)
    if any(budget < 1 for budget in budgets):
        raise ValueError("all budgets must be >= 1")
    if not 0.0 < train_ratio <= 1.0:
        raise ValueError("train_ratio must be in (0, 1]")

    state, walls, config, bounds = _build_poly_world(device)
    true_params = KernelParameters(
        agent_repulsion_strength=2.1,
        wall_repulsion_strength=3.0,
        relaxation_time_seconds=0.44,
        agent_repulsion_range_m=0.52,
        desired_speed_scale=1.02,
    )

    observations, load_info = _load_real_data_or_synthetic(
        state=state,
        walls=walls,
        config=config,
        bounds=bounds,
        steps=steps,
        dataset_path=dataset_path,
        seed=seed,
        params=true_params,
    )

    observations = _align_observations_to_state(
        observations=observations,
        state=state,
        target_steps=steps,
    )
    if observations.dim() != 3 or observations.shape[-1] != 2:
        raise ValueError("real-data tensor must be [steps, slots, 2]")

    split_at = int(observations.shape[0] * train_ratio)
    split_at = max(1, min(split_at, observations.shape[0] - 1))
    train_target = observations[:split_at]
    holdout_target = observations[split_at:]
    if holdout_target.shape[0] == 0:
        holdout_target = train_target[:1]

    results: list[RealDataResult] = []
    for budget in budgets:
        torch.manual_seed(seed)
        fit = run_parameter_recovery(
            method="adam",
            state=state,
            walls=walls,
            config=config,
            bounds=bounds,
            target_positions=train_target,
            true_params=true_params,
            budget=budget,
            seed=seed,
            weights=weights,
        )
        holdout_recovered = _trajectory_loss(
            state,
            walls,
            config,
            bounds,
            holdout_target,
            _build_kernel_from_dict(fit.recovered_parameters),
            weights=weights,
        )[0]
        holdout_ratio = float(
            holdout_recovered.item() / max(1e-8, float(fit.loss))
        )
        train_macro = _macro_proxy(
            state,
            walls,
            config,
            bounds,
            train_target,
            _build_kernel_from_dict(fit.recovered_parameters),
            steps=max(int(train_target.shape[0]), 1),
        )
        holdout_macro = _macro_proxy(
            state,
            walls,
            config,
            bounds,
            holdout_target,
            _build_kernel_from_dict(fit.recovered_parameters),
            steps=max(int(holdout_target.shape[0]), 1),
        )
        results.append(
            RealDataResult(
                dataset=load_info["path"],
                budget_steps=budget,
                seed=seed,
                train_loss=fit.loss,
                holdout_loss=float(holdout_recovered.item()),
                train_steps=int(train_target.shape[0]),
                holdout_steps=int(holdout_target.shape[0]),
                train_macro_loss=float(train_macro),
                holdout_macro_loss=float(holdout_macro),
                relative_parameter_error=fit.relative_error,
                holdout_ratio_vs_train=holdout_ratio,
                passed=fit.loss > 0.0 and float(holdout_recovered.item()) <= float(fit.loss),
                notes=_format_dataset_notes(dataset_path, load_info),
            )
        )
    return results

def _recover_four_parameters_with_grad(
    *,
    state: PopulationState,
    walls,
    config: "KernelConfig",
    bounds: Bounds,
    target_positions: torch.Tensor,
    true_params: KernelParameters,
    budget: int,
    seed: int,
    use_lbfgs: bool,
    method: str,
    weights: LossWeights,
) -> CalibrationResult:
    generator = torch.Generator(device=state.device).manual_seed(seed)
    parameters = torch.nn.Parameter(
        torch.randn(4, generator=generator, device=state.device, dtype=state.dtype) * 0.4
    )
    if use_lbfgs:
        optimizer = torch.optim.LBFGS(
            [parameters],
            lr=0.3,
            max_iter=budget,
            tolerance_grad=1e-7,
            tolerance_change=1e-9,
        )
    else:
        optimizer = torch.optim.Adam([parameters], lr=0.06)

    best_loss = float("inf")
    best_params: tuple[float, float, float, float] | None = None
    for _ in range(max(1, int(budget))):
        if use_lbfgs:
            closure_loss: torch.Tensor | None = None

            def closure():
                nonlocal closure_loss
                optimizer.zero_grad(set_to_none=True)
                closure_loss, _ = _trajectory_loss(
                    state,
                    walls,
                    config,
                    bounds,
                    target_positions,
                    _decode_parameter_vector(parameters),
                    weights=weights,
                )
                if not torch.isfinite(closure_loss):
                    closure_loss = torch.tensor(0.0, device=state.device, dtype=state.dtype)
                    return closure_loss
                closure_loss.backward()
                return closure_loss

            optimizer.step(closure)
            loss_val = float(closure_loss.item()) if closure_loss is not None and torch.isfinite(closure_loss) else float("inf")
            if loss_val < best_loss:
                best_loss = loss_val
                best_params = _to_scalar_tuple(_decode_parameter_vector(parameters))
            terms = _trajectory_loss(
                state,
                walls,
                config,
                bounds,
                target_positions,
                _decode_parameter_vector(parameters),
                weights=weights,
            )[1]
            if not math.isfinite(loss_val):
                break
        else:
            loss, terms = _trajectory_loss(
                state,
                walls,
                config,
                bounds,
                target_positions,
                _decode_parameter_vector(parameters),
                weights=weights,
            )
            loss_val = float(loss.item())
            if not math.isfinite(loss_val):
                break
            if loss_val < best_loss:
                best_loss = loss_val
                best_params = _to_scalar_tuple(_decode_parameter_vector(parameters))
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()

        if use_lbfgs and not math.isfinite(loss_val):
            break

    if best_params is None:
        best_params = _to_scalar_tuple(_decode_parameter_vector(parameters))

    recovered = {
        "agent_repulsion_strength": float(best_params[0]),
        "wall_repulsion_strength": float(best_params[1]),
        "relaxation_time_seconds": float(best_params[2]),
        "agent_repulsion_range_m": float(best_params[3]),
        "desired_speed_scale": 1.0,
    }
    error = _relative_parameter_error(recovered, true_params)
    fit_loss, fit_terms = _trajectory_loss(
        state,
        walls,
        config,
        bounds,
        target_positions,
        _build_kernel_from_dict(recovered),
        weights=weights,
    )
    return CalibrationResult(
        method=method,
        seed=seed,
        budget_steps=budget,
        loss=float(fit_loss.item()),
        relative_error=error,
        recovered_parameters=recovered,
        terms={name: float(value) for name, value in fit_terms.__dict__.items()},
        passed=best_loss < float("inf"),
        iterations=budget,
    )


def _recover_four_parameters_black_box(
    *,
    state: PopulationState,
    walls,
    config: "KernelConfig",
    bounds: Bounds,
    target_positions: torch.Tensor,
    true_params: KernelParameters,
    budget: int,
    seed: int,
    weights: LossWeights,
) -> CalibrationResult:
    rng = torch.Generator(device=state.device).manual_seed(seed)
    best_loss = float("inf")
    best_params: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    for _ in range(max(1, int(budget))):
        raw = torch.randn(4, generator=rng, device=state.device, dtype=state.dtype)
        decoded = _decode_parameter_vector(raw)
        loss, _ = _trajectory_loss(
            state,
            walls,
            config,
            bounds,
            target_positions,
            decoded,
            weights=weights,
        )
        if torch.isfinite(loss) and float(loss.item()) < best_loss:
            best_loss = float(loss.item())
            best_params = _to_scalar_tuple(decoded)

    recovered = {
        "agent_repulsion_strength": float(best_params[0]),
        "wall_repulsion_strength": float(best_params[1]),
        "relaxation_time_seconds": float(best_params[2]),
        "agent_repulsion_range_m": float(best_params[3]),
        "desired_speed_scale": 1.0,
    }
    error = _relative_parameter_error(recovered, true_params)
    return CalibrationResult(
        method="blackbox-random",
        seed=seed,
        budget_steps=budget,
        loss=best_loss,
        relative_error=error,
        recovered_parameters=recovered,
        terms={
            "trajectory_mse": best_loss,
            "checkpoint_position_mse": best_loss,
            "checkpoint_velocity_mse": 0.0,
            "density_proxy_mse": 0.0,
            "section_flow_mse": 0.0,
        },
        passed=best_loss < float("inf"),
        iterations=budget,
    )


def _recover_four_parameters_cma_es(
    *,
    state: PopulationState,
    walls,
    config: "KernelConfig",
    bounds: Bounds,
    target_positions: torch.Tensor,
    true_params: KernelParameters,
    budget: int,
    seed: int,
    weights: LossWeights,
) -> CalibrationResult:
    rng = torch.Generator(device=state.device).manual_seed(seed + 1009)
    base = torch.zeros(4, device=state.device, dtype=state.dtype)
    sigma = 0.75
    best_loss = float("inf")
    best_params = base.clone()
    pop_size = 6

    for _ in range(max(1, int(budget))):
        sampled = torch.stack(
            [
                base + sigma * torch.randn(4, generator=rng, device=state.device, dtype=state.dtype)
                for _ in range(pop_size)
            ]
        )
        losses = []
        for candidate in sampled:
            decoded = _decode_parameter_vector(candidate)
            loss, _ = _trajectory_loss(
                state,
                walls,
                config,
                bounds,
                target_positions,
                decoded,
                weights=weights,
            )
            losses.append(float(loss.item()))
        if not losses:
            break
        losses_t = torch.tensor(losses, device=state.device)
        order = torch.argsort(losses_t)
        elites = sampled[order[: max(1, pop_size // 2)]]
        base = elites.mean(dim=0)
        sigma = max(0.1, sigma * 0.98)
        best_local_idx = int(order[0].item())
        if float(losses[best_local_idx]) < best_loss:
            best_loss = float(losses[best_local_idx])
            best_params = sampled[best_local_idx]

    decoded = _decode_parameter_vector(best_params)
    recovered = {
        "agent_repulsion_strength": float(decoded.agent_repulsion_strength),
        "wall_repulsion_strength": float(decoded.wall_repulsion_strength),
        "relaxation_time_seconds": float(decoded.relaxation_time_seconds),
        "agent_repulsion_range_m": float(decoded.agent_repulsion_range_m),
        "desired_speed_scale": 1.0,
    }
    error = _relative_parameter_error(recovered, true_params)
    _, terms = _trajectory_loss(state, walls, config, bounds, target_positions, decoded, weights=weights)
    return CalibrationResult(
        method="cma-es",
        seed=seed,
        budget_steps=budget,
        loss=best_loss,
        relative_error=error,
        recovered_parameters=recovered,
        terms={name: float(value) for name, value in terms.__dict__.items()},
        passed=best_loss < float("inf"),
        iterations=budget,
    )


def _recover_four_parameters_bayesian(
    *,
    state: PopulationState,
    walls,
    config: "KernelConfig",
    bounds: Bounds,
    target_positions: torch.Tensor,
    true_params: KernelParameters,
    budget: int,
    seed: int,
    weights: LossWeights,
) -> CalibrationResult:
    # Lightweight Bayesian-style surrogate-guided search: start wide, then shrink.
    rng = torch.Generator(device=state.device).manual_seed(seed + 2026)
    mean = torch.zeros(4, device=state.device, dtype=state.dtype)
    scale = torch.tensor([1.2, 1.2, 0.8, 1.0], device=state.device, dtype=state.dtype)
    best_loss = float("inf")
    best_params = mean.clone()

    for step in range(max(1, int(budget))):
        noise_scale = 1.0 - 0.55 * (step / max(1.0, budget - 1))
        local = mean + (scale * noise_scale) * torch.randn(1, 4, generator=rng, device=state.device, dtype=state.dtype)
        random_probe = torch.randn(3, 4, generator=rng, device=state.device, dtype=state.dtype) * scale
        candidates = torch.cat([local, random_probe], dim=0)
        losses = []
        for candidate in candidates:
            decoded = _decode_parameter_vector(candidate)
            loss, _ = _trajectory_loss(
                state,
                walls,
                config,
                bounds,
                target_positions,
                decoded,
                weights=weights,
            )
            losses.append(float(loss.item()))

        loss_t = torch.tensor(losses, device=state.device)
        best_idx = int(loss_t.argmin().item())
        best_candidate = candidates[best_idx]
        if float(loss_t[best_idx].item()) < best_loss:
            best_loss = float(loss_t[best_idx].item())
            best_params = best_candidate
            mean = 0.7 * mean + 0.3 * best_candidate
        else:
            mean = 0.95 * mean + 0.05 * best_candidate

    decoded = _decode_parameter_vector(best_params)
    recovered = {
        "agent_repulsion_strength": float(decoded.agent_repulsion_strength),
        "wall_repulsion_strength": float(decoded.wall_repulsion_strength),
        "relaxation_time_seconds": float(decoded.relaxation_time_seconds),
        "agent_repulsion_range_m": float(decoded.agent_repulsion_range_m),
        "desired_speed_scale": 1.0,
    }
    error = _relative_parameter_error(recovered, true_params)
    _, terms = _trajectory_loss(state, walls, config, bounds, target_positions, decoded, weights=weights)
    return CalibrationResult(
        method="bayes",
        seed=seed,
        budget_steps=budget,
        loss=best_loss,
        relative_error=error,
        recovered_parameters=recovered,
        terms={name: float(value) for name, value in terms.__dict__.items()},
        passed=best_loss < float("inf"),
        iterations=budget,
    )


def _build_kernel_from_dict(parameters: dict[str, float | int]) -> KernelParameters:
    return KernelParameters(
        agent_repulsion_strength=float(parameters["agent_repulsion_strength"]),
        wall_repulsion_strength=float(parameters["wall_repulsion_strength"]),
        relaxation_time_seconds=float(parameters["relaxation_time_seconds"]),
        agent_repulsion_range_m=float(parameters["agent_repulsion_range_m"]),
        desired_speed_scale=float(parameters.get("desired_speed_scale", 1.0)),
    )


def _trajectory_loss(
    state: PopulationState,
    walls,
    config: "KernelConfig",
    bounds: Bounds,
    target_positions: torch.Tensor,
    parameters: KernelParameters,
    *,
    weights: LossWeights,
) -> tuple[torch.Tensor, LossProfile]:
    predicted = _roll_positions(
        state,
        walls,
        config,
        bounds,
        parameters,
        steps=target_positions.shape[0],
    )
    terms = _compute_loss_terms(predicted, target_positions, bounds, config)
    loss = terms.total(weights)
    return loss, terms


def _compute_loss_terms(
    predicted: torch.Tensor,
    target: torch.Tensor,
    bounds: Bounds,
    config: KernelConfig,
) -> LossProfile:
    predicted, target = _normalize_trajectory_for_loss(predicted, target)
    if predicted.shape != target.shape:
        raise ValueError("trajectory shape mismatch")
    if predicted.dim() != 3 or predicted.size(-1) != 2:
        raise ValueError("trajectory must be [time, slot, 2]")

    trajectory = torch.mean((predicted - target) ** 2)
    total_steps = predicted.shape[0]
    if total_steps < 2:
        velocity = torch.tensor(0.0, device=predicted.device, dtype=predicted.dtype)
    else:
        pred_v = (predicted[1:] - predicted[:-1]) / max(config.dt_seconds, 1e-6)
        target_v = (target[1:] - target[:-1]) / max(config.dt_seconds, 1e-6)
        velocity = torch.mean((pred_v - target_v) ** 2)

    idx = torch.linspace(0, float(total_steps - 1), steps=6, device=predicted.device)
    idx = idx.to(torch.long)
    checkpoints = torch.index_select(predicted, 0, torch.unique(idx)).to(predicted.dtype)
    target_cp = torch.index_select(target, 0, torch.unique(idx)).to(target.dtype)
    checkpoint_position = torch.mean((checkpoints - target_cp) ** 2)

    density = _density_proxy(predicted, bounds).mean()
    target_density = _density_proxy(target, bounds).mean()
    density_proxy_loss = (density - target_density) ** 2

    flow_pred = _section_flow_profile(predicted, bounds)
    flow_target = _section_flow_profile(target, bounds)
    section_flow = torch.mean((flow_pred - flow_target) ** 2)

    return LossProfile(
        trajectory_mse=trajectory,
        checkpoint_position_mse=checkpoint_position,
        checkpoint_velocity_mse=velocity,
        density_proxy_mse=density_proxy_loss,
        section_flow_mse=section_flow,
    )


def _normalize_trajectory_for_loss(
    predicted: torch.Tensor, target: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    """Normalize trajectory tensors for loss terms while keeping internal shapes flexible."""
    predicted = _squeeze_singleton_batch(predicted)
    target = _squeeze_singleton_batch(target)

    if predicted.shape == target.shape:
        return predicted, target

    if predicted.dim() == 4:
        predicted = predicted.reshape(predicted.shape[0], -1, predicted.shape[-1])
    if target.dim() == 4:
        target = target.reshape(target.shape[0], -1, target.shape[-1])

    if (
        predicted.dim() == 3
        and target.dim() == 3
        and predicted.shape[-1] == 2
        and target.shape[-1] == 2
        and predicted.shape[0] == target.shape[0]
    ):
        if target.shape[1] != predicted.shape[1]:
            target = _align_slots(target, predicted.shape[1])

    return predicted, target


def _squeeze_singleton_batch(trajectory: torch.Tensor) -> torch.Tensor:
    """Collapse singleton batch dimension for compatibility with legacy [T,S,2] losses."""
    if trajectory.dim() == 4 and trajectory.shape[1] == 1:
        return trajectory[:, 0]
    return trajectory


def _align_observations_to_state(
    observations: torch.Tensor,
    state: PopulationState,
    target_steps: int | None = None,
) -> torch.Tensor:
    """Align loaded observations to simulation slot count and target step count."""
    aligned = _squeeze_singleton_batch(observations)
    if aligned.dim() != 3 or aligned.shape[-1] != 2:
        raise ValueError("observations must be [steps, slots, 2]")
    if target_steps is not None:
        if aligned.shape[0] > target_steps:
            aligned = aligned[:target_steps]
        elif aligned.shape[0] < target_steps:
            aligned = _trim_or_pad_steps(aligned, target_steps=target_steps)

    target_slots = int(state.position.shape[-2])
    if aligned.shape[1] != target_slots:
        aligned = _align_slots(aligned, target_slots)
    return aligned


def _align_slots(trajectory: torch.Tensor, target_slots: int) -> torch.Tensor:
    """Align trajectories to target slot count by truncation or deterministic repeat."""
    if trajectory.dim() != 3 or trajectory.shape[-1] != 2:
        raise ValueError("trajectory must be [steps, slots, 2]")
    if target_slots < 1:
        raise ValueError("target_slots must be >= 1")
    current_slots = int(trajectory.shape[1])
    if current_slots == target_slots:
        return trajectory
    if current_slots > target_slots:
        return trajectory[:, :target_slots, :]
    repeats = (target_slots + current_slots - 1) // current_slots
    repeated = trajectory.repeat(1, repeats, 1)
    return repeated[:, :target_slots, :]


def _density_proxy(
    trajectory: torch.Tensor,
    bounds: Bounds,
    *,
    bins_x: int = 14,
    bins_y: int = 8,
    sigma: float = 0.60,
) -> torch.Tensor:
    # Smooth occupancy proxy; differentiable with respect to trajectory.
    lower_x, lower_y = bounds.lower
    upper_x, upper_y = bounds.upper
    xs = trajectory[..., 0]
    ys = trajectory[..., 1]
    x_edges = torch.linspace(lower_x, upper_x, bins_x + 1, device=trajectory.device)
    y_edges = torch.linspace(lower_y, upper_y, bins_y + 1, device=trajectory.device)
    x_centers = (x_edges[:-1] + x_edges[1:]) / 2.0
    y_centers = (y_edges[:-1] + y_edges[1:]) / 2.0
    x_diff = xs[:, :, None, None] - x_centers.view(1, 1, -1, 1)
    y_diff = ys[:, :, None, None] - y_centers.view(1, 1, 1, -1)
    kernel = torch.exp(-0.5 * (x_diff**2 + y_diff**2) / (sigma**2 + 1e-12))
    return kernel.mean(dim=1)

def _section_flow_profile(trajectory: torch.Tensor, bounds: Bounds) -> torch.Tensor:
    lower_x, _ = bounds.lower
    upper_x, _ = bounds.upper
    thresholds = torch.tensor(
        [lower_x + 0.35 * (upper_x - lower_x), lower_x + 0.65 * (upper_x - lower_x)],
        device=trajectory.device,
        dtype=trajectory.dtype,
    )
    x = trajectory[:, :, 0]
    if x.shape[0] < 2:
        return torch.zeros((len(thresholds),), device=trajectory.device, dtype=trajectory.dtype)
    x_prev = x[:-1]
    x_next = x[1:]
    if x_prev.numel() == 0 or x_next.numel() == 0:
        return torch.zeros((len(thresholds),), device=trajectory.device, dtype=trajectory.dtype)
    flows = []
    sigma = torch.tensor(0.15, device=trajectory.device, dtype=trajectory.dtype)
    for thr in thresholds:
        crosses = torch.sigmoid((x_next - thr) / sigma) - torch.sigmoid((x_prev - thr) / sigma)
        flows.append(crosses.abs().mean(dim=1))
    return torch.stack(flows, dim=0)


def _ordered_keys() -> tuple[str, ...]:
    return (
        "agent_repulsion_strength",
        "wall_repulsion_strength",
        "relaxation_time_seconds",
        "agent_repulsion_range_m",
    )


def _to_scalar_tuple(parameters: KernelParameters) -> tuple[float, float, float, float]:
    return (
        float(parameters.agent_repulsion_strength.detach().item())
        if hasattr(parameters.agent_repulsion_strength, "detach")
        else float(parameters.agent_repulsion_strength),
        float(parameters.wall_repulsion_strength.detach().item())
        if hasattr(parameters.wall_repulsion_strength, "detach")
        else float(parameters.wall_repulsion_strength),
        float(parameters.relaxation_time_seconds.detach().item())
        if hasattr(parameters.relaxation_time_seconds, "detach")
        else float(parameters.relaxation_time_seconds),
        float(parameters.agent_repulsion_range_m.detach().item())
        if hasattr(parameters.agent_repulsion_range_m, "detach")
        else float(parameters.agent_repulsion_range_m),
    )


def _relative_parameter_error(recovered: dict[str, float], truth: KernelParameters) -> float:
    truth_values = {
        "agent_repulsion_strength": float(truth.agent_repulsion_strength),
        "wall_repulsion_strength": float(truth.wall_repulsion_strength),
        "relaxation_time_seconds": float(truth.relaxation_time_seconds),
        "agent_repulsion_range_m": float(truth.agent_repulsion_range_m),
    }
    components = []
    for key in _ordered_keys():
        r = float(recovered[key])
        t = float(truth_values[key])
        denom = t if abs(t) > 1e-8 else 1.0
        components.append(abs(r - t) / denom)
    return float(torch.tensor(components, dtype=torch.float32).mean().item())


def _decode_parameter_vector(raw: torch.Tensor) -> KernelParameters:
    """Map unconstrained optimizer variables into physical ranges."""
    base = raw.to(dtype=torch.float32)
    return KernelParameters(
        agent_repulsion_strength=0.25 + functional.softplus(base[0]),
        wall_repulsion_strength=2.2 + functional.softplus(base[1]),
        relaxation_time_seconds=0.08 + functional.softplus(base[2]),
        agent_repulsion_range_m=0.28 + functional.softplus(base[3]),
        desired_speed_scale=1.0,
    )


def _macro_proxy(
    state: PopulationState,
    walls,
    config: KernelConfig,
    bounds: Bounds,
    target: torch.Tensor,
    parameters: KernelParameters,
    *,
    steps: int,
) -> float:
    predicted = _roll_positions(state, walls, config, bounds, parameters, steps=steps)
    final_gap = torch.linalg.vector_norm(predicted[-1] - target[-1], dim=-1).mean()
    return float(final_gap.item())


def _build_single_agent_scene(device: torch.device | str, world: str = "rectangle"):
    population = SlotPopulation(batch_size=1, capacity=1, device=device)
    population.spawn(1, position=(1.0, 5.0), target=(8.0, 5.0), desired_speed=1.1, radius=0.18)
    if world == "rectangle":
        from .geometry import rectangular_walls

        return (
            population.state,
            rectangular_walls(width=12.0, height=10.0, batch_size=1, device=device, dtype=torch.float32),
            KernelConfig(max_speed_mps=4.0, max_acceleration_mps2=30.0, enable_safety_projection=False),
            Bounds(lower=(0.0, 0.0), upper=(12.0, 10.0)),
        )
    raise ValueError(f"unknown world {world}")


def _build_poly_world(device: torch.device | str):
    population = SlotPopulation(batch_size=1, capacity=50, device=device)
    outer, holes, obstacles = build_demo_station_polygon()
    walls = build_polygon_walls(
        outer=outer,
        holes=holes,
        obstacles=obstacles,
        batch_size=1,
        device=device,
        dtype=torch.float32,
    )
    start_points = _sample_walkable_points(
        outer=outer,
        holes=holes,
        obstacles=obstacles,
        requested=50,
        seed=17,
        device=device,
    )
    for i, point in enumerate(start_points.tolist()):
        population.spawn(
            100 + i,
            position=(float(point[0]), float(point[1])),
            target=(13.0, 5.0),
            desired_speed=1.1,
        )
    bounds = Bounds(lower=(0.0, 0.0), upper=(14.0, 10.0))
    config = KernelConfig(max_speed_mps=1.6, enable_safety_projection=True, contact_iterations=10)
    return population.state, walls, config, bounds


def _roll_positions(
    state: PopulationState,
    walls,
    config: "KernelConfig",
    bounds: Bounds,
    parameters: KernelParameters,
    *,
    steps: int,
) -> torch.Tensor:
    positions = []
    cursor = state
    for _ in range(int(steps)):
        cursor = advance(
            cursor,
            walls,
            config,
            parameters=parameters,
            bounds=bounds,
            collect_diagnostics=False,
        ).state
        positions.append(cursor.position)
    return torch.stack(positions)


def _finite_difference(
    state: PopulationState,
    walls,
    config: "KernelConfig",
    bounds: Bounds,
    reference: torch.Tensor,
    centre: float,
    step: float = 1e-3,
    steps: int = 56,
) -> float:
    plus = _trajectory_loss(
        state,
        walls,
        config,
        bounds,
        reference,
        KernelParameters(relaxation_time_seconds=centre + step),
        weights=DEFAULT_LOSS_WEIGHTS,
    )[0]
    minus = _trajectory_loss(
        state,
        walls,
        config,
        bounds,
        reference,
        KernelParameters(relaxation_time_seconds=centre - step),
        weights=DEFAULT_LOSS_WEIGHTS,
    )[0]
    return float(((plus - minus) / (2.0 * step)).item())


def _fit_relaxation_with_adam(
    state: PopulationState,
    walls,
    config: "KernelConfig",
    bounds: Bounds,
    target: torch.Tensor,
    *,
    seed: int,
    steps: int = 140,
) -> float:
    torch.manual_seed(seed)
    raw = torch.tensor(0.20, device=state.device, requires_grad=True)
    optimizer = torch.optim.Adam([raw], lr=0.08)
    for _ in range(steps):
        relaxation = 0.10 + functional.softplus(raw)
        loss, _ = _trajectory_loss(
            state,
            walls,
            config,
            bounds,
            target,
            KernelParameters(relaxation_time_seconds=relaxation),
            weights=DEFAULT_LOSS_WEIGHTS,
        )
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    return float((0.10 + functional.softplus(raw)).detach().item())


def _ensure_seeded_population(state: PopulationState, seed: int, *, target_scale: float = 1.0):
    # Deterministic jitter keeps the train/holdout protocol reproducible.
    torch.manual_seed(seed)
    jitter = torch.randn_like(state.position) * 0.001 * target_scale
    return replace_state(state, state.position + jitter)


def _format_dataset_notes(dataset_path: str | None, load_info: dict[str, str]) -> str:
    source = load_info.get("source", "unknown")
    if source == "synthetic-fallback":
        reason = load_info.get("reason", "unavailable")
        return f"synthetic-fallback ({reason})"
    path = load_info.get("path", "")
    if dataset_path is None:
        return f"loaded:{path} ({source})"
    return f"from-dataset:{Path(dataset_path).name} ({source})"


def _load_real_data_or_synthetic(
    *,
    state: PopulationState,
    walls,
    config: KernelConfig,
    bounds: Bounds,
    steps: int,
    seed: int,
    params: KernelParameters,
    dataset_path: str | None,
) -> tuple[torch.Tensor, dict[str, str]]:
    if dataset_path:
        resolved = Path(dataset_path)
        if resolved.exists():
            try:
                trajectory, source = _load_real_data_dataset(
                    resolved,
                    state=state,
                    target_steps=steps,
                )
                if trajectory is not None:
                    return trajectory, {
                        "path": str(resolved),
                        "source": source,
                        "status": "loaded",
                        "reason": "ok",
                    }
            except Exception as exc:
                synthetic, fallback_info = _synthesize_real_data_proxy(
                    state=state,
                    walls=walls,
                    config=config,
                    bounds=bounds,
                    params=params,
                    seed=seed,
                    steps=steps,
                    fallback_reason=f"{type(exc).__name__}: {exc}",
                )
                fallback_info["path"] = str(resolved)
                fallback_info["status"] = "fallback"
                return synthetic, fallback_info

            fallback, fallback_info = _synthesize_real_data_proxy(
                state=state,
                walls=walls,
                config=config,
                bounds=bounds,
                params=params,
                seed=seed,
                steps=steps,
                fallback_reason="load-failed",
            )
            fallback_info["path"] = str(resolved)
            fallback_info["status"] = "fallback"
            fallback_info["source"] = "synthetic-fallback"
            return fallback, fallback_info

        synthetic, fallback_info = _synthesize_real_data_proxy(
            state=state,
            walls=walls,
            config=config,
            bounds=bounds,
            params=params,
            seed=seed,
            steps=steps,
            fallback_reason="file-not-found",
        )
        fallback_info["path"] = str(resolved)
        return synthetic, fallback_info

    synthetic, fallback_info = _synthesize_real_data_proxy(
        state=state,
        walls=walls,
        config=config,
        bounds=bounds,
        params=params,
        seed=seed,
        steps=steps,
        fallback_reason="synthetic-protocol-juelich-stub",
    )
    fallback_info["path"] = "synthetic-protocol-juelich-stub"
    return synthetic, fallback_info



def _load_real_data_dataset(
    source: Path,
    *,
    state: PopulationState,
    target_steps: int,
) -> tuple[torch.Tensor | None, str]:
    candidates = [source]
    if source.is_dir():
        candidates = sorted([p for p in source.iterdir() if p.is_file() and p.suffix.lower() in {".json", ".npz", ".npy", ".csv", ".txt"}])

    for path in candidates:
        suffix = path.suffix.lower()
        try:
            if suffix == ".json":
                trajectory, source_name = _load_json_trajectory(path, target_steps=target_steps, device=state.device)
                if trajectory is not None:
                    return _normalize_loaded_trajectory(trajectory), source_name
            if suffix in {".npy", ".npz"}:
                trajectory, source_name = _load_array_trajectory(path, target_steps=target_steps, device=state.device)
                if trajectory is not None:
                    return _normalize_loaded_trajectory(trajectory), source_name
            if suffix == ".csv":
                trajectory, source_name = _load_csv_trajectory(path, target_steps=target_steps, device=state.device)
                if trajectory is not None:
                    return _normalize_loaded_trajectory(trajectory), source_name
            if suffix == ".txt":
                trajectory, source_name = _load_txt_trajectory(path, target_steps=target_steps, device=state.device)
                if trajectory is not None:
                    return _normalize_loaded_trajectory(trajectory), source_name
        except Exception:
            continue
    return None, "not-loaded"


def _normalize_loaded_trajectory(trajectory: torch.Tensor) -> torch.Tensor:
    if trajectory.dim() != 3 or trajectory.shape[-1] != 2:
        raise ValueError("trajectory must be [steps, slots, 2]")
    if trajectory.shape[0] <= 2:
        raise ValueError("trajectory must contain at least 3 time steps")
    finite = torch.isfinite(trajectory).all(dim=-1)
    if bool((~finite).any()):
        trajectory = _fill_trajectory_nans(trajectory)
    if trajectory.shape[0] < 2:
        raise ValueError("trajectory duration is too short after loading")
    return trajectory


def _fill_trajectory_nans(trajectory: torch.Tensor) -> torch.Tensor:
    values = trajectory.clone()
    mask = torch.isfinite(values).all(dim=-1)
    for slot in range(values.shape[1]):
        valid = torch.nonzero(mask[:, slot], as_tuple=False).flatten()
        if len(valid) == 0:
            raise ValueError(f"slot {slot} has no finite observations")
        filled = values[:, slot].clone()
        if len(valid) < values.shape[0]:
            for coord in range(2):
                column = filled[:, coord]
                for idx in range(values.shape[0]):
                    if not mask[idx, slot]:
                        prior = torch.where(mask[:idx, slot])[0]
                        next_idx = torch.where(mask[idx + 1 :, slot])[0]
                        if len(prior) > 0:
                            filled[idx, coord] = column[prior[-1]]
                        elif len(next_idx) > 0:
                            filled[idx, coord] = column[idx + 1 + next_idx[0]]
                        else:
                            filled[idx, coord] = 0.0
            values[:, slot] = filled
    return values


def _load_json_trajectory(
    path: Path,
    *,
    target_steps: int,
    device: torch.device,
) -> tuple[torch.Tensor | None, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    options = ["trajectory", "trajectories", "positions", "positions_xy", "data"]
    for key in options:
        raw = payload.get(key) if isinstance(payload, dict) else None
        if raw is not None:
            raw_t = torch.as_tensor(raw, dtype=torch.float32, device=device)
            if raw_t.dim() == 3 and raw_t.shape[-1] == 2:
                return _trim_or_pad_steps(raw_t, target_steps=target_steps), f"json:{key}"
    if isinstance(payload, list):
        raw_t = torch.as_tensor(payload, dtype=torch.float32, device=device)
        if raw_t.dim() == 3 and raw_t.shape[-1] == 2:
            return _trim_or_pad_steps(raw_t, target_steps=target_steps), "json:list"
    if isinstance(payload, dict) and "agents" in payload:
        return _extract_agent_trajectory(payload["agents"], target_steps=target_steps, device=device), "json:agents"
    return None, "json:unsupported"


def _extract_agent_trajectory(payload, *, target_steps: int, device: torch.device) -> torch.Tensor | None:
    if not isinstance(payload, list):
        return None
    trajectories: list[list[list[float]]] = []
    for agent in payload:
        if not isinstance(agent, dict):
            return None
        if "trajectory" in agent:
            trajectories.append(agent["trajectory"])
    if not trajectories:
        return None
    try:
        max_len = max(len(item) for item in trajectories)
        slots = len(trajectories)
        out = torch.zeros((max(max_len, 1), slots, 2), dtype=torch.float32, device=device)
        for slot, path in enumerate(trajectories):
            traj = torch.as_tensor(path, dtype=torch.float32, device=device)
            if traj.dim() == 2 and traj.shape[1] >= 2:
                L = min(len(traj), max_len)
                out[:L, slot, :] = traj[:L, :2]
    except Exception:
        return None
    return _trim_or_pad_steps(out, target_steps=target_steps)


def _load_array_trajectory(
    path: Path,
    *,
    target_steps: int,
    device: torch.device,
) -> tuple[torch.Tensor | None, str]:
    import numpy as np

    if path.suffix.lower() == ".npy":
        arr = np.load(path, allow_pickle=True)
        raw_t = torch.as_tensor(arr, dtype=torch.float32, device=device)
        if raw_t.dim() == 3 and raw_t.shape[-1] == 2:
            return _trim_or_pad_steps(raw_t, target_steps=target_steps), "npy:raw"
        return None, "npy:unsupported"
    arr = np.load(path, allow_pickle=True)
    if isinstance(arr, np.lib.npyio.NpzFile):
        for key in ("trajectory", "trajectories", "positions", "data"):
            if key in arr.files:
                raw = torch.as_tensor(arr[key], dtype=torch.float32, device=device)
                if raw.ndim == 3 and raw.shape[-1] == 2:
                    return _trim_or_pad_steps(raw, target_steps=target_steps), f"npz:{key}"
        for key in arr.files:
            raw = torch.as_tensor(arr[key], dtype=torch.float32, device=device)
            if raw.ndim == 3 and raw.shape[-1] == 2:
                return _trim_or_pad_steps(raw, target_steps=target_steps), f"npz:{key}"
    return None, "npz:unsupported"


def _load_csv_trajectory(
    path: Path,
    *,
    target_steps: int,
    device: torch.device,
) -> tuple[torch.Tensor | None, str]:
    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader]
    if not rows:
        return None, "csv:empty"

    first_row = rows[0]
    cols = {name.lower(): name for name in first_row.keys()}
    frame_col = _find_first(cols, ["frame", "step", "time", "t", "frame_id"])
    ped_col = _find_first(cols, ["id", "agent_id", "person_id", "ped_id", "entity_id"])
    x_col = _find_first(cols, ["x", "pos_x", "position_x", "px", "coords_x"])
    y_col = _find_first(cols, ["y", "pos_y", "position_y", "py", "coords_y"])
    if x_col is None or y_col is None:
        return None, "csv:missing-axis"

    if frame_col is None:
        for idx, row in enumerate(rows):
            row["__auto_frame__"] = str(idx)
        frame_col = "__auto_frame__"
        cols["__auto_frame__"] = "__auto_frame__"
    if ped_col is None:
        for row in rows:
            row["__auto_id__"] = "agent_0"
        ped_col = "__auto_id__"
        cols["__auto_id__"] = "__auto_id__"

    frame_values = []
    ped_values = []
    for row in rows:
        frame_values.append(int(float(row[frame_col])))
        ped_values.append(str(row[ped_col]))
    frame_ids = sorted({int(x) for x in frame_values})
    ped_ids = sorted({p for p in ped_values})

    slot_to_index = {pid: idx for idx, pid in enumerate(ped_ids)}
    frame_to_index = {frame: idx for idx, frame in enumerate(frame_ids)}
    out = torch.full(
        (len(frame_ids), max(1, len(ped_ids)), 2),
        float("nan"),
        dtype=torch.float32,
        device=device,
    )
    for row in rows:
        fidx = frame_to_index[int(float(row[frame_col]))]
        pidx = slot_to_index[str(row[ped_col])]
        try:
            out[fidx, pidx, 0] = float(row[x_col])
            out[fidx, pidx, 1] = float(row[y_col])
        except Exception:
            return None, "csv:parse-error"

    valid_cols = torch.isfinite(out).all(dim=0).all(dim=0)
    if valid_cols.sum() == 0:
        return None, "csv:no-valid-track"
    out = out[:, valid_cols, :]
    out = _fill_trajectory_nans(out)
    return _trim_or_pad_steps(out, target_steps=target_steps), "csv:tracks"


def _load_txt_trajectory(
    path: Path,
    *,
    target_steps: int,
    device: torch.device,
) -> tuple[torch.Tensor | None, str]:
    """Load Jülich TXT tracks: ``person_id frame x y`` at 25 FPS.

    The archive stores coordinates in centimetre-like units and tracks have
    different entry/exit frames.  We select the densest contiguous window,
    interpolate missing samples, convert to metres, and map the local corridor
    into the experiment's station-scale bounds.  The transformation is
    recorded in the source label so it cannot be mistaken for raw coordinates.
    """
    records: list[tuple[int, int, float, float]] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        fields = line.strip().replace(",", " ").split()
        if len(fields) < 4:
            continue
        try:
            person_id = int(float(fields[0]))
            frame = int(float(fields[1]))
            x_value = float(fields[2])
            y_value = float(fields[3])
        except (TypeError, ValueError):
            continue
        if math.isfinite(x_value) and math.isfinite(y_value):
            records.append((person_id, frame, x_value, y_value))
    if not records:
        return None, "txt:empty"

    min_frame = min(item[1] for item in records)
    max_frame = max(item[1] for item in records)
    available_steps = max_frame - min_frame + 1
    window_steps = available_steps if target_steps <= 0 else min(target_steps, available_steps)
    window_start = min_frame
    if available_steps > window_steps:
        occupancy = [0] * available_steps
        for _, frame, _, _ in records:
            occupancy[frame - min_frame] += 1
        running = sum(occupancy[:window_steps])
        best_score = running
        best_offset = 0
        for offset in range(1, available_steps - window_steps + 1):
            running += occupancy[offset + window_steps - 1] - occupancy[offset - 1]
            if running > best_score:
                best_score = running
                best_offset = offset
        window_start = min_frame + best_offset
    window_end = window_start + window_steps
    window_records = [item for item in records if window_start <= item[1] < window_end]
    counts: dict[int, int] = {}
    for person_id, _, _, _ in window_records:
        counts[person_id] = counts.get(person_id, 0) + 1
    selected_ids = sorted(
        [person_id for person_id, count in counts.items() if count >= min(3, window_steps)],
    )
    if not selected_ids:
        selected_ids = sorted(counts)
    if not selected_ids:
        return None, "txt:no-tracks"

    slot_index = {person_id: index for index, person_id in enumerate(selected_ids)}
    out = torch.full(
        (window_steps, len(selected_ids), 2),
        float("nan"),
        dtype=torch.float32,
        device=device,
    )
    for person_id, frame, x_value, y_value in window_records:
        slot = slot_index[person_id]
        out[frame - window_start, slot, 0] = x_value
        out[frame - window_start, slot, 1] = y_value
    out = _fill_trajectory_nans(out)
    out = out * 0.01  # Jülich TXT coordinates are centimetre-like values.
    out = _normalize_juelich_window(out)
    return _trim_or_pad_steps(out, target_steps=target_steps), "txt:juelich-person-frame-xy"


def _normalize_juelich_window(trajectory: torch.Tensor) -> torch.Tensor:
    """Map a local Jülich corridor window into the kernel's station-scale box."""
    result = trajectory.clone()
    for coordinate, (lower, upper) in enumerate(((1.0, 13.0), (4.0, 6.0))):
        values = result[..., coordinate]
        minimum = values.amin()
        maximum = values.amax()
        span = (maximum - minimum).clamp_min(1e-6)
        result[..., coordinate] = (values - minimum) / span * (upper - lower) + lower
    return result


def _find_first(columns: dict[str, str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return columns[candidate]
    return None


def _trim_or_pad_steps(trajectory: torch.Tensor, target_steps: int) -> torch.Tensor:
    if target_steps <= 0:
        target_steps = int(trajectory.shape[0])
    if trajectory.shape[0] >= target_steps:
        return trajectory[:target_steps]
    if trajectory.shape[0] == 0:
        raise ValueError("trajectory is empty")
    repeat = target_steps - trajectory.shape[0]
    if repeat <= 0:
        return trajectory
    last = trajectory[-1:].repeat(repeat, 1, 1)
    return torch.cat([trajectory, last], dim=0)


def _synthesize_real_data_proxy(
    *,
    state: PopulationState,
    walls,
    config: KernelConfig,
    bounds: Bounds,
    params: KernelParameters,
    seed: int,
    steps: int,
    fallback_reason: str,
) -> tuple[torch.Tensor, dict[str, str]]:
    synthetic = _roll_positions(
        state,
        walls,
        config,
        bounds,
        params,
        steps=steps,
    ).detach()
    rng = torch.Generator(device=state.device).manual_seed(seed)
    noise = torch.randn(synthetic.shape, generator=rng, device=state.device, dtype=synthetic.dtype) * 0.01
    return (
        synthetic + noise,
        {
            "path": fallback_reason,
            "source": "synthetic-fallback",
            "status": "fallback",
            "reason": fallback_reason,
        },
    )



def _sample_walkable_points(
    *,
    outer: torch.Tensor,
    holes: list[torch.Tensor],
    obstacles: list[torch.Tensor],
    requested: int,
    device: torch.device | str,
    seed: int = 17,
    seed_distance: float = 0.40,
    grid_step: float = 0.45,
) -> torch.Tensor:
    """Generate deterministic non-overlapping walkable points."""
    max_x = float(outer[:, 0].max())
    max_y = float(outer[:, 1].max())
    x_coords = torch.arange(0.8, max(max_x - 0.8, 0.8), grid_step, device=device)
    y_coords = torch.arange(0.5, max(max_y - 0.5, 0.5), grid_step, device=device)
    candidates = torch.stack(torch.meshgrid(y_coords, x_coords, indexing="ij"), dim=-1).reshape(-1, 2)
    valid = filter_points_in_polygon(
        candidates.unsqueeze(0),
        outer,
        holes=holes,
        obstacles=obstacles,
    )[0]
    selected: list[torch.Tensor] = []
    for point in candidates[valid]:
        if selected:
            existing = torch.stack(selected)
            sq = ((existing - point) ** 2).sum(dim=1)
            if bool((sq.sqrt() <= seed_distance).any()):
                continue
        selected.append(point.clone())
        if len(selected) >= requested:
            break

    if len(selected) < requested:
        rng = torch.Generator(device=device).manual_seed(seed + 100)
        attempts = 0
        max_attempts = requested * 400
        while len(selected) < requested and attempts < max_attempts:
            attempts += 1
            point = torch.stack(
                (
                    torch.rand((), generator=rng, device=device) * max_x,
                    torch.rand((), generator=rng, device=device) * max_y,
                ),
                dim=-1,
            )
            inside = filter_points_in_polygon(point[None, None, :], outer, holes=holes, obstacles=obstacles)
            if not bool(inside.item()):
                continue
            if selected:
                existing = torch.stack(selected)
                if bool(((existing - point) ** 2).sum(dim=1).sqrt().le(seed_distance).any()):
                    continue
            selected.append(point)

    if len(selected) < requested:
        if not selected:
            raise ValueError(f"unable to sample {requested} walkable points with seed={seed}")
        selected.extend([selected[0].clone() for _ in range(requested - len(selected))])

    return torch.stack(selected[:requested])


def _normalize_weights(weights: LossWeights | None) -> LossWeights:
    if weights is None:
        return DEFAULT_LOSS_WEIGHTS
    normalized = weights.clamp()
    total = (
        normalized.trajectory_mse
        + normalized.checkpoint_position_mse
        + normalized.checkpoint_velocity_mse
        + normalized.density_proxy_mse
        + normalized.section_flow_mse
    )
    if total == 0:
        return DEFAULT_LOSS_WEIGHTS
    return normalized


def export_calibration_plan(path: str | Path, payload: object) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def replace_state(state: PopulationState, position: torch.Tensor) -> PopulationState:
    from dataclasses import replace

    return replace(state, position=position)
