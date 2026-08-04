# Round 16 independent review — superseded by fixes

Date: 2026-08-04. This review is retained to show why the next revision was required. Its
conclusion is **not** current acceptance evidence; every P1 below changed code or artifact
contracts and therefore requires a fresh round.

## Industry / paper methodology

- P1: observed and simulated speeds used different physical windows; the comparator did not
  enforce a complete common analysis contract.
- P1: frame packing could bridge sparse source frames and fabricate speed.
- P1: a global-density, speed-truncated sample was labeled “free flow”.
- P1: FD conditional fit did not distinguish density-support coverage and could pass on a
  low-density sliver.
- P1: a scalar minimum sample size hid correlated support across agents, windows, episodes and
  seeds.

Disposition: metrics v3 fixes the physical window at 0.4 s, hashes the shared measurement
polygon, rejects contract mismatches, verifies source continuity, renames the speed quantity as
a non-release proxy, separates FD support from conditional fit, and reports structured support.

## Metro compatibility

- P1: the formal ten-minute artifact predated the current Metro source tree.
- P1: replay accepted a one-way config subset instead of exact schema/value/hash equality.
- P1: the automated check trusted manifest provenance instead of rebuilding canonical evidence
  from the raw movement trace and compiling the current design.

Disposition: simulation manifest v3 records a source/dependency runtime fingerprint and exact
SceneConfig contract; replay has missing/extra/different/hash counterexamples; the compatibility
check reparses the raw trace, compares the canonical table exactly, and compiles the current
DesignDocument.

## General solution / anti-patch

- P1: the same area ID with different bounds could compare as equal.
- P1: off-grid trace times and sparse sampled frames failed only downstream.
- P1: HTTP 416 or ignored Range restart could destroy resumable state before replacement passed
  integrity checks.
- P1: geometry release qualification could be self-declared by an artifact.
- P1: canonical validation accepted object strings, and a non-string dataset ID raised an
  incidental exception.
- P1: the automated generality suite did not execute the complete counterexample suite.

Disposition: polygon hash and trusted scene geometry are comparison inputs; trace/sampling fail
before PedPy; restart downloads preserve the old partial until MD5 succeeds; canonical requires
Pandas StringDtype and stable validation errors; all tests plus a fresh acceptance run are now
part of the generality check.

Round 17 must replay these P1s against newly rebuilt v3 artifacts before the implementation can
be called complete.
