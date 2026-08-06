# Round 26 fix-contract ledger

This ledger answers the same three questions for every `fix(...)` commit in the Round-26 stack:
what physical or evidentiary mechanism changed, why the change is general, and what evidence rejects
a seed-, passenger-, or threshold-specific patch. A visibility-only fix explicitly says that no
physical mechanism changed.

| commit | mechanism changed | why general | anti-patch evidence |
|---|---|---|---|
| `026f9588` | No physical rule changed; source-size ownership was split into focused modules. | The split follows decision-holding, waiting-geometry, and downstream-evidence responsibilities. | Directed behavior tests retained decisions; only historical `runtime_base.py` remains over budget. |
| `a777cddd` | No physical rule changed; canonical `travel` became a falsifiable motion/upstream-state breakdown. | Both flows use the same state and velocity classifier. | Owner-level totals reconcile with unchanged canonical phases and residence, with unclassified time exposed rather than suppressed. |
| `d10b1d13` | No physical rule changed; shutdown diagnostics retain lifecycle-censored owners after token closure. | Reconstruction keys off the lifecycle record, not an owner id or scenario. | Closed-owner tests cover the shutdown boundary and raw residence records remain unchanged. |
| `e6031afa` | Exit holding temporarily preferred locally near the published body. | The ranking used geometry for every exit owner. | The controlled run worsened replans to 46/314; `e4ca3da0` reverted it and the failed experiment is not counted as progress. |
| `4e55795b` | Exit approaches fan out before converging on their lane mouths. | Offset is derived from crossed-lane count for every compiled bank and preserves lane ownership. | Seed-42 900-step completion changed from 68/73 with five censored owners to 73/73; later seeds and horizons reproduce full completion. |
| `366d17ec` | Exit holding cells are ranked by live-body path clearance before the existing deterministic order. | Ranking uses the same body-clear predicate for every passenger and cell. | Controlled seed-42 replans fell from 9/314 to 1/314 without changing the replan threshold or counter. |
| `4a394e59` | Entry decision holding similarly ranks unchanged finite cells by path clearance. | It applies to the compiled cell set and all positioned owners; positionless synthetic probes retain deterministic behavior. | Three 240-step seeds recorded zero of 314 controlled replans with source and liveness gates intact. |
| `7fa6e393` | Holding exclusion and release capacity now share one body-clear finite geometry and bounded alternates. | Capacity counts admissible body rows for every lane instead of raw lattice rows. | Three 240-step seeds record zero placement retries; no retry name, denominator, or threshold changed. |
| `e4cd5a5e` | A genuinely stalled owner may advance a compiler-proven ingress turn already reached within the semantic radius. | Proof requires the same committed gate, fixed lane mouth, existing next route point, and geometric reach for every owner. | Canonical multi-seed runs remain at or below 0.641% replans; remote stalls still take the ordinary replan path and emit unchanged counters. |
| `05f0ade1` | Finite admission remains reserved early, while service FIFO begins only at physical lane-mouth capture; approach claims compact without retargeting the mouth. | Reservation capacity and physical arrival order are separated for every gate lane and demand cohort. | Gate-focused and bidirectional tests pass; 240/480 × three seeds eliminate the empty-queue reservation deadlock while keeping finite owners and source conservation. |
| `01f64607` | A stalled committed gate owner adjacent to any mouth in its compiled bank may finish the tail turn toward its reserved inner slot. | Recovery is bank-geometric: it requires the committed mouth, an exhausted route, measured stall, and distance within two personal-space widths, independent of seed or passenger id. | Two boundary tests cover eligible and remote bodies; 480/600/900 seeds 42/43 complete all 73 exits with stable p99 and at most one replan. |

The ledger does not turn `feat(...)`, `test(...)`, `refactor(...)`, or the explicit revert into
unreviewed fixes. Their behavior/visibility scope remains in their commit bodies and the Round-26
review.
