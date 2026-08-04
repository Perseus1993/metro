# Round 20 independent review and current blocker

Date: 2026-08-04. Scope: current `alignment/` source, current Eindhoven canonical/observed evidence, and the current Metro seam. The three independent agents were retriggered after every P0/P1 fix; their final pre-long-run rounds were methodology Round 8, Metro Round 8, and generality Round 6.

## Current executable result

| Gate | Result | Quantitative evidence |
|---|---|---|
| Ruff | pass | `All checks passed!` |
| Pytest | pass | `137 passed` |
| Step 1–4 | pass | current `docs/acceptance_latest.json` |
| Step 5 | fail | published simulation wrapper is still v2; current 600-step run stopped at step 327 |
| Step 6 | fail | published comparison wrapper is still v2 |
| Step 7 | pending | `parameter_report_platform_boarding.json` is absent |
| Step 8 | pass | every registered raw file, canonical, and trace pattern is ignored |
| implementation / release | hold / hold | formal non-skip acceptance exit code 1 |

Observed v5 was rebuilt from 185,234,516 canonical rows. Five complete contiguous windows contain 199,806 sampled rows and 4,909 packed frames. Walking-proxy support is 102,075 points / 806 agents / 4,909 frames / 5 windows with p50 1.169 m/s. The fundamental diagram has only two populated low-density bins, so it is not a congested-branch validation.

## Independent agent conclusions

### Industry/paper methodology

P0=0 and P1=0 after adversarial replay. The agent verified strict raw identity types, trusted trace interval binding, correct small/full frame-time validation, pristine producer roundtrip, exact observed recomputation, and rejection of forged raw/canonical/provenance/metrics/summary/wrapper evidence.

The remaining scientific P2 findings are intentional holds: the speed statistic is a low-global-density speed-truncated proxy rather than isolated free-flow speed, and observed FD support does not cover a congested branch.

### Metro compatibility

P0=0 and P1=0 in the alignment/Metro API seam before the long run. Current Metro raw evidence contains 888,506 points with integer passenger IDs, string episode IDs, finite numeric physical fields, and a 0.2 s sample interval. Direct and wrapped Metro traces roundtrip exactly. A 0.4 s trace against a trusted 0.2 s SceneConfig is rejected by producer, verifier, and compatibility agent.

The remaining adversarial P2 boundary is that the run envelope is not externally signed. The current transaction and fingerprints prevent accidental corruption, stale reuse, and mid-run source changes, but not an attacker who rewrites a manifest and re-labels old raw evidence. A signed or append-only evidence root is required for that threat model.

### Generality / anti-patch

P0=0 and P1=0 after counterexamples for Windows device/path IDs, registry key/value aliases, zero ready scenes, multiple active/ready defaults, malformed nested JSON/Parquet, source TOCTOU, `--skip-tests`, trace identity coercion, trace-clock mismatch, and small-data frame-rate mismatch. The agent classified the implementation as registry/scene-driven and fail-closed rather than an Eindhoven-specific fallback.

## Step-327 long-run blocker

The current-fingerprint formal run reached step 327 and then raised:

```text
JuPedSimPlacementBlocked: JuPedSim could not place passenger 405
at (31.2, 22.047000000000004)
```

This passenger was an alighting arrival in the `platform_edge_a` boarding holding region. Metro's alighting source pre-check uses Mesa positions and a 0.360001 m clearance, while the native JuPedSim placement contract requires 0.369 m. The passenger is published to the model before native admission, retains `target == position`, and immediately enters the already-at-target waiting-body conversion. Native exact placement then fails.

Lowering alignment demand may reduce the chance of collision but does not close the admission-contract gap and would weaken the required congested-regime evidence. It is therefore not accepted as a fix for the baseline scene.

The general fix belongs at the Metro movement/source boundary: expose native exact-placement admission, publish a passenger only after admission succeeds, and retain blocked arrivals in a source/FIFO pending queue for retry at the next JuPedSim boundary. Acceptance requires all 600 steps, zero uncaught placement failures, no ghost/dropped passengers, counters reconciling generated+pending+admitted, and a current-fingerprint v5 bundle promoted atomically.

Until that external dependency changes, old v2 simulation/comparison/report artifacts remain history only and implementation/release stay `hold`.
