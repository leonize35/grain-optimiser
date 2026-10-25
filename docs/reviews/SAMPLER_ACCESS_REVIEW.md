# Review response: sampler access, physical queue blocking and sampler location

Date: 2026-10-25. Responds to the critical review of the sampler-access extension. This is a gap assessment against
the actual code, configurations and evidence: no features were added for it.

**Preserved unchanged:**
- `paper2-v1` (commit `6345377`);
- `paper2-ext-sampling-v1` (commit `3c54428`, built at `deb1c2b`).

**Verdict (agreed with the review):**
- **Suitable** as a verified experimental modelling extension.
- **Not suitable** for site-specific operational recommendations. No operating rule in it is verified with a silo,
  no output is validated against observations, and labour was not represented in the experiment.

## 1. Implementation status against the design (`docs/SAMPLER_ACCESS_DESIGN.md`)

| Proposed (§3-§6) | Status | Evidence |
|---|---|---|
| Per-truck sampling requirement (arrival data or share) | Implemented | `inputs/scripted.py:47`, `inputs/generated.py:49`, `sim/truck_flow.py:834` |
| Ordered single-file areas, front-only exit | Implemented | `TruckArea.single_file`; `_guarded` in `sim/truck_flow.py` |
| Declared bypasses | Implemented **without capacity** | `config/schema.py:253` (`TruckBypass`: activity, from, to, for). §3's example shows `"capacity": 2`; the implemented semantics (bypass holds no trucks) are only in §8 O3. **Inconsistency, now recorded here.** |
| Drive-through of a sampler bay (`pass_through`) | Implemented | `Equipment.pass_through`; step `pass` |
| Sampler at weighbridge bays (`located_at`, `located_lanes`) | Implemented | `_try_colocated_sample`, `_weigh_on_held_bay` |
| `sampling_overlaps_weighing` | **Not implemented** | §8 O6 |
| Per-truck blocked time, area occupancy, station utilisation | Implemented (blocked behind, time-weighted occupancy); utilisation computed in the evidence tool | `truck_access`, `area_occupancy`; `tools/evidence/sampling_ext.py` |
| Audit invariants | Implemented | `checks/flow_audit.py` `_audit_access`; 5 sensitivity tests |
| Experiment factor demand {×1.0, ×1.2} (§6) | **Not run.** Only ×1.0. | `tools/evidence/sampling_ext.py:101` (`demand_factor=1.0`); the manifest has no demand factor. **Inconsistency: the design lists ×1.2, the package has none.** |
| Experiment unloading sequence | **Changed from the base sites** | `sampling_ext.py:70` sets `sample, weigh_in, grade, tip, weigh_out`. All three base configurations (Sites A, C, S) have `sample, grade, weigh_in, ...`, so trucks wait for the grading result *before* weighing in. The extension moved that wait after weigh-in (O8). |
| Site A weighbridge | **Changed** | `sampling_ext.py:64`: Site A's weighbridge gets 2 bays in every layout (the base Site A has 1). |
| Reproducibility | Confirmed | Independent rebuild 105/105 files identical (`evidence/out/paper2-ext-sampling-v1-reproduction-check.json`); `paper2-v1` reproduces unchanged under the extended engine (84/84 files). |

Consequence: the extension's "Site A" and "Site C" are **modified variants**, with a moved grading wait and, on
Site A, a second weighbridge bay. They are not the configured sites, and must be labelled that way in any write-up.

## 2. Issue register

| # | Current behaviour | Why it matters | Evidence | Potential effect on results | Recommended correction | Needs operational confirmation? | Minimum tests before acceptance |
|---|---|---|---|---|---|---|---|
| 1 | **No labour in the experiment.** Sampling units, weighbridge bays and graders are capacity counts; staff are merged into them. | One person may do several tasks; parallel equipment may not be staffable. | `paper2-ext-sampling-v1` was built before any labour support; Equipment `cap` = "trucks served at once". | S1-S4 may overstate parallelism (e.g. sampling and weighing at once). Turnaround differences could change size or sign under shared staff. | Use the staffing framework (§6) with **verified** pools and labour requirements; rerun S1-S4 as a new versioned package. | **Yes** (M1-M4) | The staffing hand traces (done); then S1-S4 with a shared operator hand-traced before the stochastic runs. |
| 2 | **No sampling means no grading.** Trucks not needing sampling skip `sample` **and** `grade`. | A truck may need grading or documentation without new sampling. | `sim/truck_flow.py:796` | Unsampled trucks gain the whole grading wait; the bypass benefit and class differences may be overstated. | Separate `requires_grading` from `requires_sampling` (default: grading needed iff sampled, as now). | **Yes** (new question G1) | Hand trace: an unsampled truck that still waits for grading; a sampled truck graded without delay. |
| 3 | **The requirement is known at arrival.** | A bypass at the gate needs the decision before the truck joins the queue. | `inputs/generated.py:49`; scripted `requires_sampling` | S2's gate bypass may be infeasible if the decision is made later (registration, inspection). | Add `requirement_known_at`: the area or step after which the requirement is known; bypasses only from later places. | **Yes** (O1 extended) | Hand trace: decision at the weighbridge gives no gate bypass. |
| 4 | **Single-file approach** with exit only from the front, where configured. | Real yards may allow manoeuvring. Single-file should apply only where passing is physically impossible. | `truck_areas[].single_file: true` in all S1-S4 approach areas | Blocking may be overestimated. | Use single-file only on verified segments; keep the default unordered. | **Yes** (O2) | Unchanged logic; a sensitivity run with `single_file: false`. |
| 5 | **Bypass lanes hold no trucks**; the S2 bypass leads to the weighbridge; capacity is not modelled. | A real bypass has a length, a safety layout and an access point. | `TruckBypass` has no capacity; design §3 vs §8 inconsistency | Bypass benefits (4.4 and 14.1 min on Site S) are upper bounds for a free, instant, unlimited lane. | Optional bypass capacity (a finite area) and travel time; correct design §3. | **Yes** (O3) | Hand trace with a 1-truck bypass lane. |
| 6 | **Zero travel time.** | Layouts differ in distances. A bypass can add driving time while removing queueing. | No travel field in the engine (O9) | Layout comparisons exclude travel; bypass gains are upper bounds. | Optional travel time per path element; sensitivity runs (e.g. 0 / 1 / 3 min). | **Yes** (O9) | Hand trace with travel time; equivalence at 0. |
| 7 | **Grading wait after weigh-in** in the experiment (base sites wait before weigh-in); the grader is a capacity count. | Where the result is awaited decides whether trucks block bays. Lab staff may be shared. | `sampling_ext.py:70`; grader `cap` | Results describe a different grading procedure from the base sites. Grading congestion is not attributable to staff or equipment. | Make grading location and grading staff explicit; separate "grading processing" from "waiting for the result". | **Yes** (O8, G2-G4) | Hand traces for each grading location, and for one lab technician with two benches. |
| 8 | **"Sampler location" also changes weighbridge capacity.** In S3/S4 sampling occupies a weighbridge bay, and the probe is at 1 of 2 bays. In S1/S2 sampling has its own position and both bays weigh. | The factor is a sampling configuration, not location alone. | `sampling_ext.py:84` (`located_lanes: [0]`); Site S `WB1 cap 2` | The location effect (+15 min for sampled trucks, +0.24 bay occupancy) includes a capacity change and a probe asymmetry. | Report the factor as **"sampling configuration"**. Add arms that separate the effects (probe at both bays; S1/S2 with one weighbridge bay). | Partly (O4: number and placement of probes) | Hand trace: a probe at both bays. |
| 9 | **Demand ×1.2 not run.** | Bypass and configuration effects may grow with arrival intensity. | `sampling_ext.py:101`; design §6 lists ×1.2 | Conclusions hold only at ×1.0. | Run demand levels (once verified as average, busy and peak, M8) in a new package. | **Yes** (M8, to define levels) | None beyond existing; the runner already supports `demand_factor`. |
| 10 | **Site C throughput interpretation.** The earlier report used the correlation between the change in completed trucks and the change in trucks left waiting at a hopper (−0.99 to −1.00). | That correlation is **mechanical**: arrivals are identical across layouts, so completed + unfinished is constant per seed. | Evidence §5 below | The earlier claim ("a downstream effect") was argued from a tautology. | **Retracted and replaced** by the trace evidence in §5. | No | Done (§5). |
| 11 | **The base-site modifications** (Site A second weighbridge bay; sequence change) are not prominent in the report. | Readers may take "Site A" for the configured Site A. | `sampling_ext.py:64,70` | Mislabelling. | Label as "Site A variant" and "Site C variant" everywhere; this note. | No | — |
| 12 | **Drive-through time 0.3-1.0 min** is invented for the experiment. | It decides sampler-bay occupancy by unsampled trucks in S1. | `sampling_ext.py:69` | It affects S1 versus S2 only through pass-through occupancy. | Treat as a sensitivity parameter until measured. | **Yes** (O7) | Sensitivity runs at 0 / 0.5 / 2 min. |

## 3. Classification of O1-O11

**Categories:**
- **V:** verified with site evidence.
- **P:** supported by existing project data (prototype or base configurations).
- **R:** provisional but reasonable.
- **U:** unsupported, needs confirmation.

**No assumption is V.**

| Q | Assumption as implemented | Class | Note |
|---|---|---|---|
| O1 | Requirement per truck, known at arrival; experiment shares 0.3, 0.7, 1.0 | **U** (the default "all sampled" is **P**: the prototype and base sites sample every unloading truck) | Shares are experimental factors, not site data. When the decision is made is unknown (issue 3). |
| O2 | Single-file approach where configured | **U** | Issue 4 |
| O3 | Declared bypasses; the lane holds no trucks | **U** | Issue 5 |
| O4 | Separate upstream sampler (default); probe at one weighbridge bay in S3/S4 | Default **P** (prototype and Sites A, B, C configure a separate sampler); co-location **U** | Issue 8 |
| O5 | Holding space of 2 places (0 and 5 tested on Site S) | **U** | — |
| O6 | Sampling, then weighing, at a probe bay; no overlap | **R** | — |
| O7 | Drive-through 0.3-1.0 min | **U** (invented range) | Issue 12 |
| O8 | Grading result awaited in the yard after weigh-in | **U, and it conflicts with project data**: the base sequences await it before weigh-in | Issue 7 |
| O9 | Zero travel time | **R** for verification; **U** for layout comparison | Issue 6 |
| O10 | No staff discretion over order | **U** | — |
| O11 | No priority for either class | **R** | — |

**New questions raised by the review:**
- **G1** Can a truck need grading without being sampled at this silo (existing results, documentation)?
- **G2** Is grading done immediately after sampling, and can a truck weigh in before its result?
- **G3** Where does a truck wait for its result (bay, approach, holding area, yard)?
- **G4** How many samples can be graded at once, and is grading limited by benches, staff or both?

## 4. Experimental validity

- **Common random numbers:** arrivals, the sampling requirement (its own per-truck stream) and service draws (per
  truck and step) are identical across layouts within a seed.
- **Changes between layouts:** only the declared layout fields change. The build asserts this
  (`layout_differences.json`).
- **What S1-S4 isolate:**
  - **Bypass effect** (S2 vs S1, S4 vs S3): isolated, given the provisional bypass semantics.
  - **"Location" effect:** a **sampling-configuration** effect that includes weighbridge-bay occupancy and the probe
    asymmetry (issue 8).
  - **Holding effect** (Site S only): isolated.
- **Factors that may materially affect the conclusions:**
  - no labour (issue 1);
  - the coupling of sampling and grading (issue 2);
  - zero travel time and the unlimited, instant bypass (issues 5 and 6);
  - the moved grading wait (issue 7);
  - one demand level (issue 9).
- **Site S** has no downstream constraint by design: it isolates access effects but represents no real site.
  Its results must stay separate from any site-specific statement.
- **Turnaround versus throughput (Site S):** access layouts changed turnaround, but **throughput was identical**
  (131.2 trucks in every layout). These are different operational benefits; the extension shows only the first.

## 5. Site C throughput: corrected interpretation, from the event trace

**What the earlier report claimed:** a correlation of −0.99 to −1.00 between Δ(completed) and Δ(trucks left waiting
at a hopper) "shows" a downstream effect.

**Why that is not evidence:** with identical arrivals, completed + unfinished = arrivals, which is constant per
seed. Most unfinished trucks wait at the hoppers, so the correlation follows from the bookkeeping.

**Trace evidence** (Site C variant, share 0.7, seed 0; hourly snapshot of waiting requests; runs regenerated from the
package configurations, no package file changed):

| | S1 | S4 |
|---|---|---|
| Trucks waiting to tip, 09:00 / 14:00 / 18:00 | 7 / 27 / 41 | 4 / 10 / 18 |
| Dominant tipping wait reasons | pit space and pit incompatibility (e.g. 126 and 82 reason entries at 18:00) | the same reasons, about half as often |
| Route changeovers (conveyors, elevators) | **326** | **214** |
| Completed unloading trucks | 132 | 158 |

**Across 20 seeds** (S4 − S1, share 0.7):
- mean change in completed trucks **+2.2**, with the **sign varying by seed** (from −21 to +26);
- mean change in changeovers +21.8;
- correlation between the change in completed trucks and the change in changeovers **−0.47**.

**Interpretation:**
- On the Site C variant, the access layout changes the **order in which commodities reach the pits**. That changes
  pit compatibility, route changeovers and therefore intake capacity, **in either direction depending on the seed**.
- This is a sensitivity of the downstream grain system to arrival order. It is **not** a consistent access effect:
  the paired throughput differences are descriptive (§6).
- The trace shows the mechanism for one seed. The −0.47 cross-seed association is consistent with it, but is still
  a correlation, not a causal test.
- A causal test would hold the commodity order at the pits fixed (for example by replaying the hopper arrival
  sequence) while changing only access. It is listed as optional future work.

## 6. Statistical evidence (as computed by `tools/evidence/sampling_ext.py`)

- **Pairing:** by seed (common random numbers), n = 20 pairs per comparison.
- **Confidence intervals:** 95% Student *t*, df = 19.
- **Two-sided p:** Student *t* by numerical integration (`tools/evidence/export.py:47`, checked against tabled
  values).
- **Multiplicity:** Holm adjustment over all 406 tested comparisons in the package. Comparisons with zero variance
  are labelled, not tested.
- **Seeds:** `derived_seed(base, 'replication', i)` (BLAKE2b, 32-bit). Per-entity streams are keyed by truck and
  step. Replications are independent pseudo-random streams; there is no shared state between runs.
- **Precision:**

  | Comparison | Effect vs 95% CI half-width | Assessment |
  |---|---|---|
  | Site S turnaround, bypass | 4.4 vs about 0.8 min; 14.1 vs about 6.2 min | adequate |
  | Site C throughput | 2-5 trucks vs about 5 trucks | inadequate (and confounded, §5) |

  No power analysis was done. Replication counts for future packages should be set from these half-widths.
- **Categories kept apart in the package:**
  - Holm-supported;
  - nominal only (the CI excludes 0 but the difference fails after Holm);
  - descriptive;
  - no difference in any pair;
  - not applicable (no trucks of a class at share 1.0).

## 7. Operator staffing: current state

- **What exists:** following the instruction of 2026-10-25, a staffing **framework** was implemented
  (`docs/OPERATOR_STAFFING_DESIGN.md` §9):
  - operator pools, labour requirements reserved atomically with equipment, staffing scenarios, optional crew-time
    factors, labour utilisation and waiting attribution, audit checks;
  - 16 hand-traced tests;
  - defaults change nothing (fingerprint and configuration hashes identical).
- **What it isn't:** **not yet committed** at the time of this review. Reproduction of both evidence packages under
  it is running.
- **Not used by any evidence package.** No operator counts or policies are entered for any site; all test pools
  are marked unverified.
- **This review recommends** no staffing experiment until M1-M10 and G1-G4 are answered (§3).

## 8. Recommended order of work

1. **Operational validation with the silo manager:**
   - M1-M10 (staffing);
   - O1-O11 (access), including when the sampling requirement is known;
   - G1-G4 (grading).

   Record answers as verified inputs with their source and date.
2. **Close modelling gaps that the answers show to matter.** Candidates:
   - separate grading requirement (issue 2);
   - decision point for the requirement (issue 3);
   - bypass capacity and travel time (issues 5 and 6);
   - explicit grading location and staff (issue 7);
   - arms separating probe placement from bay capacity (issue 8).

   Each needs hand traces first.
3. **New versioned packages** (none overwritten):
   - S1-S4 with verified staffing;
   - demand levels as verified;
   - travel-time and single-file sensitivity;
   - throughput reported separately from turnaround.
4. **Validation:** compare simulated turnaround, waiting and throughput with observed site data that was not used to
   calibrate. Until then, all results are labelled scenario-based or exploratory.

## 9. Research-integrity statement

- **Not invented:** no site data, staffing levels, procedures or validation evidence.
- **Not changed:** no baseline configuration, published evidence package or committed result was changed for this
  review.
- **Classification:**
  - software verification: tests, audit, reproduction;
  - operational validation: none yet;
  - experimental findings: synthetic, exploratory.

  These are reported separately.
- **Corrected:** the Site C interpretation in `paper2-ext-sampling-v1/report/README.md` and in
  `docs/SAMPLER_ACCESS_DESIGN.md` §9 is superseded by §5 of this review. The frozen package itself is not edited.
