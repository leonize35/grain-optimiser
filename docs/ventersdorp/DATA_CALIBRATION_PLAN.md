# Ventersdorp data requirements and calibration plan (no implementation)

Status: plan only (2026-10-25). No engine code, configuration or evidence package was changed. The synthetic
configurations (Sites A, B, C, S, trap) and the packages `paper2-v1` and `paper2-ext-sampling-v1` are untouched.
**The Ventersdorp model does not exist yet and is not validated.** No staffing optimisation starts before the
acceptance criteria in §8 are met.

## Input labels used in this plan

| Label | Meaning |
|---|---|
| **M** | Measured: taken directly from Ventersdorp records or time studies |
| **C** | Calibrated estimate: derived from measured data by a stated method, with uncertainty |
| **U** | Unverified assumption: reported in every result until confirmed |

## 1. Confirmed operating rules (user, 2026-10-25) and what they mean for the engine

| # | Rule | Engine today | Gap |
|---|---|---|---|
| R-1 | Silo A and Silo B unload simultaneously and share one receiving sampler, one incoming and one outgoing weighbridge | One config holds both subsystems; weighbridge `moves: in / out` enforced | None for structure. Topology from PLC (§5) |
| R-2 | Receiving: sample → weigh in → assigned silo/hopper → unload → weigh out → depart | Sequence `[sample, weigh_in, tip, weigh_out]` is valid. No separate grade stop | Whether the truck waits for a grading result before going to the hopper is **Q-1** |
| R-3 | Loading: weigh in → load → sample loaded grain → weigh out → depart | `sample` after `load` is not refused by validation, but it is **untested**. A sample there must not gate anything | **G-C3:** test (and fix if needed) a post-load sample step |
| R-4 | Loading sampling may use a separate silo-side point or one near the outgoing weighbridge, not necessarily the receiving sampler | Samplers are **pooled**: any sampler serves any truck (`truck_flow.py`, `crews = [… type == "sampler"]`) | **G-C2:** restrict a sampler to activities (like weighbridge `moves`), so receiving trucks never use the loading point and vice versa |
| R-5 | Hopper/commodity assignment depends on connected storage, bin contents and the silo manager | Hopper chosen by a feasible grain route and bin compatibility | Manager decisions are **not modelled**. Baseline rule: feasible route + bin contents (**U**). Allocation shares from records if available (§2, D-2) |
| R-6 | FIFO is normal, with exceptions | `strict_fifo` and `feasible_first` selectable per queue group | Baseline = FIFO (**M** as a rule). Exceptions are unmodelled and listed as a limitation. No dispatching intervention until the exceptions are understood |
| R-7 | At closing, admission stops; trucks present are processed to completion | `admission_cutoff`, `close`, fixed `overtime` hours, `end_of_day` | **G-C4:** "process until clear" mode, plus outputs for overtime used and final clearance time (measurement framework step 6) |
| R-8 | Staffing: sampling 2 (collector + runner to office), weighbridge 2–3, unloading ~4 depending on active hoppers; seasonal/shift workers added | Pools, shifts, scenarios; labour on sample, grade, weigh_in, weigh_out, tip, load and intake; shared unloading workers by task (`unloading_labour`, OPERATOR_STAFFING_DESIGN §11) | **G-C5 (corrected 2026-10-25):** labour on `load` is already supported; only crew-time factors are not. **G-C6:** the sample runner works off the truck (transport to the office); it matters only if the result gates the truck (Q-1). **G-C8:** per-silo crews if they exist (Q-9) |
| R-9 | Unloading includes manual work: positioning, assisting, scraping, sweeping spill into hoppers | Tip time is one triangular duration per hopper; `crew_time` scales a step's time by operator count | **G-C7:** a crew-size effect on unloading needs time-study evidence (§3.4). Without it, more operators only reduce waiting for labour, never task time |

The engine also needs:
- **G-C1:** fitted distributions. Only triangular [min, mode, max] durations are supported today (`service_times.py`); fitted families (e.g. lognormal, gamma) or empirical resampling are needed.
- **G-C9:** a per-truck weigh-in-to-weigh-out interval output (derivable from step records).

Resolved items in `VENTERSDORP_GAP_ANALYSIS.md`:
- row 6 (no separate grading stop, pending Q-1);
- row 7 (receiving order);
- row 8 (loading order and loading sampling);
- part of row 10 (assignment by storage, bin contents and manager).

## 2. Required datasets and fields

Data handling, for every dataset:
- raw records stay **outside the repository** (the GitHub repo is public);
- registrations, driver names and ticket numbers are pseudonymised before analysis;
- only aggregate, approved parameters enter a configuration;
- each dataset gets an id, date range, source and extraction date in a data register.

| ID | Dataset | Status | Required fields | Use |
|---|---|---|---|---|
| D-1 | Time-study observations, receiving activities | **Available** | Date, time of day, activity, start, end, truck pseudonym, commodity, tonnes, truck type (e.g. side tipper, interlink), hopper/silo, crew size present, interruptions/notes, observer | Process-time fitting (§3) |
| D-2 | Historical weighbridge records | **Available** | Ticket pseudonym, direction (in/out), timestamp (which instant: start or end of weighing? **Q-2**), gross/tare/net, commodity, grade, activity (receiving/loading), silo/bin/hopper if recorded | Validation of weigh-in → weigh-out (§4); arrival estimation (§3.5); assignment shares (R-5) |
| D-3 | Daily truck counts and tonnage | **Available** | Date, activity, commodity, trucks, tonnes | Demand per day type; reconciliation with D-2 |
| D-4 | Operating hours: average, busy, peak | **Available** | Day type, opening, admission cut-off, close, actual last departure if known | Hours configuration; clearance validation |
| D-5 | PLC layouts, Silo A and Silo B | **Available** (not yet supplied to this project) | Hoppers, conveyors, elevators, bins, load points, connections and directions, shared equipment | Topology (§5) |
| D-6 | Equipment capacities and rates | **Obtainable** | Hopper pit capacity and intake rate, conveyor/elevator rated and effective t/h, bin capacities, load-point rates, changeover/cleaning times | Equipment parameters (§5) |
| D-7 | Staffing records or rosters | **Needed** | Per day/shift: people per activity, seasonal additions | Staffing baseline (§6) |
| D-8 | Time study of loading activities | **Needed** if loading is in scope | As D-1 for load, loading sampling, positioning | Loading process times |
| D-9 | Gate arrival times (a sample of days) | **Needed** (see §3.5) | Truck pseudonym, gate arrival time, commodity | Unbiased arrival process |
| — | Continuous timestamps for sampling, grading, unloading | **Not available** | — | Those stages are validated only through the weighbridge interval |
| — | Equipment downtime or breakdown history | **Not available** | — | No downtime in the baseline; sensitivity only (§7) |

## 3. Process-time distribution fitting

### 3.1 Activities to fit (from D-1)

Receiving:
- sampling (probe at the truck);
- sample transport to the office, only if it gates the truck (Q-1);
- weigh-in;
- travel/positioning at the hopper;
- unloading (tipping);
- scraping and sweeping;
- travel to and weigh-out at the outgoing weighbridge.

Loading (D-8): weigh-in, positioning, loading, loading sampling, weigh-out.

Whether positioning and sweeping are separate from tipping, and whether sweeping keeps the hopper occupied after the
truck leaves, is **Q-3**.

### 3.2 Data preparation
1. Check every observation against its notes. Interruptions (breakdowns, breaks) are flagged, never silently deleted; a sensitivity fit with them included is reported.
2. Record sample size per activity and stratum.
3. Look for dependence on covariates before choosing one distribution:
   - unloading time against tonnes, truck type, commodity, hopper and crew size;
   - sampling time against commodity.

   A clear dependence is modelled (e.g. unloading = handling time + tonnes ÷ effective rate, or a distribution per truck type), not averaged away.

### 3.3 Fitting and selection
- **Candidates:** lognormal, gamma, Weibull (positive, right-skewed), fitted by maximum likelihood; empirical resampling when the sample is large and no family fits.
- **Triangular only** as a documented fallback for very small samples, labelled **U**.
- **Selection:**
  - visual Q-Q and P-P plots;
  - Anderson-Darling or Kolmogorov-Smirnov (noting that p-values are optimistic when parameters are estimated from the same data);
  - AIC between families;
  - the simplest adequate family wins.
- **Minimum observations** (guidance): about 30 per activity and stratum for a fitted family. Fewer → pool strata (if no significant difference) or flag the input as **U**.
- **Output per activity:** family, parameters, n, date range, goodness-of-fit evidence, label **C**.

### 3.4 Uncertainty
- **Parameter uncertainty:** bootstrap the time-study sample (≥1 000 resamples) for confidence intervals of each parameter and of the mean and p90.
- **Propagation:** for each scenario, run replications across bootstrapped parameter sets (input-uncertainty replications), or at least at the lower and upper CI parameter sets. Report how much of the output spread comes from input uncertainty versus run-to-run variation.
- **Crew-size effect (G-C7):** estimable only if D-1 contains unloading observations at different crew sizes (e.g. 2 against 4 people). If not, `crew_time` stays empty and staffing affects only waiting for labour. That limitation is stated in every staffing result.

### 3.5 Arrival process
Only weighbridge timestamps are recorded continuously. A weigh-in time equals gate arrival **plus** waiting and service
at the sampler. Arrival rates estimated from weigh-in times are therefore smoothed and delayed exactly when the site is
congested, which is when it matters.

Proposed method:
- **Daily totals** (**M**) from D-3.
- **Hourly arrival profile** per day type (**C**): estimated from weigh-in times, corrected with gate arrival observations (D-9) on a sample of days. Without D-9 the correction is **U** and the profile is labelled "weigh-in based".
- **Circularity:** hourly weigh-in counts are then partly input. They must not be used as independent validation (§4).

## 4. Validation metrics and observation windows

**Primary validation quantity:** the weigh-in-to-weigh-out interval (W2W), per completed truck.
- *Historical:* weigh-out timestamp − weigh-in timestamp for the same ticket (D-2).
- *Simulated:* the same two instants, consistent with Q-2 (start or end of weighing).
- W2W for receiving trucks covers hopper queue, unloading, travel and the outgoing-weighbridge queue and service. For loading trucks it covers loading and loading sampling.
- **It is not total turnaround:** sampling, the sampler queue and gate waiting come before weigh-in and are not in it.

| Metric | Comparison | Window |
|---|---|---|
| V-1 W2W distribution, receiving | Mean, median, p90; distance between distributions (e.g. Wasserstein); simulated 95% interval of daily means vs observed daily means | Per day type (average, busy, peak); by hour band (e.g. 07–10, 10–14, 14–cut-off, after cut-off) |
| V-2 W2W per commodity | Mean and p90 | Per day type, where n is enough |
| V-3 W2W, loading trucks | Mean, median, p90 | Per day type, if loading is in scope |
| V-4 Final clearance | Last weigh-out time − admission cut-off (overtime used) | Per day |
| V-5 Weigh-outs per hour | Hourly counts | Per day type. Partly independent: it follows from arrivals plus the system, but the weigh-in side is input (§3.5) |
| V-6 Daily tonnes and trucks | Must match by construction | Input check, **not validation** |

**Observation windows:**
- **Calibration and validation days are separated before any comparison.** Split by date, e.g. alternate weeks, or one season to calibrate and another to validate. No parameter is tuned on validation days.
- Each day type (average, busy, peak) needs enough days in both sets. A guideline of ≥10 validation days per day type is to be confirmed against what D-2 holds.
- Downtime is not recorded, so some historical days contain unrecorded breakdowns. Those days are not removed by outcome (that would bias validation). Results are reported with and without days the site identifies as abnormal, using its own list, not the model's fit.
- Thresholds are agreed **before** the comparison (§8).

## 5. Equipment parameters (from D-5, D-6)

Per silo:
- hoppers: count, pit capacity (t), intake rate (t/h), tip admission rule, commodities allowed;
- conveyors and elevators: rated and effective t/h, length and speed (→ clearing time), concurrent feeds, changeover/cleaning time per commodity pair;
- bins: id, capacity (t), allowed commodities and grades, opening stock per scenario day;
- load points: count, rate, setup time;
- connections: hopper → … → bin and bin → … → load point, with directions;
- shared equipment between A and B, including any interconnect;
- truck roads and waiting areas: capacity between sampler, incoming weighbridge, hoppers and outgoing weighbridge (**Q-4**).

Site-wide:
- receiving sampler (probes, trucks at once);
- loading sampling point(s) and where they are (R-4);
- incoming and outgoing weighbridges (trucks at once).

Labels: PLC connectivity **M** after the silo manager confirms the reading; rated capacities **M**; effective rates **C** (from time studies or tonnage records); anything else **U**.

## 6. Staffing parameters (treated as decision variables, not as optimal)

| Pool (proposed) | Skills (steps) | Baseline count | Label |
|---|---|---|---|
| Sampling: collector | `sample` (receiving) | 1 | M (stated), schedule U |
| Sampling: runner | Sample transport (off-truck; G-C6) | 1 | M (stated); modelled only if Q-1 says the result gates the truck |
| Weighbridge | `weigh_in`, `weigh_out` (shared or split, **Q-5**) | 2–3 | M range; the split is U |
| Unloading crew | One pool **shared by Silo A and Silo B** (confirmed 2026-10-25), doing unloading tasks: positioning, assisting, scraping, sweeping (`unloading_labour`; task workers and times Q-3, Q-6) | ~4 | M (stated, shared); task requirements U |
| Loading crew | `load` (supported) | **Q-7** | U |

- Shift windows and seasonal additions come from D-7.
- Staffing scenarios vary pool counts and windows only. Equipment stays unchanged.
- Staffing optimisation is **not started** here. It needs §8 and an agreed objective that does not infer revenue (CLAUDE.md), e.g. minimum crew meeting a W2W or clearance target.

## 7. Downtime

- **Baseline:** normal operation, no downtime. That is stated as a limitation because downtime is not recorded.
- **Sensitivity scenarios:** explicit, hypothetical outages using the existing scheduled `outages` (equipment, start, duration). Examples: incoming weighbridge down 30 min at 10:00; one elevator down 2 h. They are labelled hypothetical and never presented as historical frequencies.
- Random breakdowns (mean time between failures, mean time to repair) are **not** modelled. No data exists, and the engine would need an extension.

## 8. Minimum acceptance criteria before scenario experimentation

| # | Criterion | Evidence |
|---|---|---|
| AC-1 | PLC topology entered and reviewed with the silo manager (equipment, connections, shared items) | Signed-off topology note; config validation with no errors |
| AC-2 | Every parameter labelled M, C or U in an assumption register; U items reviewed | Register in the result metadata |
| AC-3 | Engine gaps needed for the baseline closed with tests: G-C1, G-C2, G-C3, G-C4 and G-C9 (G-C5 to G-C8 as Q-1, Q-6, Q-7 and Q-9 require) | Tests passing; full suite; both evidence packages reproduce |
| AC-4 | Measurement framework steps 1–6 implemented (outcomes, occupancy, RMST, failures reported, clearance verified) | `docs/MEASUREMENT_FRAMEWORK.md` tests T1–T11 |
| AC-5 | Verification on the Ventersdorp baseline | Zero rule violations, grain balance zero, zero stalls, and clearance verified in every replication |
| AC-6 | Process-time distributions fitted with goodness-of-fit evidence and bootstrap uncertainty | Fitting report per activity |
| AC-7 | Validation on held-out days, against thresholds agreed **before** comparison | Validation report (V-1 to V-5) |
| AC-8 | Face validity: a trace walk-through of a busy day reviewed by the silo manager | Review note |
| AC-9 | Sensitivity of the baseline to the main U items (arrival profile correction, crew-time effect, assignment rule) known | Sensitivity table |
| AC-10 | Data handling: no raw or identifying records in the repository; customer configuration stored only with permission | Repository check |

Proposed starting thresholds for AC-7, to be confirmed by you before any comparison:
- Receiving W2W mean within ±10% of the observed mean for each day type.
- The observed daily-mean W2W within the simulated 95% interval on at least 80% of validation days.
- p90 within ±15%.
- Clearance time within ±30 min on average.

Passing AC-7 supports validity **for Ventersdorp under the observed conditions and this model version only**.

## 9. Remaining operational questions

1. **Q-1:** Does a receiving truck wait for the grading result (from the office) before it is sent to a hopper? Does the runner's transport time matter?
2. **Q-2:** Which instant do weighbridge timestamps record: start or end of weighing, ticket print?
3. **Q-3:** Are positioning and sweeping separate from tipping? Does sweeping keep a hopper unavailable after the truck leaves?
4. **Q-4:** Where do trucks wait between stations? How many fit (e.g. between incoming weighbridge and hoppers, and before the outgoing weighbridge)?
5. **Q-5:** Are the weighbridge staff split between incoming and outgoing, or shared?
6. **Q-6:** How many unloading people does one active hopper need?
7. **Q-7:** Who loads trucks, and is loading labour-constrained?
8. **Q-8:** Which loading sampling point is used when, and who does it?
9. **Q-9:** Are crews per silo or shared across A and B?
10. **Q-10:** Do the time studies include gate arrival times, and observations at different crew sizes?
11. **Q-11:** Do weighbridge records include silo, bin or hopper, so that assignment shares can be estimated?
12. **Q-12:** Are weigh-only trucks part of the operation? Which weighbridge do they use?
13. **Q-13:** What form do FIFO exceptions take (e.g. priority commodity, a truck sent ahead because its bin is free), and how often do they occur?

Measurement questions Q-M1 to Q-M9 (`docs/MEASUREMENT_FRAMEWORK.md` §7) remain open. Partly answered:
- **D1 / Q-M3:** at closing, admitted trucks are processed to completion.
- **D7:** FIFO is normal, with exceptions.

## 10. Proposed sequence (each step test-first; nothing started)

1. Data register and pseudonymisation procedure (outside the repo); receive D-1 to D-6.
2. Measurement framework steps 1–6 (AC-4) and engine gaps G-C1 to G-C4 and G-C9.
3. PLC topology → Ventersdorp configuration (private location unless you approve otherwise), plus structure tests (AC-1).
4. Fit process times and estimate the arrival profile (§3), then the verification runs (AC-5, AC-6).
5. Validation on held-out days (AC-7), face validity (AC-8) and sensitivity (AC-9).
6. Only then: staffing scenarios, then staffing optimisation.
