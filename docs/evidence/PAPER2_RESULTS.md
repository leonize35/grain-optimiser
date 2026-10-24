# Paper 2: results from the evidence package `paper2-v1` (generated)

Built from `evidence/out/paper2-v1/manifest.json` (sha256 `71ca9133ee4e4534e64420064875b9309053e6a87854f56ead765c2785acf677`), engine 0.3.0.dev0, engine source sha256 `bb6d050d170971f9…`, base seed 20261023.

**Status of every number below: software-verification output on synthetic configurations.** Sites A and B are the prototype's demonstration configurations; Site C and the trap variant are synthetic. Nothing here is an observation of a real silo, and no empirical validation has been performed. Operational figures (throughput, waiting, stalls) are properties of the synthetic inputs and rules, not predictions for a real site.

## Table 1. Equipment configurations (`structure/structure.json`)

| Metric | A | B | C | C-trap |
|---|---|---|---|---|
| Configuration hash (first 12) | e214e4680b9a | f8a22f2f35f4 | 56712a9a8716 | 37d5d3dd70dc |
| Equipment / connections | 15 / 15 | 23 / 22 | 34 / 39 | 34 / 39 |
| Equipment by type | bin 4, conveyor 4, elevator 1, grader 1, hopper 2, loadpoint 1, sampler 1, weighbridge 1 | bin 6, conveyor 6, elevator 2, grader 1, hopper 4, loadpoint 1, sampler 1, weighbridge 2 | bin 10, conveyor 9, elevator 3, grader 1, hopper 5, loadpoint 2, sampler 1, weighbridge 3 | bin 10, conveyor 9, elevator 3, grader 1, hopper 5, loadpoint 2, sampler 1, weighbridge 3 |
| Independent intake systems | 1 | 2 | 1 | 1 |
| Interconnect equipment | none | none | X1 | X1 |
| Intake systems with interconnects removed | 1 | 2 | 2 | 2 |
| Intake routes / load routes | 8 / 4 | 12 / 6 | 40 / 10 | 40 / 10 |
| Hopper-bin pairs with alternative intermediate routes | 0 / 8 | 0 / 12 | 4 / 36 | 4 / 36 |
| Equipment shared by several hoppers | C3, E1 | C1, C2, C3, C4, E1, E2 | CN1, CS1, DN1, DN2, DS1, EN1, EN2, ES1, X1 | CN1, CS1, DN1, DN2, DS1, EN1, EN2, ES1, X1 |
| Equipment shared by intake and load-out | E1 | none | EN2 | EN2 |
| Multi-feed equipment | none | none | EN1 | EN1 |
| Graded commodities | none | none | YM | YM |
| Compatible bins per grain identity | YM 2, WM 2, SB 1 | YM 3, WM 2, SB 2, SF 1 | YM:1 3, YM:2 3, WM 3, SB 2 | YM:1 3, YM:2 4, WM 3, SB 2 |
| Grain identities with a single reachable bin from some hopper | SB | YM, SF | YM:1, YM:2, WM, SB | YM:1, WM, SB |
| Load points / weighbridges | 1 / 1 | 1 / 2 | 2 / 3 | 2 / 3 |


## Table 2. Grain conservation (EV-C1 base days; EV-C2 with outages and stock events)

| Experiment | Site | Policy mapping | Demand | Runs | Audit problems | max abs balance (kg) | Engine violations | Unexplained (kg) | Received t/day (mean ± 95% CI) |
|---|---|---|---|---|---|---|---|---|---|
| EV-C1 | A | M-FF | ×1.0 | 5 | 0 | 0 | 0 | 0 | 1862 ± 293 |
| EV-C1 | A | M-FF | ×1.2 | 5 | 0 | 0 | 0 | 0 | 1763 ± 245 |
| EV-C1 | A | M-PT | ×1.0 | 5 | 0 | 0 | 0 | 0 | 1754 ± 103 |
| EV-C1 | A | M-PT | ×1.2 | 5 | 0 | 0 | 0 | 0 | 1728 ± 160 |
| EV-C1 | A | M-SF | ×1.0 | 5 | 0 | 0 | 0 | 0 | 1754 ± 103 |
| EV-C1 | A | M-SF | ×1.2 | 5 | 0 | 0 | 0 | 0 | 1728 ± 160 |
| EV-C1 | B | M-FF | ×1.0 | 5 | 0 | 0 | 0 | 0 | 3568 ± 566 |
| EV-C1 | B | M-FF | ×1.2 | 5 | 0 | 0 | 0 | 0 | 4045 ± 679 |
| EV-C1 | B | M-PT | ×1.0 | 5 | 0 | 0 | 0 | 0 | 3524 ± 500 |
| EV-C1 | B | M-PT | ×1.2 | 5 | 0 | 0 | 0 | 0 | 3819 ± 203 |
| EV-C1 | B | M-SF | ×1.0 | 5 | 0 | 0 | 0 | 0 | 3460 ± 449 |
| EV-C1 | B | M-SF | ×1.2 | 5 | 0 | 0 | 0 | 0 | 3586 ± 143 |
| EV-C1 | C | M-FF | ×1.0 | 5 | 0 | 0 | 0 | 0 | 4761 ± 484 |
| EV-C1 | C | M-FF | ×1.2 | 5 | 0 | 0 | 0 | 0 | 4955 ± 579 |
| EV-C1 | C | M-PT | ×1.0 | 5 | 0 | 0 | 0 | 0 | 4650 ± 165 |
| EV-C1 | C | M-PT | ×1.2 | 5 | 0 | 0 | 0 | 0 | 4675 ± 265 |
| EV-C1 | C | M-SF | ×1.0 | 5 | 0 | 0 | 0 | 0 | 4125 ± 290 |
| EV-C1 | C | M-SF | ×1.2 | 5 | 0 | 0 | 0 | 0 | 4258 ± 185 |
| EV-C2 | A | M-FF | ×1.0 | 5 | 0 | 0 | 0 | 0 | 1639 ± 356 |
| EV-C2 | A | M-PT | ×1.0 | 5 | 0 | 0 | 0 | 0 | 1673 ± 127 |
| EV-C2 | B | M-FF | ×1.0 | 5 | 0 | 0 | 0 | 0 | 3555 ± 566 |
| EV-C2 | B | M-PT | ×1.0 | 5 | 0 | 0 | 0 | 0 | 3506 ± 477 |
| EV-C2 | C | M-FF | ×1.0 | 5 | 0 | 0 | 0 | 0 | 4720 ± 214 |
| EV-C2 | C | M-PT | ×1.0 | 5 | 0 | 0 | 0 | 0 | 4402 ± 233 |

Checker sensitivity (EV-C3): 12/12 corruptions detected: bin closing +1 kg (detected), book +1 kg (detected), duplicate transfer record (detected), observation altered (detected), pit closing set to 1 kg (detected), process losses dropped (detected), received counter +1 kg (detected), reconciliation component altered (detected), route released before the grain finished (detected), suspension removed (flow through unavailable equipment) (detected), transfer moves 5 t more (detected), transfer starts before its lot was tipped (detected).

## Table 3. Equipment and route feasibility

| Check | Configuration | Result | Accepted |
|---|---|---|---|
| Validators (prototype parity + rules) | A (`evidence/configs/site_a.json`) | prototype ok True, rule errors 0 | yes |
| Validators (prototype parity + rules) | B (`evidence/configs/site_b.json`) | prototype ok True, rule errors 0 | yes |
| Validators (prototype parity + rules) | C (`evidence/configs/site_c.json`) | prototype ok True, rule errors 0 | yes |
| Validators (prototype parity + rules) | C-trap (`evidence/configs/site_c_segregation_trap.json`) | prototype ok True, rule errors 0 | yes |
| Alternative route CN1→EN2 while EN1 unavailable 05:00-12:00 (EV-F2a) | C | transfers per run [7, 10, 7, 10, 16] | yes |
| Same, EN1 unavailable 08:00-12:00 (EV-F2b, observation) | C | transfers per run [0, 0, 0, 0, 0] | observation (hold rule I1) |
| Segment, feed-limit, merge, clear-time, outage invariants in all runs | A, B, C, C-trap | audit problems 0 over 217 runs | yes |

## Table 4. Grain segregation

EV-S1: 89 runs on the graded configurations (C, C-trap), audit problems 0.

| EV-S2 (C-trap) policy mapping | Runs | Stalled runs | Stall reason codes | Physical invariants |
|---|---|---|---|---|
| M-FF | 5 | 1 | {'BIN_FULL': 2, 'BIN_INCOMPATIBLE': 5, 'PIT_INCOMPATIBLE': 18, 'PIT_SPACE': 66} | hold |
| M-PT | 5 | 0 | – | hold |
| M-SF | 5 | 1 | {'BIN_INCOMPATIBLE': 1, 'PIT_SPACE': 3, 'QUEUE_ORDER': 81} | hold |

## Table 5. Operating-policy mappings (EV-C1, demand ×1.0, 5 seeds; mean ± 95% CI)

| Site | Mapping | Completed unloading trucks | Unfinished unloading trucks | Mean unloading turnaround (min) | Max overtakes of a truck | Starved trucks (≥120 min) | Stalled runs |
|---|---|---|---|---|---|---|---|
| A | M-FF | 59.0 ± 7.1 | 6.8 ± 11.0 | 117.9 ± 42.7 | 29.6 ± 7.6 | 24.4 ± 9.9 | 0 |
| A | M-PT | 55.0 ± 3.6 | 10.8 ± 9.7 | 149.3 ± 44.2 | 0.0 ± 0.0 | 40.4 ± 15.3 | 0 |
| A | M-SF | 55.0 ± 3.6 | 10.8 ± 9.7 | 149.3 ± 44.2 | 0.0 ± 0.0 | 40.4 ± 15.3 | 0 |
| B | M-FF | 113.6 ± 17.5 | 0.0 ± 0.0 | 60.9 ± 14.0 | 40.8 ± 17.6 | 16.8 ± 8.0 | 0 |
| B | M-PT | 112.2 ± 15.5 | 1.4 ± 3.9 | 78.6 ± 23.2 | 1.2 ± 0.6 | 26.0 ± 19.2 | 0 |
| B | M-SF | 109.4 ± 13.3 | 4.2 ± 9.0 | 92.3 ± 27.6 | 0.0 ± 0.0 | 35.8 ± 19.2 | 0 |
| C | M-FF | 148.6 ± 14.1 | 11.0 ± 10.2 | 75.0 ± 22.5 | 68.6 ± 21.9 | 35.6 ± 13.6 | 0 |
| C | M-PT | 145.2 ± 5.2 | 14.4 ± 15.1 | 103.3 ± 35.9 | 1.0 ± 0.0 | 60.8 ± 51.0 | 0 |
| C | M-SF | 128.0 ± 9.5 | 31.6 ± 16.6 | 141.4 ± 33.7 | 0.0 ± 0.0 | 101.6 ± 24.3 | 0 |

Adversarial policies (EV-P1, demand ×1.0, 5 seeds per cell): physical invariants hold in every run (0 audit problems over 45 runs).

| Site / adversarial policy | Runs | Stalled (operational, reported) | Completed trucks (total) | Unfinished (total) |
|---|---|---|---|---|
| A/ADV-RAND | 5 | 0 | 384 | 14 |
| A/ADV-REV | 5 | 0 | 396 | 2 |
| A/ADV-RHOL | 5 | 0 | 384 | 14 |
| B/ADV-RAND | 5 | 0 | 669 | 3 |
| B/ADV-REV | 5 | 0 | 672 | 0 |
| B/ADV-RHOL | 5 | 0 | 672 | 0 |
| C/ADV-RAND | 5 | 0 | 877 | 27 |
| C/ADV-REV | 5 | 0 | 890 | 14 |
| C/ADV-RHOL | 5 | 0 | 856 | 48 |

Reporting threshold (EV-P2): 9/9 cells give identical decision digests for thresholds 0, 120 and 10 000 min.

## Table 6. Interruptions and stock events (EV-C2, demand ×1.0, 5 seeds per mapping)

| Site | Mapping | Runs | Suspensions | Stock events refused | Losses (t, total) | Observations flagged (tolerance 1 t) | Book − physical at end (t, mean) | Unexplained (kg) | Audit problems |
|---|---|---|---|---|---|---|---|---|---|
| A | M-FF | 5 | 7 | 0 | 30 | 15 | -3146.45 ± 49.75 | 0 | 0 |
| A | M-PT | 5 | 5 | 0 | 30 | 15 | -3160.06 ± 95.65 | 0 | 0 |
| B | M-FF | 5 | 7 | 0 | 30 | 15 | -4521.03 ± 83.21 | 0 | 0 |
| B | M-PT | 5 | 7 | 0 | 30 | 15 | -4543.26 ± 134.81 | 0 | 0 |
| C | M-FF | 5 | 10 | 0 | 30 | 15 | -3197.85 ± 224.85 | 0 | 0 |
| C | M-PT | 5 | 9 | 0 | 30 | 15 | -3039.57 ± 131.43 | 0 | 0 |

## Table 7. Reproducibility and cross-implementation equivalence

| Check | Result | Accepted |
|---|---|---|
| Test suite outcomes | {'passed': 343, 'xfailed': 2} | yes |
| Fresh interpreters, PYTHONHASHSEED 0 and 12345 (EV-R1) | 16/16 identical run digests | yes |
| Full rebuild and comparison of deterministic files | 90 files compared, 0 differing | yes |
| Validation parity with the prototype (EV-X1) | {'passed': 35} | yes |
| Admission decisions vs prototype | identical 8/10; tie-break only 2 (two_shared_opening_grain/tip=fifo, two_shared_opening_grain/tip=feasible); tie-break substitution diagnostics {'two_shared_opening_grain/tip=feasible': 'passed', 'two_shared_opening_grain/tip=fifo': 'passed'} | yes |
| Prototype rules refused, not approximated | 4 scenarios | yes |
| Prototype self-tests | 12/12 | – |
| Features the prototype cannot represent (no equivalence claimed) | grades and grade-specific bins, waiting areas and blocking, scheduled outages, stock events and reconciliation, concurrent feeds on one segment, commodity-pair changeover matrix, continuous hopper drain (prototype: stepwise) | – |

## Figures

- `docs/evidence/figures/fig_completed_by_policy.svg`: completed unloading trucks per day by site and policy mapping (Table 5).
- `docs/evidence/figures/fig_turnaround_by_policy.svg`: mean unloading turnaround by site and policy mapping (Table 5).

Policy mappings: M-FF feasible-first in every queue (engine default); M-PT strict FIFO at the hopper, feasible-first elsewhere (prototype-equivalent); M-SF strict FIFO in every queue including transfers (stress case, not representative practice).


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

