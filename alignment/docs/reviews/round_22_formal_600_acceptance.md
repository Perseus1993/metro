# Round 22: first valid formal 600-step baseline evidence

Date: 2026-08-04 20:16 CST. Decision: **valid formal fail / implementation hold / release hold**.

## Frozen inputs

| Item | Value |
|---|---|
| Scene | `platform_boarding` |
| Duration | 10 minutes, 1 second/tick, 600 horizon steps |
| Demand window | 10 minutes, 600 demand steps |
| Entry / exit demand | 2500 / 2200 persons/hour |
| Seed | 42 |
| Design SHA-256 | `d401a34735b0aa1e54273eead86b5e8435594e82693ed245a4ac870abbe8ba99` |
| Metro source SHA-256 | `d53bd72110e60abee7fdf27b5ebf605ca961def908ee86ecfdb1b9e7ac9976ef` |
| Analysis source SHA-256 | `151bed69eed7e5eca1666a16cc8beb8cf2eea01ab1e3aa07dff66653ebfbd3f9` |

No duration extension, demand reduction, trace replay, or old artifact was used.

## Formal runner result

Command:

```powershell
uv run python scripts\run_alignment_scene.py `
  --scene-id platform_boarding `
  --output data\metrics\platform_boarding_simulated.parquet
```

Exit code 1 is the expected fail-closed result. The v2 preflight ran before Metro model construction, so the runtime correctly remained `not_started`; a formal workflow must not bypass a deterministic invalid-input gate merely to consume 600 ticks.

Quantitative conflict:

- minimum body clearance: 0.396 m;
- runtime candidate spacing: 0.4 m;
- projection clearance: 0.189 m; maximum projection shift: 0 m;
- peak same-tick alighting batch: 4;
- 67 unique source candidates;
- 60 candidates inside the boarding holding polygon;
- 64 candidates inside its clearance buffer;
- 4 candidates within door-axis clearance.

Classification: `model_invalid / source_geometry_conflict`; `capacity_certificate=false`. This is not evidence of `capacity_exceeded`.

Artifact: `data/metrics/platform_boarding_source_preflight.json`, 6172 bytes, SHA-256 `f7defea486122f422a6f9102c1cacaf52c81efeed59122b1bc3d36c956f6ea3a`.

## Complete acceptance result

Command:

```powershell
uv run python scripts\verify_acceptance.py --out docs\acceptance_latest.json
```

The verifier completed in 87.3 seconds. Its non-zero exit code is the formal aggregate HOLD result, not an execution failure.

| Step | Result | Current evidence |
|---|---|---|
| 1–4 | pass | dependencies, registry, 185,234,516-row canonical, and exactly rebuilt observed v5 |
| 5 | fail | current-fingerprint source preflight completed; runtime not started; model invalid |
| 6 | fail | comparison schema is stale because no valid current simulation exists |
| 7 | pending | parameter report intentionally absent |
| 8 | pass | clean process, isolation, `175 passed`, and Ruff pass |

Acceptance artifact: `docs/acceptance_latest.json`, 5535 bytes, SHA-256 `ddd69591d61dda153ec2c1daa4d09e625636abadc0b5bd8d54636e5574d6c6ab`.

This is the first formal evidence snapshot in which the source blocker, verifier, Metro tree, analysis tree, design, and scene configuration all agree. The next implementation dependency is the Metro-core PTI exchange contract, not another alignment runtime extension.
