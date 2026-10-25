# Ventersdorp Configuration Gap Analysis (no implementation)

Status: **analysis only**. No engine code, configuration, baseline or evidence package was changed. The prototype
(`reference/prototype_js/`), its golden cases (`tests/golden/validation_cases.json`) and the evidence packages
(`evidence/out/paper2-v1/`, `evidence/out/paper2-ext-sampling-v1/`) are untouched. No prototype or Paper 2 demonstration
result is a Ventersdorp result.

## 0. Sources and evidence labels

| Label | Meaning | What was actually available |
|---|---|---|
| **F** | Confirmed fact, stated by the user | The Ventersdorp description in the request (two silos, shared sampler and weighbridges, staffing rules) |
| **P** | Interpretation of the Ventersdorp PLC diagrams | **None possible.** No PLC diagram or site photograph was attached to the request or found in the project or Desktop folders. Every P item below is a question, not a reading |
| **O** | From the user's master's operational-flow diagram `Masters_2026_2027/Simulation - 13 Oct/All diagram used-OFD.drawio.png` | Labelled "SiloX". It is a flow diagram of a research model, not a PLC diagram, and it is **not confirmed to show either Ventersdorp facility**. It is used here only to suggest questions |
| **E** | Engine fact, verified in the code on `feat/config-validate-port` (9fbb44d) | `src/silo_engine/config/schema.py`, `rules_validation.py`, `sim/truck_flow.py` |
| **A** | Assumption that needs the user's confirmation | — |

`SiloX_SAP_IAT_data.xlsx` (SAP data) was **not opened**, and no SAP, registration or personal data is used here.

## 1. Existing model

There is no Ventersdorp configuration. Every configuration in the repository is a prototype demonstration or a
synthetic case:

| Config | Origin | Weighbridges | Sampling | Grain system |
|---|---|---|---|---|
| Site A "Kareepan Silo" | Prototype demo | WB1, cap 1, `moves: both` | S1 cap 1 + G1 grader cap 2 | 2 hoppers → 1 elevator → 4 bins; 1 load point |
| Site B "Rietvlei Depot" | Prototype demo | WB1 `in` + WB2 `out` | S1 cap 2 + G1 cap 3 | 4 hoppers, 2 lines (E1, E2) → 6 bins |
| Site C | Synthetic proposal | WB1 `in`, WB2 `out`, WB3 `both` | S1 cap 2 + G1 cap 3 | Two systems (N: 3 hoppers, 6 bins; S: 2 hoppers, 4 bins) joined by interconnect X1 |
| Site S, trap variant | Synthetic, controlled | — | — | Test structures only |

The unload sequence in all of them is `sample → grade → weigh_in → tip → weigh_out`. All capacities and times are
demonstration values.

## 2. Gap table

| # | Component | Existing model | Actual Ventersdorp | Required change | Verification status |
|---|---|---|---|---|---|
| 1 | Site structure | Separate demo sites; Site C (synthetic) has two systems in one config | **F:** one integrated site, two interconnected subsystems (Silo A, Silo B) | New config `ventersdorp` (v1) with one equipment graph tagged A and B. No engine change: one `SiteConfig` already holds several hopper→bin systems (as Site C does) | E: supported. Ventersdorp topology not yet known |
| 2 | Sampling station | One sampler per site (cap 1 or 2) | **F:** one shared station for both silos. **O:** "Sampler (2)" | One `sampler` shared by A and B. **A:** is "(2)" two probes (equipment `cap: 2`) or one probe with two people (cap 1 plus an operator pool of 2)? | F for sharing; capacity unconfirmed |
| 3 | Incoming weighbridge | Site A: one `both` bridge; Site B/C: `in` + `out` | **F:** one dedicated incoming bridge, never used for weigh-out | WB_IN with `moves: in`. No engine change: `weigh_in` only uses `in`/`both` bridges (`truck_flow.py:108`) | E: supported. Needs a Ventersdorp test proving no weigh-out on WB_IN |
| 4 | Outgoing weighbridge | as above | **F:** one dedicated outgoing bridge | WB_OUT with `moves: out`, and **no `both` bridge** in the config | E: supported; same test |
| 5 | Lanes per weighbridge | `cap` = trucks at once | Unknown. **O:** in 1, out 1 | **A:** one truck on each bridge at a time? | A |
| 6 | Grading | Separate `grader` (cap 2–3) after sampling | Not stated. **O:** "Grader (1)", grading after sampling, results returned before weigh-in | **A:** is grading a separate truck stop, or done in the lab while the truck waits or moves on? This decides whether `grade` is in the truck sequence (the sampler-access design's O1–O3 questions) | A |
| 7 | Truck sequence (unload) | `sample → grade → weigh_in → tip → weigh_out` | Not stated. **O:** sample → (grading) → weigh-in → hopper → weigh-out | **A:** confirm the order for both silos; is it the same for A and B? | A |
| 8 | Truck sequence (load/dispatch) | `weigh_in → load → weigh_out` | Not stated. **O:** dispatch trucks also go to a sampling queue | **A:** are outgoing loads sampled? `sample` is a valid step in any sequence, but a dispatch-sampling test is needed | A; engine check needed |
| 9 | Weigh-only trucks | `weigh: [weigh_in]` | Not stated. **O:** "Act 3 – just weigh" exists | **A:** which bridge do weigh-only trucks use (in, out, or both)? With dedicated bridges this must be explicit | A |
| 10 | Truck choice of silo (A or B) | No silo attribute on a truck; the hopper is chosen by a feasible grain route over the whole graph | Unknown | **A:** how is a truck sent to A or B? (a) by commodity and bin availability: no engine change, encode in bin `commodities`/`accepts` and connectivity; (b) by an instruction or preference (e.g. fill A first, B only for some grades): **engine change** (a routing-preference policy) | A; decides whether engine work is needed |
| 11 | Truck paths and waiting areas | `truck_paths` per activity (unload/load/weigh), not per destination | Unknown; the two silos are separate facilities | **A:** after weigh-in, do A-bound and B-bound trucks use different roads or queue areas? If so, **engine change**: path per destination (hopper group) | A; engine gap if yes |
| 12 | Hoppers / unloading positions per silo | Demo counts | **P:** from PLC, not received | Need, per silo: hopper count, pit capacity (t), tip time, intake rate (t/h), tip admission rule | Not available |
| 13 | Combined load/unload position | Hoppers (tipping) and load points (loading) are separate equipment | **O:** "1 unload hopper and one combined load and unload" | **A:** if a single bay serves both tipping and loading trucks, the engine has no shared truck bay across `hopper` and `loadpoint`: **engine change** | E: gap confirmed in schema; applicability A |
| 14 | Conveyors and elevators per silo | `rate` t/h, `clear_minutes`, changeover | **P:** not received. **O:** 270 t/h; conveyor 2.3 m/s × 40 m; elevator 1.8 m/s × 40 m; conveyor above bins 2.3 m/s × 128 m; scenario 540 t/h | Map each to `rate` and `clear_minutes` (length ÷ speed: about 0.29, 0.37 and 0.93 min). **A:** rated versus actual throughput; are speeds and lengths Ventersdorp values? | O values unconfirmed for Ventersdorp |
| 15 | Bins per silo | Demo bins | **P:** not received. **O:** 8 bins × 7 000 t (WM1–3, YM1, YM1G, YM2, GH1, FH) plus a temporary bin of 500/1 000 t | Need, per silo: bin ids, capacity (t), allowed commodities and grades, opening stock | Not available |
| 16 | Shared versus independent grain equipment | Site C: separate N/S lines plus one interconnect | **F:** subsystems are interconnected. **P:** details not received | **A:** which conveyors or elevators are shared between A and B, and in which direction can grain move? Model only the connections you confirm; no implicit links | Interconnect exists (F); its form is unknown |
| 17 | Internal transfers A↔B (bin to bin) | **Not supported:** grain moves only on truck activities (unload, load) | Unknown | **A:** do bin-to-bin transfers happen during receiving hours and compete for shared conveyors? If yes, **engine change** (scheduled transfer jobs). If they happen outside receiving or are rare, document them as out of scope | E: gap confirmed |
| 18 | Changeover rules | Matrix or per-equipment minutes | **O:** 0 min base, 5 min scenario | **A:** Ventersdorp changeover times per conveyor or elevator and commodity pair | A |
| 19 | Staffing: pools | Framework exists (9fbb44d); no site data | **F:** variable per activity and shift; separate from equipment; helps only where labour-constrained. **O:** Admin (1) on both weighbridges, Hopper operator (1), Grader (1), Sampler (2) | Config only, if the pools are site-wide. All `verified: false` until confirmed | E: framework verified by hand-traced tests; Ventersdorp data A |
| 20 | Staffing: per-silo operators | `labour` is keyed by **task step**, not by equipment or silo | Unknown | **A:** does each silo have its own hopper operator? If yes, **engine change**: a labour requirement scoped to equipment or subsystem (e.g. `tip` at A hoppers → pool A). One operator covering both silos would also need walking time, which is not modelled | E: gap confirmed |
| 21 | Labour on load step | Labour allowed for sample, grade, weigh_in, weigh_out, tip only (`rules_validation.py:375`) | Unknown | **A:** is loading labour-constrained? If yes, small engine change | E: gap confirmed |
| 22 | Hours and demand | Demo | **O:** 07:00–19:00, arrivals until 18:00; IAT distributions; 30 replications | Arrival data must come from a permitted source. SAP-derived inputs are **not** to be committed | Not used |
| 23 | Data handling | Repo `leonize35/grain-optimiser` is public | Senwes site data | **Decision needed:** store the Ventersdorp config outside the public repo (local or private), or commit an anonymised version only with permission | Decision needed |

## 3. Answers to the five verification questions

**3.1 Correct assumptions in the existing model (they carry over):**

- the engine handles one integrated site with several hopper→bin systems competing for site-wide sampler and weighbridges (Site C);
- directional weighbridges exist and are enforced (`moves: in | out`);
- atomic whole-route reservation and feasible-first dispatch apply unchanged;
- labour is separate from equipment, so adding operators changes nothing unless the step is labour-constrained (tests `test_a_second_operator_at_a_single_probe_gives_no_gain_without_a_crew_time_rule`, `test_a_scenario_changes_staffing_without_changing_equipment`).

**3.2 Contradictions with Ventersdorp:**

- Site A's single `both` weighbridge contradicts the dedicated in/out bridges (F). Site A must not be used as a Ventersdorp proxy.
- Site C's third `both` bridge (WB3) contradicts "not interchangeable". Site C is not a Ventersdorp model either.
- All demo sites use a grader as a separate truck station. Whether that holds is unconfirmed (row 6).

**3.3 Missing resources and routes:**

- the PLC-level equipment lists for A and B (rows 12–16);
- the A↔B interconnect;
- a possible combined load/unload bay (row 13);
- a possible temporary bin (row 15);
- truck road layout and queue areas (row 11).

**3.4 Operating rules needing confirmation:** rows 2, 5–11, 13, 16–18, 20–21. The list is in section 5.

**3.5 Simulation logic that may need to change** (each only if the answer requires it):

| Gap | Triggered by | Size |
|---|---|---|
| G-V1 routing preference A/B | row 10 (b) | medium |
| G-V2 truck path per destination | row 11 | medium |
| G-V3 shared tip/load bay | row 13 | medium |
| G-V4 bin-to-bin transfer jobs | row 17 | large |
| G-V5 labour scoped to equipment/subsystem | row 20 | small–medium |
| G-V6 labour on `load` | row 21 | small |

If the answers are commodity-based routing, one road, separate hopper and load bays, no in-hours transfers and site-wide crews, **no engine change is needed**: Ventersdorp becomes a configuration only.

## 4. Minimum changes proposed (in order, each test-first)

1. **Data-handling decision** (row 23) before any Ventersdorp file is created.
2. **Configuration `ventersdorp` v1** with only confirmed items:
   - one sampler (shared);
   - WB_IN `moves: in`, WB_OUT `moves: out`, no `both` bridge;
   - the A and B equipment graphs exactly as you confirm them from the PLC diagrams, with ids prefixed `A_` and `B_` (naming only, no logic depends on it);
   - only the confirmed interconnects;
   - unconfirmed numbers marked provisional in an assumptions list that every result reports.
3. **Ventersdorp structure tests**, hand-traced:
   - weigh-in never on WB_OUT and weigh-out never on WB_IN;
   - A-bound and B-bound trucks queue for the same sampler and bridges;
   - a route from each hopper reaches only the bins the PLC connectivity allows;
   - no route uses an unconfirmed link.
4. **Engine gaps G-V1 to G-V6**, only those your answers trigger, one at a time (failing test, minimal change, invariants, review).
5. **Staffing pools**, all `verified: false` until you confirm them. No staffing, bottleneck or capacity experiment until M1–M10, G1–G4 and this document's open items are closed.
6. **Verification only.** Validation against Ventersdorp observations (queue times, throughput) is a separate later step and needs permitted data.

## 5. Questions for you (V1–V14)

1. **V1.** Please attach or describe the PLC diagrams for Silo A and Silo B. They did not reach this session.
2. **V2.** Is the "SiloX" flow diagram a model of a Ventersdorp facility (A, B, or both)? Or is it another site?
3. **V3.** Sampling station: number of probes, and number of people working it?
4. **V4.** Is grading a separate truck stop? Does the truck wait for the result before weigh-in?
5. **V5.** Unload order for each silo (same for A and B?). Are dispatch trucks sampled?
6. **V6.** Which bridge do weigh-only trucks use?
7. **V7.** How is a truck assigned to Silo A or B: by commodity and grade, by bin space, or by a rule or instruction?
8. **V8.** After weigh-in, do trucks for A and B use different roads or queue areas? What are the queue capacities?
9. **V9.** Per silo: hoppers (count, pit t, tip time, t/h), and is any bay used for both tipping and loading?
10. **V10.** Per silo: conveyors and elevators (rated and actual t/h), and which of them are shared between A and B?
11. **V11.** The A↔B interconnect: equipment, direction(s), and when it is used. Are bin-to-bin transfers made during receiving hours?
12. **V12.** Bins: ids, capacities, allowed commodities and grades, the temporary bin's role.
13. **V13.** Changeover times per conveyor or elevator.
14. **V14.** Crews per silo or site-wide (hopper operator, weighbridge clerk, sampler, grader), by shift.
