# Evidence-readiness audit for Paper 2 (software-independent, transferable DES methodology for grain silos)

Status: audit for review, 2026-10-23, at commit `10be6d1` (branch `feat/config-validate-port`). **No engine code was
changed.** Added: this document and two synthetic configuration files (`site_c_proposal.json`,
`site_c_segregation_trap.json`).

## 0. Verification, not validation

- Everything below is **software verification**: evidence that the implementation follows its specified rules
  (conservation, feasibility, segregation, policy separation, reproducibility, equivalence with the reference
  prototype).
- **No empirical validation has been performed.** No simulated output has been compared with observations from a
  real silo.
- All configurations are **synthetic**:
  - Sites A and B are the prototype's demonstration configurations;
  - Site C is a proposal written for this audit.

  No customer or operational data is used. Synthetic results must not be reported as observed silo performance.
- Figures quoted as "observed" in this document are outputs of the software under synthetic inputs.

## 1. Inventory

**Tests:** 27 files, 339 collected test cases (`pytest -q --co`). The full suite passes: 337 passed, 2 expected
failures (strict xfail: the known equal-age intake tie-break, §2.7).

**Reference implementation:** `reference/prototype_js/silo_engine_v0.2.0.js`, unchanged (sha256 `b46c2bc7…1628`).
Its 12 self-tests pass (`tools/run_prototype_selftests.ps1`).

**Golden data:**
- `tests/golden/validation_cases.json`: 17 configurations with the prototype's `validate()` output, including the
  valid Sites A and B and 15 invalid cases.
- `tests/golden/policy_equivalence.json`: prototype traces for 14 scenarios.

**Tools:**
- `tools/fairness_report.py` → `docs/audit/FAIRNESS_BASELINE.md`;
- `tools/policy_equivalence.py` (captures prototype traces in headless Edge);
- `tools/scenario_viewer/`;
- `tools/run_prototype_selftests.ps1`.

**Independent checker:** `src/silo_engine/checks/flow_audit.py`. It rebuilds conservation, bins, segments,
outages and stock from the run's records only.

**Specifications:** `docs/DOMAIN_DECISIONS.md`, `docs/QUEUE_POLICY_DESIGN.md`, `docs/MATERIAL_FLOW_AUDIT.md`,
`docs/INTERRUPTED_TRANSFERS.md`, `docs/STOCK_ADJUSTMENTS.md`, `docs/PORT_LOG.md`.

**Commits by build step:**

| Commit | Content |
|---|---|
| `78b75bf` | configuration schema + `validate()` parity |
| `98f4314` | event calendar, time, quantities, scripted arrivals |
| `f61ceb4` | domain rules R1-R7, storage bin |
| `b22515e` | central dispatcher, truck stations |
| `68a7edf` | pits, intake transfers, atomic reservation ledger |
| `84cd926` | changeover matrix, clear time |
| `d0dd950` | concurrent feeds, merge rule |
| `04b359d` | grades |
| `31aef4f` | waiting areas, blocking, deadlock policy |
| `40eb753` | operating hours, unfinished work |
| `8d32541` | seeded random streams, generated arrivals, experiments (incl. the transfer-order fix found by differential comparison) |
| `97bddcd` | fairness, loading |
| `844250d` | starvation diagnostics |
| `cfe94e9` | queue-policy interface, per-site policies |
| `cf3415d` | prototype policy translation + equivalence tests |
| `7412103` | flow audit, lot-to-storage |
| `d7f0aa7` | interrupted transfers |
| `10be6d1` | stock adjustments and reconciliation |

## 2. Evidence by claim

Legend:
- **Strong**: deterministic tests with hand-derived expectations, fault injection, and multi-configuration runs.
- **Partial**: tests exist, but coverage or persisted outputs are missing.
- **Weak**: argued, not demonstrated.

### 2.1 Physical grain conservation: **strong (verification); persisted outputs missing**

- **Tests:**
  - `test_material_flow.py` (19 cases): lot split, competing transfers for a bin's last space, all bins full,
    shared-conveyor clear time, termination mid-transfer and mid-load, transfers stopped at close, the audit
    rejecting 8 corruptions, generated days on A and B;
  - `test_ledger_and_pit.py` (16), `test_storage_bin.py` (20), `test_intake_transfers.py` (9), `test_loading.py`
    (6), `test_interrupted_transfers.py` (19), `test_stock_adjustments.py` (27).
- **Mechanisms:**
  - integer-kg quantities;
  - engine invariants after every event (`ledger.check_invariants`; pit and bin invariants);
  - end-of-run balance: opening + received − dispatched − losses = closing;
  - independent `flow_audit`: global, per pit, per bin, per lot; bins and segments over time.
- **Configurations:** golden Sites A and B; hand-made layouts in the tests; Site C (this audit).
- **Commits:** `68a7edf`, `7412103`, `d7f0aa7`, `10be6d1`.
- **Observed (software outputs, synthetic inputs):**

  | Runs | Result |
  |---|---|
  | 40 generated days (A and B × 2 policies × 2 demand levels × 5 seeds) | 0 audit problems |
  | 20 days with scheduled outages | 28 suspensions, 0 problems |
  | 20 days with stock events | 300 applied, 20 correctly refused (losses on empty bins), unexplained difference 0 kg |
  | Site C (§4), 30 days (2 variants × 3 policy settings × 5 seeds) | 0 audit problems, balance 0 kg in every run |

- **Fault injection:**
  - step 16: 4/4 engine faults and 8/8 record corruptions detected;
  - step 17: 8/8;
  - step 18: 9/9.
- **Missing evidence:**
  - **E-1** The multi-run results above were produced interactively and recorded in docs and commit messages.
    They are **not persisted as re-runnable output files with manifests**.
  - **E-2** No randomised (property-based) configurations; all generated runs use 3 site layouts.
  - **E-3** No multi-day horizons at scale (all large runs are 1 day).
  - **E-4** Grain on conveyors and elevators is a modelled in-transit mass, not located (provisional assumption I2).

### 2.2 Equipment and route feasibility: **strong for the implemented rules**

- **Tests:**
  - `test_ledger_and_pit.py`: all-or-nothing reservation, exclusive and shared segments;
  - `test_concurrent_feeds.py` (9): feed limit, equal sharing, merge rule;
  - `test_changeovers.py` (16): matrix, clear time;
  - `test_staging.py` (8): truck areas, blocking, deadlock prevention;
  - `test_truck_stations.py` (12);
  - `test_interrupted_transfers.py`: no reservation or flow through unavailable equipment;
  - `test_validation_parity.py` (35 cases): 17 golden configurations, including a soybean bin that can't be reached, a
    disconnected hopper, illegal connections, transfer loops and missing capacities;
  - `flow_audit`: segment commodity, feed limit, merge rule, clear time and outage invariants rebuilt from records.
- **Commits:** `78b75bf`, `68a7edf`, `84cd926`, `d0dd950`, `31aef4f`, `d7f0aa7`.
- **Missing evidence:**
  - **E-5** Neither golden site has a choice of intermediate equipment: alternative routes differ only in the
    destination bin (§3). Choosing between equipment is tested only on small hand-made layouts.
  - **E-6** Throughput rates are inputs; no mechanical capacity calculations (out of scope).
  - **E-7** Route enumeration is capped at 400 paths per source (prototype parity); not tested near the cap.

### 2.3 Grain segregation: **partial**

- **Tests:**
  - `test_grades.py` (13): grade-specific bins and pits, grading before tipping, mixing rules;
  - `test_storage_bin.py`: identity, mixing rules, refusals;
  - `test_ledger_and_pit.py`: commodity lock, one commodity per pit;
  - `test_changeovers.py`: commodity-pair changeovers;
  - `test_interrupted_transfers.py`: a held route excludes incompatible grain;
  - `flow_audit`: bin identity over time, one commodity per segment.
- **Commits:** `f61ceb4`, `04b359d`, `84cd926`, `d0dd950`, `d7f0aa7`.
- **Observed:** Site C (graded yellow maize, 30 runs): 0 audit problems.
- **New finding (this audit):** `site_c_segregation_trap.json` (South grade-1 maize has a single bin accepting
  grades 1 and 2):
  - a 719 kg grade-2 residue left by a load blocks grade-1 intake permanently;
  - under strict FIFO on every queue, including intake, this stalls the plant (2 of 5 seeds; reported as a stall
    with `BIN_INCOMPATIBLE`);
  - under feasible-first, or the prototype-equivalent mapping (strict only at the hopper), it does not stall.

  The engine behaves consistently. The point is that segregation risks of this kind are not detected statically.
- **Missing evidence:**
  - **E-8** Neither golden site uses grades; segregation at site scale exists only in Site C (synthetic).
  - **E-9** No static "segregation robustness" check: a grain whose only bins can be captured by another grade.
  - **E-10** Changeover is assumed to clean completely: no residue model on equipment.

### 2.4 Queue policies separated from physical constraints: **strong; one experiment to add**

- **Tests:**
  - `test_queue_policy.py` (22): policies get read-only snapshots and cannot change state; held requests; invalid
    recommendations refused; a custom reversing policy; argument, site and default precedence; head-of-line
    behaviour at parallel hoppers;
  - `test_dispatcher.py` (4);
  - `test_starvation_diagnostics.py` (13): the reporting threshold never changes a decision;
  - `test_policy_equivalence.py` (21).
- **Design:** `docs/QUEUE_POLICY_DESIGN.md`. Physical eligibility, compatibility, routes, capacity and changeovers
  stay in the engine's `attempt` callables and the ledger; a policy only orders requests.
- **Commits:** `b22515e`, `cfe94e9`, `cf3415d`, `844250d`.
- **Observed:** the audit is clean under every policy run so far (2 built-in policies, mapped per-group policies,
  test policies).
- **Missing evidence:**
  - **E-11** No **adversarial-policy experiment**: random or deliberately bad orderings over many seeds and sites,
    showing the physical invariants (audit) always hold. The current implementation supports this without engine
    changes.
  - **E-12** Prototype BATCH is not ported; it is refused, not approximated.

### 2.5 Transferability across configurations: **partial**

- **Evidence:**
  - Everything is configuration-driven: no equipment ids or site names in `src/` (source scan, step 16);
  - Sites A, B and C, and the small hand-made layouts used throughout the tests, run without code changes;
  - validation parity on 17 configurations;
  - per-site policy selection (`queue_policies`).
- **Commits:** `78b75bf`, `cfe94e9`, `7412103`.
- **Missing evidence:**
  - **E-13** Sites A and B are not structurally different enough (§3).
  - **E-14** No automated test that `src/` stays free of site-specific constants (the scan was done once by hand).
  - **E-15** No structural-metrics report generated from configurations (§3 was computed for this audit).
  - **E-16** "A non-programmer can configure" needs the user interface and a user study; it is outside engine
    evidence.

### 2.6 Stochastic reproducibility: **strong on one platform**

- **Tests:** `test_random_and_generation.py` (12): seeded per-entity streams (BLAKE2b + `random.Random`),
  triangular and exponential sampling, generated arrivals; `test_experiments.py` (5): same seeds give identical
  experiments, derived seeds, common random numbers, failed runs excluded.
- **Metadata:** every experiment records the engine version, configuration hash, seeds, replications, policy and
  its source, and assumptions.
- **Commits:** `8d32541`, `cfe94e9`.
- **Observed:**
  - The engine-decision fingerprint (32 runs, sites A and B) is identical across separate processes and under
    `PYTHONHASHSEED` = 0, 1, 4242 and random (this audit).
  - `FAIRNESS_BASELINE.md` regenerated byte-identically at steps 13-18.
- **Missing evidence:**
  - **E-17** Only one platform: Windows 11, CPython 3.14.8, pydantic 2.14.1. No Linux or macOS runs, no other
    Python versions, no CI.
  - **E-18** Dependencies are not pinned: `pyproject.toml` has `pydantic>=2.7`; no lock file.
  - **E-19** The fingerprint is a scratch script, not a versioned tool with a stored reference.

### 2.7 Cross-platform equivalence (prototype JavaScript versus Python): **partial, quantified**

- **Tests:**
  - `test_validation_parity.py`: identical `validate()` output on 17 configurations;
  - `test_jscompat.py` (3);
  - `test_policy_equivalence.py`: every admission decision compared on 10 scenarios. 8 are identical; 2 differ
    only by the equal-age intake tie-break and become identical when the prototype's tie-break is substituted.
    The 4 prototype rules without an equivalent are refused.
  - prototype self-tests 12/12.
- **Commits:** `78b75bf`, `98f4314`, `8d32541`, `cf3415d`.
- **Observed (step 11 differential, Site A ×1.2, 10 runs):** the remaining statistical differences come from
  documented model differences: continuous versus stepwise hopper drain (A3), and explicit changeover rules.
- **Missing evidence:**
  - **E-20** Equivalence covers only the common subset. The prototype has no grades, waiting areas, outages, stock
    events or concurrent feeds.
  - **E-21** The tie-break decision is open.
  - **E-22** The prototype `policies` field is not applied by the Python engine (documented).
  - **E-23** "Cross-platform" in the operating-system sense is E-17.

## 3. Are Sites A and B different enough to show structural transferability?

| Metric | Site A | Site B | Site C (proposal) |
|---|---|---|---|
| Equipment items / connections | 15 / 15 | 23 / 22 | 34 / 39 |
| Hoppers, conveyors, elevators, bins, load points, weighbridges | 2, 4, 1, 4, 1, 1 | 4, 6, 2, 6, 1, 2 | 5, 9, 3, 10, 2, 3 |
| Intake systems | 1 (both hoppers into one elevator) | 2 independent lines (H1+H2, H3+H4), sharing one load point | 2 systems + an interconnect (North can reach South bins) |
| Intake routes / load routes | 8 / 4 | 12 / 6 | 40 / 10 |
| Hopper-bin pairs with a choice of intermediate equipment | 0 / 8 | 0 / 12 | 4 / 36 |
| Intake and load-out share equipment | yes (E1) | no | yes (EN2) |
| Equipment with more than one concurrent feed | none | none | EN1 (2) |
| Graded commodities | none | none | yellow maize (2 grades, grade-specific bins) |
| Compatible bins per commodity | YM 2, WM 2, SB 1 | YM 3, WM 2, SB 2, SF 1 | YM 5, WM 3, SB 2 |
| Changeovers | per equipment (prototype format) | per equipment | commodity-pair matrix incl. grade rules |
| Truck sequence, hours | identical | identical | same steps; different hours |
| Origin | prototype demo generator | same generator | written for this audit |

**Assessment:** **not sufficient on their own.** Site B differs from Site A in useful ways:
- a second independent intake line;
- hoppers merging on a conveyor, not an elevator;
- load-out that does not share intake equipment;
- a fourth commodity.

But both come from the same demonstration generator. They use the same equipment types and truck sequences, with
no grades, no multi-feed equipment and no choice of intermediate equipment. They show **parametric** variation and
one topological change, not structurally different silo designs. A third configuration with route choice,
interconnected systems, grades and several compatible bins is needed (§4).

## 4. Proposed Site C (`docs/evidence/site_c_proposal.json`; configuration only, nothing in the engine)

**Layout:**
- **North complex:**
  - two maize hoppers on CN1, which can feed **either EN1 (2 feeds) or EN2** (choice of intermediate equipment);
  - a soybean hopper on CN2 → EN2;
  - distribution conveyors DN1 and DN2 to six bins: yellow maize grade 1, grade 1/2 and grade 2; two white maize
    bins; one soybean bin;
  - reclaim RN1 → **EN2** → load point LN1 (load-out shares EN2 with intake).
- **South complex:** two hoppers → CS1 → ES1 → DS1 → four bins (yellow maize grade 1, grade 2, white maize,
  soybeans); reclaim RS1 → LS1.
- **Interconnect:** X1 from DN2 to DS1, so North grain can reach South bins by a different route.
- **Changeovers:** commodity-pair matrix with grade rules.
- **Stations:** three weighbridges (in, out, both), sampler, grader.
- **Opening stock:** in five bins.

**Feasibility on the current implementation:**
- Passes the prototype-parity `validate()` and `validate_rules`.
- 15 generated days (3 policy settings × 5 seeds): 0 audit problems, 0 stalls, grain balanced.
- Configuration hash `56712a9a8716`.

**What the runs show (software outputs):**
- The fixed bin preference (same grain first, then route order) leaves **BN3 and BN5 unused**.
- The alternative CN1→EN2 route and the interconnect were used **2 times in 10 days**.

So the structure exists, but without a bin-allocation policy (an unfinished capability) multiple compatible bins
and alternative routes are rarely exercised. Experiments that depend on them must wait for, or explicitly test,
allocation rules.

**Variant** `site_c_segregation_trap.json` (hash `37d5d3dd70dc`): the segregation finding in §2.3, kept as a
negative scenario.

## 5. Which experiments can run now

| Experiment | Runs now? | Depends on |
|---|---|---|
| Conservation audits on A, B, C (incl. outages and stock events) | yes | (E-1 runner for persisted outputs) |
| Feasibility and segregation invariants on A, B, C | yes | — |
| Adversarial-policy invariance (E-11) | yes (test policy objects) | runner only |
| Strict versus feasible-first comparison per site (fairness, throughput) | yes | — |
| Transferability: identical code and validation across A, B, C and the trap variant | yes | structural metrics tool (E-15) |
| Reproducibility: seeds, hash seeds, regeneration | yes on one platform | CI on other platforms (E-17), lock file (E-18) |
| JS versus Python admission equivalence | yes (10 scenarios) | tie-break decision (E-21) for full identity |
| Effect of using alternative routes and multiple compatible bins | **no** (only by fixed preference) | **bin-allocation policy** |
| Capacity from mechanical parameters (belt speed, bucket volume) | **no** | **mechanical calculations** |
| Breakdown statistics, repair times | **no** | random outages (deferred) |
| Drying, shrink formulas, by-products, regrading | **no** | deferred (step 18 scope) |
| Multi-bin loads, bin-to-bin transfers | **no** | not implemented |
| **Empirical validation** against a real silo | **no** | site data, observed KPIs, calibration, independent review |

## 6. Reproducible test matrix (proposed; to be implemented as `tools/evidence_run.py` after review)

Every run writes `evidence/out/<ID>/`:
- `manifest.json`: git commit, engine version, Python and dependency versions, OS, configuration file and hash,
  seeds, policy and its source, `PYTHONHASHSEED`, command line;
- `results.json`: the figures below;
- `audit.json`: the flow audit;
- `fingerprint.txt`: the engine-decision hash.

Acceptance is checked by the runner and by a pytest wrapper.

| ID | Claim | Deterministic inputs | Expected outcome | Acceptance criterion |
|---|---|---|---|---|
| EV-C1 | Conservation | A, B, C × {strict, feasible, prototype mapping} × seeds 0-9 × demand {1.0, 1.2} | Audit clean | 0 audit problems; balance 0 kg in every run; unexplained 0 kg |
| EV-C2 | Conservation under disturbance | EV-C1 subset + 3 scheduled outages + 16 stock events per site | Audit clean, suspensions recorded | as EV-C1; every suspension ends in a resume or at end of run |
| EV-C3 | Checker sensitivity | Corrupted records (the step 16-18 corruption sets) | Every corruption detected | 100% detection |
| EV-F1 | Feasibility | The 17 golden validation cases + Site C + trap | Same messages as the prototype; C and trap valid | exact message equality (parity); no errors for C and trap |
| EV-F2 | Route choice | Site C with EN1 unavailable 08:00-12:00 | CN1 lots routed via EN2 | ≥ 1 transfer on CN1→EN2 during the outage; 0 flow through EN1 |
| EV-S1 | Segregation | Site C, all EV-C1 runs | No mixed bin or segment | 0 identity or segment problems |
| EV-S2 | Segregation risk | Trap variant × {strict, feasible} × seeds 0-4 | Strict FIFO on all queues stalls in some seeds with `BIN_INCOMPATIBLE`; feasible does not | stall reason recorded; mass balance holds at the stall |
| EV-P1 | Policy separation | A, B, C × {strict, feasible, reverse, random-permutation (seeded)} × seeds 0-9 | Physical invariants independent of policy | 0 audit problems for every policy |
| EV-P2 | Threshold independence | A, B, C × starvation thresholds {0, 120, 10 000} | Identical decisions | identical fingerprints |
| EV-T1 | Transferability | A, B, C, trap; no code changes | All validate and run | zero edits to `src/` between runs (commit unchanged); structural metrics table generated |
| EV-T2 | No site constants | `src/` scan | No equipment ids or site names | 0 matches |
| EV-R1 | Reproducibility | EV-C1 subset, run twice, under `PYTHONHASHSEED` {0, random} | Identical outputs | byte-identical `results.json` and fingerprints |
| EV-R2 | Platform independence | EV-R1 on Linux and Windows, Python 3.12 and 3.14 | Identical outputs | identical fingerprints (or documented differences) |
| EV-X1 | JS versus Python | 14 policy scenarios + 17 validation cases | 8 identical, 2 tie-break, 4 refused; validation identical | as stated; no new differences |
| EV-X2 | Statistical comparison on the common subset | Site A ×{1.0, 1.2}, 20 runs each engine | Differences explained by A3 only | report with confidence intervals; listed causes |

## 7. Implementation gaps (for review before any code change)

**Evidence infrastructure** (no engine change):
1. `tools/evidence_run.py` with manifests and persisted outputs; pytest wrapper for acceptance (E-1, E-19).
2. Structural-metrics tool for configurations (E-15).
3. Site-constant scan as a test (E-14).
4. Adversarial and random-permutation policy objects for EV-P1 (E-11).
5. Lock file and CI on Linux and Windows with two Python versions (E-17, E-18).
6. Promote Site C and the trap variant to versioned evidence configurations, once reviewed.

**Engine or model decisions** (need your decision; not started):

7. **Static segregation-robustness warning** (E-9): flag a grain whose only bins can be captured by another grade.
8. **Bin-allocation policy** (needed before claims about alternative routes or multiple compatible bins).
9. **Equal-age tie-break** decision (E-21); prototype `policies` field (E-22).
10. **Strict FIFO on intake transfers:** the prototype never applies it, and it causes the trap stall. Paper
    experiments should state the policy per queue; consider recommending the prototype-equivalent mapping as the
    "strict FIFO" baseline.
11. **Performance:** feasible-first is about 5× slower than strict FIFO on Site C (about 2.9 s versus about 14 s
    per 5 days). It is acceptable now, but limits large experiment designs.

**Empirical validation** (outside software verification):

12. Observed site data, KPI definitions, calibration and an independent operational and technical review. None
    exist yet.
