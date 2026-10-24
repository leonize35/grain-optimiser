## Package verification status (clean build)

| Item | Confirmed value | Where |
|---|---|---|
| Source commit | `54d3869` (tools and configurations committed; engine source unchanged since step 18, digest `bb6d050d…`) | `evidence/out/paper2-v1/environment/environment.json` |
| Working tree at build time | clean apart from the package's own output folder (`?? evidence/out/`) | same file, `git_dirty_files` |
| Test suite | 343 passed, 2 expected failures (strict xfail: the known equal-age intake tie-break) | `evidence/out/paper2-v1/tests/test_outcomes.json` |
| Prototype self-tests | 12/12, prototype engine sha256 unchanged | `evidence/out/paper2-v1/tests/prototype_selftests.json` |
| Manifest | 90 deterministic files with sha256; manifest sha256 `71ca9133…` | `evidence/out/paper2-v1/manifest.json` |
| Rebuild and compare | independent full rebuild: 90/90 files identical, manifest settings identical, 0 differing | `evidence/out/paper2-v1-reproduction-check.json` |
| Hash-seed check | 16/16 run digests identical in fresh interpreters (PYTHONHASHSEED 0 and 12345) | `evidence/out/paper2-v1/experiments/EV-R1/evaluation.json` |

Reproducibility is therefore confirmed **on one platform** (Windows 11, CPython 3.14.8, pydantic 2.14.1). Other
operating systems and Python versions have not been tested.

## Three kinds of result

1. **Verified simulation behaviour** (software verification; acceptance criteria met). In every one of 217 audited
   runs:
   - grain conservation was exact (0 kg);
   - no flow-audit problems occurred: route reservation, feed limits, merge rule, clear times, outages, bin
     capacity and identity, segment commodity;
   - the unexplained reconciliation difference was 0 kg.

   Further:
   - Every applicable record corruption was detected (12/12).
   - The physical invariants held under adversarial queue policies.
   - The reporting threshold never changed a decision.
   - The run outputs reproduce exactly.
   - On the common subset, admission decisions match the JavaScript prototype in 8/10 scenarios. The other 2 differ
     only by the documented equal-age tie-break.
2. **Synthetic experimental findings** (outputs of the model under synthetic inputs; they show what the method can
   reveal, not what any silo does):
   - throughput and waiting differences between policy mappings (Table 5, figures);
   - stalls of the segregation-trap variant;
   - the hold rule blocking an alternative route;
   - the unused spare bins.
3. **Not empirically validated:** everything. No output has been compared with observations from a real silo. No
   parameter is calibrated. Sites A and B are prototype demonstration data; Site C and the trap variant were written
   for this evidence.

## Stalls, failures and unexpected outcomes

- **Failed tests: none.** No evaluation failed its acceptance criterion in the clean build.
- **Expected failures (2):** the strict-xfail equivalence scenarios `two_shared_opening_grain/tip=fifo` and
  `/tip=feasible`. They differ from the prototype only by the equal-age intake tie-break: the prototype uses
  configuration order, this engine uses request order. With the prototype's tie-break substituted they match
  exactly. **No complete cross-platform equivalence is claimed**, and none for features the prototype cannot
  represent (Table 7).
- **Legitimate operational stalls: 2 of 217 runs, both on the segregation-trap variant (EV-S2):**

  | Run | Stalled at | Cause |
  |---|---|---|
  | M-FF (feasible-first everywhere), seed 1 | 18:55, after all 187 arrivals | Grade-1 maize had **no compatible storage destination**: BN1 full (3,000 t); BN2 (accepts grades 1 and 2) taken by grade 2; BS1 (accepts 1 and 2) holding a 1.16 t grade-2 residue. Three hoppers held grade-1 lots that could not move. |
  | M-SF (strict FIFO everywhere, incl. transfers), seed 1 | 12:35 | The front lot of the strict-FIFO transfer queue was stranded (`BIN_INCOMPATIBLE`) and held back every other transfer (`QUEUE_ORDER`). |

  In both runs the physical invariants held and the stall was reported with its reasons. **Correction to the
  earlier audit:** feasible-first can also stall when no compatible storage destination remains; it is not only
  the strict-FIFO stress mapping. (The package's generated `EVIDENCE_SUMMARY.md` attributes the EV-S2 stalls to
  M-SF in its limitation column; its outcome column correctly shows M-FF 1/5 and M-SF 1/5. This report supersedes
  that wording.) A stall ends the run: the M-SF run stopped after 108 of the day's trucks had arrived, so its
  operational figures cover a partial day.
- **No stalls in 202 other runs**, on Sites A, B and C under M-FF, M-PT, M-SF and the three adversarial policies.
- **Unexpected outcome 1, alternative route blocked under the hold rule (EV-F2b):** when EN1 stops at 08:00, 0
  transfers use the alternative CN1→EN2 route in all 5 runs. A transfer running on CN1→EN1 is suspended and, under
  the provisional rule I1 (hold-and-resume), keeps the shared upstream conveyor CN1 reserved for the whole outage.
  With EN1 already down at opening (EV-F2a), the alternative route carried 7, 10, 7, 10 and 16 transfers. This is a
  consequence of a provisional modelling assumption, not of verified silo practice.
- **Unexpected outcome 2, identical results for M-PT and M-SF on Site A:** the decisions are identical in 10/10
  cells. Site A has single sampling, weighing and elevator units, so strict FIFO beyond the hopper never changes a
  decision. On Sites B and C the two mappings differ in 10/10 cells.
- **Large book − physical differences in EV-C2 (about −3,000 to −4,500 t):** these are an artefact of the
  synthetic stock plan. Each plan records a survey of 100 t in a bin holding 800-2,200 t and then accepts that
  survey into the book. The whole difference is attributed to survey-based corrections; the unexplained part is
  0 kg in every run. It shows that the reconciliation exposes an implausible accepted survey. It says nothing about
  real stock records.
- **Fixed bin preference:** spare compatible bins and alternative routes are rarely used (Site C: BN3 and BN5
  unused in the audit runs). Bin choice follows a fixed rule (same grain first, then route order); there is no
  allocation policy by decision.

## Interpretation for Results and Discussion (synthetic evidence)

- **Methodological claims supported by verification:**
  - Conservation, route feasibility and segregation are enforced by the engine's reservation and identity rules.
    They are checked independently from the records alone.
  - The same unchanged engine (one source digest; no site constants in the code) ran three structurally different
    configurations:
    - one intake system with no route choice (A);
    - two independent systems (B);
    - two systems with an interconnect, alternative intermediate routes, a multi-feed elevator and graded grain (C).
  - Queue policies only order requests. Even deliberately adversarial orderings never broke a physical invariant,
    which supports separating policy from physics.
  - Results reproduce exactly from the manifest.
- **What the synthetic experiments illustrate** (hypotheses for empirical study, not findings about silos):
  1. *Policy trade-off.* On every site, feasible-first (M-FF) gave the shortest mean unloading turnaround:
     118 / 61 / 75 min on A / B / C, against 149 / 79 / 103 min for the prototype-equivalent mapping (M-PT). It also
     completed at least as many trucks. The cost was overtaking: the maximum overtakes of one truck averaged
     30 / 41 / 69 under M-FF, against 0 / 1.2 / 1.0 under M-PT. Strict FIFO everywhere (M-SF) was worst on Site C
     (128 trucks completed against 149; 141 min turnaround). The confidence intervals are wide with 5 seeds, and
     on A and B the throughput differences are within them.
  2. *Segregation capacity is a structural property.* A configuration can be valid and still lose all storage for
     one grade once shared-grade bins are captured by another grade, under feasible-first too. A static check of
     grade-specific storage robustness, and allocation rules, are needed before such sites are compared.
  3. *Recovery rules interact with topology.* Holding a suspended route can block an alternative route that shares
     upstream equipment. The recovery rule therefore needs empirical confirmation (I1).

## Limitations (all results)

- **Synthetic inputs only** (configurations, demand profiles, service-time distributions, outage and stock plans).
  No real-silo data and no calibration.
- **No empirical validation.** Verification shows the software follows its rules, not that the rules or numbers
  match a real silo.
- **Fixed bin-allocation preference** (same grain first, then route order). Multiple compatible bins and
  alternative routes are under-used; no claims about allocation strategies.
- **Provisional modelling assumptions** I1-I7 (interruptions), the stock-adjustment scope (losses in bins only,
  explicit quantities, no moisture attribute), and grain on conveyors as a modelled in-transit mass only.
- **No mechanical capacity model** (rates are inputs). No random breakdowns. No by-products, drying or regrading.
- **Small sample:** 5 seeds per cell, a 1-day horizon, wide confidence intervals. A stall ends its run, so that
  run's operational figures cover a partial day.
- **One platform** for reproducibility. Prototype equivalence only on the common subset, with the tie-break
  difference unresolved.

## Evidence files

| Result | File |
|---|---|
| Manifest (inputs, mappings, hashes of all deterministic files) | `evidence/out/paper2-v1/manifest.json` |
| Reproduction check | `evidence/out/paper2-v1-reproduction-check.json` |
| Configurations (synthetic, labelled) | `evidence/out/paper2-v1/configs/` (sources in `evidence/configs/`, labels in `index.json`) |
| Overlays (outage, stock and threshold plans) | `evidence/out/paper2-v1/overlays/` |
| Structural comparison (Table 1) | `evidence/out/paper2-v1/structure/structure.json`, `structure.md` |
| Per-run results, audits, traces | `evidence/out/paper2-v1/experiments/<EV-ID>/runs.json`, `audit.json`, `traces/*.jsonl.gz` |
| Acceptance per experiment | `evidence/out/paper2-v1/experiments/<EV-ID>/evaluation.json` (EV-C1, C2, C3, F1, F2, S1, S2, P1, P2, T1, T2, R1, X1) |
| Test outcomes; prototype self-tests | `evidence/out/paper2-v1/tests/test_outcomes.json`, `prototype_selftests.json` |
| Environment (excluded from reproduction) | `evidence/out/paper2-v1/environment/` |
| Generated claim summary | `evidence/out/paper2-v1/EVIDENCE_SUMMARY.md` (EV-S2 limitation wording superseded above) |
| Figures | `docs/evidence/figures/fig_completed_by_policy.svg`, `fig_turnaround_by_policy.svg` |
| How to reproduce | `python tools/evidence_run.py build`, then `python tools/evidence_run.py check`; tables and figures: `python tools/evidence/report.py` |
