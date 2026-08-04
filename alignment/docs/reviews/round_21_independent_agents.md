# Round 21/13 final independent review

Date: 2026-08-04 17:22 CST. This review supersedes Round 20 for current status. Three independent agents rechecked methodology, Metro compatibility, and generality after the replay/preflight/publication fixes. They were triggered again after every alignment P1 change.

## Outcome

| Gate | Result | Evidence |
|---|---|---|
| Source-geometry method | pass | clearance 0.396 m; runtime spacing 0.4 m; projection clearance 0.189 m; 67 unique candidates; projection shift 0 m |
| Deterministic conflict | pass | 60/67 inside holding polygon; 64/67 inside its clearance buffer; 4/67 within door-axis clearance |
| Classification | pass | `model_invalid / source_geometry_conflict`; `capacity_certificate=false`; never `capacity_exceeded` |
| Alignment regression | pass | 175 tests, including clean-process CLI smoke; Ruff pass |
| Clean-process runner | pass after upstream repair | the new regression first caught, then verified repair of, the Metro circular import |
| Formal freshness | fail | existing preflight/acceptance fingerprints predate final alignment and Metro changes |
| Scientific / release | hold / hold | no current runnable Metro entrypoint and no publishable simulation v5 |

## Alignment P1 closure

The agents verified these fixes in the final alignment tree:

- fresh runs and trace replay execute the same document-level v2 preflight before model construction or old-manifest use;
- a source blocker is retired only after the replacement immutable bundle and manifest publish successfully; a crash between publication and retirement stays fail-closed;
- verifier semantics require outer `runtime_status=not_started`, `scientific_status=model_invalid`, the exact blocker, and `release_eligible=false`; inner schema/status/outcome/capacity-certificate and non-empty blocker reports are mutation-tested;
- the unused runtime v1 geometry implementation was deleted; v2 uses Metro's actual `max(0.4, radius*2.2)` lattice spacing and walkable projection while the collision contract uses the scenario-wide clearance multiplier;
- admission is FIFO within each source, while a blocked source no longer head-blocks an independent source; constructor exceptions restore the current and unprocessed demand records and propagate;
- `--minutes` is restricted to `1..registered_minutes`; 840 seconds remains diagnostic history, not a replacement formal baseline.

No alignment-scoped P0 or remaining code-design P1 was found. These changes are reusable contracts, not platform-coordinate, demand-reduction, extended-horizon, or private-reservation fallbacks.

## Methodology conclusion

The static result is a deterministic counterexample to the current source/queue resource contract. It is sufficient to reject the model input/control contract without running 600 or 840 steps. It is not a station or door-capacity measurement: it does not estimate calibrated door throughput, dwell clearance, stable backlog, or multi-seed uncertainty. The historical 600-step admitted/pending result was 195/172; 840 seconds changed it only to 197/170. Those runs also had PTI deadlock and train-schedule desynchronization, so they remain diagnosis only.

The general Metro fix remains a train-specific exchange manifest, a shared PTI controller with alighting-first or calibrated mixed policy, shared corridor ownership/keep-clear, a certified alighting reservoir/release apron, and bounded deadlock/hold behavior.

## External blocker observed during review

The shared Metro core changed after the 174-test alignment snapshot. At 17:22 a clean process followed:

```text
passenger -> facilities.runtime_base -> runtime.spatial_capacity_admission
-> runtime.__init__ -> mesa_model -> spatial_queries -> partially initialized PassengerAgent
```

The new subprocess smoke test reproduced this. The upstream task then repaired the import boundary; the same clean-process test and the complete alignment suite now pass (`175 passed`). Alignment deliberately did not pre-import modules to hide the defect.

The remaining external blocker is source-tree stability. Two successive 90-second non-skip acceptance runs saw Metro change `9b7be3… → ef07ee… → 1c127c…`. Both runs correctly failed the source-fingerprint/TOCTOU gates. `docs/acceptance_latest.json` is the current HOLD evidence: Step 1–4 pass, Step 5 fails because its blocker artifact became stale, Step 6 fails, Step 7 is pending, and Step 8 fails because Metro changed during acceptance. After Metro freezes, rerun source preflight and the verifier. Until then, implementation and release remain `hold`.
