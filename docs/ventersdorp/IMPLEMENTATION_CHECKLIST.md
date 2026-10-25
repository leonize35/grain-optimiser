# Ventersdorp implementation checklist

Status (2026-10-25): the data requirements and calibration approach are approved, subject to corrections C1–C6
(§0). The Ventersdorp model is **not validated** and **no staffing optimisation has started**. The synthetic
configurations and evidence packages stay unchanged.

## 0. Corrections from the user's approval

| # | Correction | Where applied |
|---|---|---|
| C1 | Q-9 resolved: about four unloading workers are **shared** across Silo A and Silo B | One shared pool (`unloading_labour`, commit eeab26f); `DATA_CALIBRATION_PLAN.md` Q-9 |
| C2 | 30 observations per activity or stratum is a **guideline**, not a minimum. Report uncertainty; avoid unnecessary subgrouping | `DATA_CALIBRATION_PLAN.md` §3.3 |
| C3 | Staffing objective: an allocation that **balances** turnaround, throughput, overtime and labour, not minimum headcount | `DATA_CALIBRATION_PLAN.md` §6; `OPERATOR_STAFFING_DESIGN.md` §11.3 |
| C4 | Validation thresholds stay **provisional** until the historical data has been examined | `DATA_CALIBRATION_PLAN.md` §8 |
| C5 | Distinguish admission closing time, continued processing of admitted trucks and actual final clearance time | Item A1 below |
| C6 | Preserve the synthetic models and evidence packages | Every item: reproduction check before commit |

## 1. Can proceed now (technical; no site data or operational answer needed)

Each item follows the same cycle: failing test, minimal change, invariants, full suite, reproduction checks, commit.

| # | Item | Source | Status |
|---|---|---|---|
| A1 | Closing and clearance per day: admission cut-off, closing, hard stop, last admission, continued processing after closing, final clearance time, overtime used, cleared or not (with the trucks remaining) | MEASUREMENT_FRAMEWORK §4; C5 | **Done**: `result.clearance`, `result.outcomes` (tests/test_outcomes_clearance.py) |
| A2 | Truck outcomes: completed / unfinished on site / unfinished at gate / turned away (reason, time on site) | MEASUREMENT_FRAMEWORK K2, K3, §1 | **Done**: `result.clearance`, `result.outcomes` (tests/test_outcomes_clearance.py) |
| A3 | Truck-hours on site and mean observed time on site within the horizon, split gate/site, with the exact ∫N(t)dt identity | MEASUREMENT_FRAMEWORK K6 | **Done**: `result.clearance`, `result.outcomes` (tests/test_outcomes_clearance.py) |
| A4 | Weighbridge instants per truck (weigh-in start/end, weigh-out start/end), so the weigh-in-to-weigh-out interval can match the historical definition once Q-2 is answered | DATA_CALIBRATION_PLAN G-C9 | **Done**: `result.clearance`, `result.outcomes` (tests/test_outcomes_clearance.py) |
| A5 | Restricted mean time to completion RMST_C(τ) on the full-follow-up cohort, with F_C(τ) and F_R(τ). τ is a parameter with no default | MEASUREMENT_FRAMEWORK K7 | **Done**: `outcomes.restricted_mean_time_to_completion` (tests/test_outcomes_clearance.py) |
| A6 | Run validity: failed replications reported, never dropped (`run_experiment`, `paired`); arrival hash per pair; evidence tools get the new fields only in a new package version | MEASUREMENT_FRAMEWORK §3 | **Done** (runner): `Replication` arrival hash, intended/arrived trucks, failure time; metadata `failures`, `summary_scope`; `compare()` (tests/test_run_validity.py). Evidence tools: only in a new package version |
| A7 | Fitted service-time distributions (lognormal, gamma, Weibull, empirical) alongside triangular; independent streams kept | DATA_CALIBRATION_PLAN G-C1 | **Done**: `Equipment.distributions` per step; `sim/distributions.py` (tests/test_distributions.py). Not yet for unloading-task times |
| A8 | A sampler restricted to activities (receiving or loading), like weighbridge direction | G-C2 | **Done**: `Equipment.activities` for stations (tests/test_station_activities.py) |
| A9 | Loading sequence with sampling after loading (weigh in → load → sample → weigh out): test, fix if needed | G-C3 | **Verified**: works without an engine change; the loading sample is not graded (tests/test_station_activities.py) |
| A10 | Tonnes consistency (received, completed-truck tonnes, work in progress) and fairness bounds per commodity | MEASUREMENT_FRAMEWORK K4, K8 | **Done**: `outcomes.summary[act].tonnes`, `outcomes.fairness` (per commodity: completion rate, starvation [lower, upper], overtaking; disparity) |
| A11 | Distribution-fitting tool (maximum likelihood, Q-Q/AD, AIC, bootstrap CIs) tested on synthetic samples; no site data | DATA_CALIBRATION_PLAN §3 | **Done**: `silo_engine.calibration.fitting` (`fit`, `bootstrap`, `as_distribution`; tests/test_fitting.py, synthetic samples only) |

**How A1 represents "processed to completion".** Services for admitted trucks may start until closing plus the
configured overtime (the hard stop); a running service is completed. Each day's `clearance` then reports, separately:
- the admission cut-off;
- closing;
- the hard stop;
- the trucks admitted, and how many were still on site at closing;
- the actual final clearance time, overtime used, and whether every admitted truck completed (with those remaining if not).

For Ventersdorp the overtime is set as a cap long enough to clear. A day that does not clear by the cap is
reported as **not cleared**, never as cleared (MEASUREMENT_FRAMEWORK §4). Whether workers are available in overtime is
Q-M7.

**Finding from A6 (not changed):** when operator shifts are configured, a run blocked for good (e.g. a full bin)
is not flagged as a stall before the last shift change. It ends at the hard stop with trucks unfinished; the day's
clearance record shows it as not cleared. Possible later refinement: ignore shift changes that cannot resolve the
waiting reasons when detecting a stall.

## 2. Needs your data

| # | Item | Needs |
|---|---|---|
| B1 | Ventersdorp topology and configuration (hoppers, conveyors, elevators, bins, interconnects) | PLC layouts (D-5), capacities and rates (D-6) |
| B2 | Process-time distributions per activity, with bootstrap uncertainty | Time studies (D-1, D-8) |
| B3 | Arrival profile per day type (weigh-in based, corrected if gate arrivals exist) | Weighbridge records (D-2), daily counts (D-3), gate arrivals (D-9, Q-10) |
| B4 | Hours per day type | Operating hours (D-4) |
| B5 | Validation on held-out days (W2W, clearance, weigh-outs per hour); thresholds set after examining the data (C4) | D-2, D-4 |
| B6 | Staffing baseline per shift and period | Rosters (D-7) |

Raw records stay outside the public repository; registrations and names are pseudonymised (DATA_CALIBRATION_PLAN §2).

## 3. Needs your operational confirmation

| # | Question | Blocks |
|---|---|---|
| ~~Q-1~~ | Resolved: the truck waits for its result on the incoming weighbridge (`RECEIVING_PROCESS.md`; tests/test_grading_blocking.py) | — |
| Q-2 | Which instant do weighbridge timestamps record? | W2W definition (A4 provides all four instants meanwhile) |
| Q-3 | Are positioning and sweeping separate tasks? Does sweeping block the hopper? | Unloading task list (now a provisional assumption) |
| Q-4 | Waiting places and capacities between stations | Truck paths and blocking |
| Q-5 | Weighbridge staff shared between in and out, or split? | Weighbridge labour pool |
| Q-6 | Workers needed per unloading task | Task workers (placeholders now) |
| Q-7, Q-8 | Loading labour; which loading sampling point is used when | Loading model |
| Q-11 | Do weighbridge records carry silo, bin or hopper? | Assignment shares |
| Q-12 | Weigh-only trucks, and which bridge they use | Weigh-only activity |
| Q-13 | Form and frequency of FIFO exceptions | Queue policy; any intervention |
| Q-M1, Q-M4, Q-M5 | Gate wait on site? Which τ? Turnaround from gate arrival or admission? | Reporting choices (A3, A5) |
| Q-M7 | Are workers available during overtime? | Clearance runs with labour |
| D3, D4, D6 | Starvation threshold, fairness criterion, commodity priorities | Fairness reporting; any intervention |

## 4. Not started, by instruction

- Staffing optimisation, and any staffing recommendation for Ventersdorp.
- Dispatching interventions (overtaking limits, priorities).
- Any claim that the Ventersdorp model is validated. That needs B1–B5 and the acceptance criteria AC-1 to AC-10.
