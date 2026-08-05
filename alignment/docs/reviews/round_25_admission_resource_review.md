# Round 25 Step 5 admission-resource review

Date: 2026-08-06 (Asia/Shanghai)

## Decision

Round 25 completes the scoped Step 5 source-integrity work. The finite upstream resource now
controls flow with geometry-free credits, while exact physical exclusion remains a placement-time
decision. Entry and exit demand are blocked into explicit FIFO pending ownership instead of being
dropped. The 120-step tripwire and 240-step ladder both pass the formal source-integrity gate.

This is not a Step 6 release decision. Geometry evidence remains `proxy`, the seven-door design is
frozen rather than observationally validated, `dynamic_blocked` remains Round-26 work, and no new
600/900-step ladder result is published by Round 25. `T1_measurement_900.json` is a residence-time
measurement input, not a restored 900-step acceptance level.

## Completion record

| Task | Result | Evidence |
|---|---|---|
| T0 baseline | pass | `T0_two_arm_baseline.json` preserves the Round-24 finite/amplified comparison and freezes all inputs except admission capacity. |
| T1 residence W | measured | Entry `n/completed/censored=83/83/0`, p50/p90/p99 `18/29/36`; exit `73/68/5`, p50/p90 `219/351`, p99 right-censored with lower-bound p99 `785`. |
| T2 resource split | pass | Admission credit holds no polygon, point or slot; placement remains exact and retryable; lifecycle cleanup records right-censoring. |
| T3 preflight | pass | Deterministic schedule envelopes require entry/exit capacities `26/73`; deliberate `25/72` underconfiguration fails before runtime. |
| T4 gate | pass | `spawned == scheduled`, zero terminal pending, pending residence `<10`, exhaustion ratio `<=5%`, zero dropped, conservation true and zero liveness violations. |
| T5 120 | pass | Entry `83/83/0`, exit `55/55/0`, dropped `0`, conserved `true`, liveness `0`; finite and amplified arms have zero spawned/scheduled difference. |
| T6 attribution | pass | All 16 T5 events and all 21 T8 events are `placement.dynamic_blocked`; top three T8 regions are entry release-apron lanes 2/1/3 with `10/6/5`. |
| T7 split | pending final audit rerun | PR-1 and PR-2 are independent review units; final branch was rebuilt after PR-2 integration to remove its duplicate cherry-pick. |
| T8 240 | pass | Entry `83/83/0`, exit `73/73/0`, dropped `0`, conserved `true`, liveness `0`; the prior 120-step gate replays. |
| T9 debt | pass | Five registered debts, three evidence-backed legitimate designs, zero unclassified candidates; first-register delta is correctly `null`, with `unclassified_candidate_delta=-6`. |

The production sizing rule uses the deterministic demand schedule's maximum arrival envelope over
the registered W window. `L + 3*sqrt(L)` is retained only as a reference because the configured
arrivals are scheduled, not a demonstrated Poisson process. Residence evidence binds the design,
scene, seed, rates, movement parameters, schedule, source fingerprints and artifact hash; a missing
or mismatched field fails closed.

## Independent audits

| Audit | Result | Material conclusion |
|---|---|---|
| A lifecycle | pass | No token leak, double release, geometry coupling, pending TTL or drop path was found. |
| B conservation | pass | Every due group remains exactly admitted or pending; the independent `1/0/0` counterexample fails. |
| C sizing | pass, one P2 | Capacity `26/73` is reproducible; the approximately 19x nominal-exit-service gap remains `DEBT-4`. |
| D generality | pass | Rates 2500/5000/800 derive envelopes 26/52/9; seed and design mismatches invalidate old evidence. |
| E evidence chain | pass | Ten artifacts verify against content-addressed copies; T8's 18 gate groups replay exactly. |
| F branch risk | pending final audit rerun | The first audit found duplicate PR-2 history; the branch was rebuilt on the PR-2-integrated main with an identical final tree. |
| G patch/debt | pass | Seventeen logical production changes classified 15 fix/2 visibility-only; all visibility debt is registered and all seven fix bodies satisfy the three-question contract. |

Round completion requires every final audit status to be `pass`; the pending F entries above are
replaced only after the rebuilt topology is independently verified.

## Evidence integrity

The manifest contains ten required aliases and ten committed content-addressed immutable copies.
Verification checks both byte-level file hashes and canonical artifact hashes. Round-25 JSON is
marked `-text`, and source fingerprints normalize CRLF/CR/LF to LF before hashing so a clean Windows
checkout agrees with Git blobs.

- Metro source fingerprint v2: `ec2ecc090713a995667dc089bea0775e948cdbe154a1da302a9b4670cdd321e5`
- Analysis source fingerprint v2: `43cfc72b51343f270f9f4f628f580f93fa6d23e71575a2e62a206d5f23d57512`
- Evidence manifest artifact hash: `5ec8fbea37d4651373d703bed225989b98813bab055a44dd7ae1750cd6365aa6`
- T1 residence artifact hash: `6d019bd5a5cd5d61c3878663bfb31963bd1b94b85eb73e727356a9f3d55b43ce`
- T8 240 artifact hash: `97a90ce90e8b10972a66b3d4a88ebb80e395e02e8b8d1287a628681122d11323`

Publication fails before manifest switching when a resolved Windows target would be at least 262
characters. A failed staged publication leaves the previous bundle intact.

## Validation

- Round-25 relevant suite: `138 passed, 7 skipped`.
- PR-1 affected suite: `55 passed`; the two formerly blocked Playwright CLI tests separately passed
  in `250.13s`, for 57 affected passes in total.
- Post-rebuild full root suite: pending final run.
- Import Linter on the rebuilt final source tree: 775 files, 3535 dependencies, 12 contracts kept,
  0 broken.
- Round-25 changed Python files after the imported PR-2 unit: Ruff passed.
- Evidence manifest `--verify-only`: 10 artifacts, pass.
- Seven `fix(...)` commits: 7 checked, 0 missing required failure/visibility/debt fields.

The seven skips are retained as visible environment/coverage conditions; they are not converted to
passes. The broader pre-existing Ruff findings in the PR-1/PR-2 history were not silently rewritten
as Round-25 changes.

## Branch and rollback boundary

The intended integration order is now encoded in history:

1. PR-1 formal ladder and publication support is in local `main` at `b7e11eb3`.
2. Independent PR-2 is `codex/gate-runtime-handoff` at `507dc933` and is merged into local `main` by
   `ca2c1f14`.
3. `codex/round25-final` is rebuilt from that merge and contains only the later fixed-design,
   recovery, admission, evidence, reproducibility and review units. The former equivalent
   `22102436` cherry-pick is absent.

PR-2 can therefore be reverted as its own merge parent/unit; the Round-25 admission work can be
reverted from newest to oldest without leaving a second copy of the gate handoff. The rebuilt tree
is byte-for-byte equal to the pre-rebuild reviewed tree; only ancestry and commit IDs changed.

## Registered limits and next work

The baseline debt register contains `DEBT-1` through `DEBT-5`:

- unobserved 10 m alighting-source lateral offset;
- stalled-region replanning used on 78.8% of the frozen 900-step cohort;
- unobserved seven-door synthetic design;
- approximately 19x nominal exit-service/completed-throughput gap;
- placement retry at 11.59% (T5) and 13.46% (T8), plus missing stable per-mechanism counters.

Round 26 should instrument and remove the high-frequency placement/waiting/stall dependencies and
explain downstream exit service before any 600/900 ladder restoration. Step 6 remains blocked until
observed geometry and non-proxy movement evidence exist.
