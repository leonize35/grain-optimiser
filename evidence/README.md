# Paper 2 evidence

Reproducible software-verification evidence for the transferable grain-silo DES methodology.

> **Synthetic data only.** Sites A and B are the prototype's demonstration configurations. Site C and its
> segregation-trap variant were written for this evidence. No configuration describes, or was calibrated to, a real
> silo, and no output here is an observation of silo performance. Empirical validation has not been performed.

## Layout

| Path | Content |
|---|---|
| `configs/` | The four configurations, labelled in `configs/index.json` |
| `overlays/` | Deterministic experiment inputs layered onto a configuration: outage plans, stock-event plans, reporting thresholds |
| `out/paper2-v1/` | The evidence package (generated) |
| `out/paper2-v1/manifest.json` | Engine version, engine source digest, prototype digest, base seed, policy mappings per queue group, configuration hashes, experiment list, and the **sha256 of every deterministic file** |
| `out/paper2-v1/EVIDENCE_SUMMARY.md` | Claim, configuration, experiment, quantitative outcome, acceptance criterion, limitations, evidence file |
| `out/paper2-v1/structure/` | Automated structural comparison of the configurations |
| `out/paper2-v1/experiments/<ID>/` | `runs.json` (per-run settings, seeds, policy mapping, physical results, operational results, KPIs, digests), `audit.json` (independent flow-audit output), `evaluation.json` (acceptance), `traces/` (event trace of replication 0 per cell, gzip without timestamps) |
| `out/paper2-v1/tests/` | Test outcomes per test id; prototype self-test result |
| `out/paper2-v1/environment/` | Time, platform, versions, git state, raw JUnit report and outputs. **Excluded from reproduction checks.** |
| `out/paper2-v1-reproduction-check.json` | Result of the latest full rebuild-and-compare |

## Commands

```bash
python tools/evidence_run.py build
python tools/evidence_run.py check
python tools/evidence_run.py digest '{"exp": "EV-C1", "site": "A", "overlays": [], "policy": "M-FF", "seed_index": 0, "demand": 1.0, "days": 1}'
```

- `build` writes the package.
- `check` rebuilds it in a temporary folder and compares deterministic files only.
- `digest` runs one cell and prints its digest (used for the hash-seed reproduction check).

## Queue-policy mappings

Every queue group has an explicit policy in every run (full mapping in `manifest.json`):

| Name | Meaning |
|---|---|
| M-FF | feasible_first in every queue group (the engine's unchanged default) |
| M-PT | strict FIFO at the hopper, feasible_first elsewhere (equivalent to the prototype's `tip: "fifo"`) |
| M-SF | strict FIFO in every queue group, including grain transfers. A stress case, **not** claimed to represent silo practice. |
| ADV-REV, ADV-RAND, ADV-RHOL | Adversarial test policies (reverse order; seeded random order; random order with head-of-line blocking). Test devices only. |

## Acceptance rules

- **Physical invariants** must hold in every run: 0 flow-audit problems, mass balance 0 kg, 0 engine violations,
  unexplained reconciliation 0 kg.
- **Operational outcomes** (stalls, unfinished trucks, blocking reasons) are reported separately. A legitimate
  operational stall is not a verification failure.
- **Reproduction** compares deterministic outputs only.
