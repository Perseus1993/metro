# Review evidence index

`docs/agent_*round_1..14*.json` and `ROUND_7_ACCEPTANCE_SUMMARY.md` predate the strict
canonical rebuild, PedPy v5 artifacts, episode-aware Metro adapter, and frame-gap fix. They are
retained as history only and must not be cited as current acceptance evidence.

Current evidence order:

1. `../acceptance_latest.json` — executable Step 1–8 gate;
2. `round_25_admission_resource_review.md` — current Step 5 admission-resource, source-integrity, evidence-chain, branch, and debt review;
3. `round_24_step5_conservation_handoff.md` — prior Step 5 scope, short-probe evidence, and the finite-admission blocker;
4. `round_22_formal_600_acceptance.md` — first current-fingerprint formal 600-step baseline evidence, with a valid fail result;
5. `round_20_automated_all.json` — reproducible behavior/artifact checks for all three views;
6. `round_21_independent_agents.md` — independent method, Metro, and generality review of the fail-closed source contract.

`round_20_independent_agents.md` is retained as the historical step-327 diagnosis. Its runtime
status and test count are superseded by Round 21 and must not be cited as current evidence.

The automated scripts are guardrails, not substitutes for independent review. Each independent
agent must inspect the newest source and artifacts, report P0/P1/P2 with a reproduction and
quantitative acceptance condition, and must be triggered again after any P0/P1 fix. Scientific
`release_status=hold` is an expected honest outcome and does not become a software failure unless
the hold is hidden, bypassed, or mislabeled as validated.
