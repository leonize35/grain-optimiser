# TLS on the model: design draft (TOC, Lean, Six Sigma)

Status: **draft for the user to correct** against the integrated TLS framework of the dissertation (2026-11-07).

Progress:
- **T1 (built 2026-11-07).** `silo_engine.analysis.resource_use(site, result, little_tolerance=0.1)` reports:
  - per equipment: busy, after-hours, utilisation, blocked, queued truck-minutes, served and mean queue;
  - graders, read from the reservation ledger (runs now carry `ledger_log`);
  - per grain segment: reserved and flowing time;
  - the gate, with censoring;
  - labour and areas;
  - steps still waiting at the end;
  - the Little's law check (exact and steady-state).

  Tests: `tests/test_resource_use.py` (hand-traced). Not yet in the API or app. Known limitations are listed in each report. The 10 % tolerance is provisional.
- **T2 (built 2026-11-07).**
  - **New engine output.** Runs carry `wait_causes`, recorded at every event (reporting only; about 12 % extra run time). It holds the minutes of waiting per clock hour, per kind and per cause.
    - Kinds:
      - truck: waiting to start a step;
      - in_service: during service, waiting for pit space in partial tipping, or for workers;
      - task;
      - sample;
      - grain.
    - Each waiting request counts 1 per minute, split equally over its reasons.
  - **Causes are traced** to what explains them:
    - a full pit → its intake's reasons (e.g. a full bin), or the slowest part of the draining route;
    - a busy station whose lanes hold trucks that finished but are held → those trucks' causes;
    - a truck held for its grading result → the sample's queue, or the grader serving it;
    - a request behind an earlier one → that one's reasons.
  - **`silo_engine.analysis.constraint_candidates(site, result, lead_share=0.4, lead_ratio=1.5, min_hour_min=5)`:**
    - sums the causes by the resource at the root of each chain and ranks the candidates;
    - shows for each candidate its direct and traced minutes, the chains, its in-service minutes and its utilisation;
    - names the constraint only if it stands out, otherwise "no single constraint";
    - reports the leader per clock hour and the periods in which it stays the same;
    - checks independently that the truck causes reconcile exactly with the step records.

  Tests: `tests/test_constraints.py` (hand-traced). The thresholds are provisional. Not yet in the API or app.

TLS here is an **analysis layer over simulated runs**. It reads run results; it never changes how the engine dispatches, reserves or moves grain. It works for any silo configured in the platform. No layout, step, target or threshold is assumed, and each is a setting of the silo or of the study.

## 1. Sequence (proposed)

1. **TOC first: find the constraint.** Its purpose is to say where improvement pays off. Without it, Lean and Six Sigma effort spreads over steps that do not limit the flow.
2. **Lean: remove waste around and across the flow.** Look first at waiting before the constraint and at work the constraint does that could be done elsewhere.
3. **Six Sigma: reduce variation.** Focus on the constraint's service time and on the turnaround that the truck owner experiences, measured against targets the site sets.
4. **Repeat.** Re-identify the constraint on the improved scenario, because it moves.

Each improvement idea is a **scenario**: a configuration overlay compared paired against the baseline with common random numbers, using the existing `compare`. Each idea is tagged with the part of TLS it comes from.

## 2. What the runs already record (verified in `sim/truck_flow.py`)

| Need | Available now | Gap |
|---|---|---|
| Waiting and service per truck per step | `StepRecord`: entered, started, finished, left, unit (equipment and lane) | none |
| Time blocked at a station (finished, but could not move off) | `left − finished` | none |
| Gate waits | `TruckRecord.arrived`, `admitted`, `departed` | none |
| Why trucks wait, and for which resource | `waiting_attribution` per (reason, resource) | only when labour or unloading labour is configured; must become general |
| Labour utilisation | `staffing` per pool | none |
| Waiting-area use | `area_occupancy` (time average, peak) | none |
| Grain-side flow (tipping → storage) | `lots`, `transfers` | busy time of elevators and belts per segment is derivable from transfers; pit-full and pit-empty time is not reported yet |
| Clearance | `clearance`, `clearance_by_system` | none |

## 3. TOC module

**Resource use report**, per resource: station lanes, hoppers and pits, route segments (belts and elevators), bins, labour pools, waiting areas. It shows:
- busy share of open time;
- truck-minutes queued for the resource;
- time blocked (it could not hand work on);
- time starved (idle while trucks or grain were upstream);
- for pits: time full (trucks cannot tip) and time empty.

**Constraint candidates:**
- Resources are ranked by the truck-minutes of waiting they cause, using the waiting reason. A hopper that waits because its pit cannot drain points downstream, to the belt, elevator or bin.
- The report shows the evidence for each candidate, not a verdict.
- When no resource stands out, it says "no single constraint". When the leading resource changes during the day (e.g. the morning peak versus the afternoon), it reports that too.
- The threshold for "stands out" is a setting, to be calibrated.

**Five focusing steps as a guided workflow:**
- **Identify:** the report above.
- **Exploit:** rule changes without new capacity, e.g. queue policy, release rules, partial tipping, two hoppers on one belt.
- **Subordinate:** pace the rest of the site to the constraint, e.g. gate admission and the buffer size before the constraint.
- **Elevate:** capacity scenarios, e.g. a lane, a hopper, belt rate, workers.
- **Repeat:** re-identify on the chosen scenario.

Drum-buffer-rope maps onto existing primitives: the waiting area before the constraint is the buffer, and gate admission is the rope.

## 4. Lean module

**Value-stream map** per activity (receiving, loading, weighing). For every step in the site's own sequence, it shows:
- mean and spread of service time;
- waiting before the step;
- time blocked;
- movement between places.

It also shows the time on site from gate to exit.

**Step classification** is a site setting: value-adding, necessary non-value-adding, or waste. The platform does not decide that tipping adds value and sampling does not. The user classifies each step.

**Measures:**
- process cycle efficiency, defined as value-adding time divided by time on site;
- lead time;
- trucks on site through the day (WIP), and grain waiting in pits;
- takt time, defined as available time divided by demand, set against the constraint's cycle time.

**Little's law** (L = λW) is computed per run as an **independent consistency check**: average trucks on site = throughput × mean time on site, within a stated tolerance, over a window where the system starts and ends comparably. A failure is reported as a model or measurement problem, not as a finding.

**Waste categories**, mapped to what the model can show:
- waiting: queues, holds and blocking;
- transport: movement between areas;
- inventory: trucks queued and grain waiting in pits;
- defects: unfinished and turned-away trucks.

Over-processing and rework are not modelled (e.g. re-sampling), and the report says so.

## 5. Six Sigma module

**CTQ settings (critical to quality)**, set per silo or per study:
- for example, the turnaround upper limit (USL) in minutes;
- the definition of turnaround: gate to exit, or weigh-in to weigh-out;
- the hopper wait limit;
- the clearance deadline.

No defaults that look like real targets.

**Capability across trucks and replications:**
- defect share, yield and DPMO, with confidence intervals across replications;
- percentile-based Pp/Ppk. Turnaround is skewed, so normal-theory Cpk would mislead. Long-run simulated data is "performance" (Pp/Ppk), not short-term capability;
- the sigma level is optional, and the 1.5σ shift convention is shown only if chosen.

**Unfinished trucks** (right-censored):
- If its wait so far already exceeds the USL, it is a defect.
- Otherwise its status is unknown, and it is reported apart and never dropped silently.

**Sources of variation:**
- Turnaround is decomposed into waiting and service per step.
- A **screening experiment** varies user-chosen factors, each a configuration overlay with two levels, in a fractional factorial. It uses common random numbers and reports main effects with intervals on the mean, the 90th percentile and the defect share.

**DMAIC mapped onto the manager workflow:**
- **Define:** CTQs and scope.
- **Measure:** baseline runs, with the configuration's calibration status shown.
- **Analyse:** the TOC report, the value-stream map and the screening experiment.
- **Improve:** scenarios.
- **Control:** the chosen scenario re-run under busy and peak demand and other variability scenarios, to check that it holds.

## 6. One "improvement study"

A study belongs to one saved site version and holds:
- the baseline;
- the CTQs and step classifications;
- the TOC, Lean and capability reports;
- the list of candidate changes, each tagged TOC, Lean or Six Sigma;
- their paired results.

Study settings live **beside** the site configuration, not inside it. They do not change the simulation, so they stay out of the engine configuration hash. They are versioned with the study and recorded in every report, together with:
- the engine version;
- the configuration hash;
- the seeds;
- the replications;
- the model-assurance scope.

## 7. Guardrails

- Results are **simulated**. A study reports the configuration's validation status (for Ventersdorp: not validated).
- No revenue or lost-demand gain is inferred from shorter queues.
- TLS **suggests and compares**. It does not optimise staffing or dispatching automatically (standing rule).
- Thresholds (constraint, Little's law tolerance) are settings and are reported with the result.

## 8. Build slices (each test-first, with hand-traced cases)

1. **T1 Resource use report:**
   - busy, queued, blocked and starved time per resource;
   - waiting attribution for all resources, not only labour;
   - the Little's law check;
   - covering a station, a hopper with pit and route, and a labour pool.
2. **T2 Constraint candidates:**
   - ranking with evidence;
   - the "points downstream" rule for a pit that cannot drain;
   - "no single constraint";
   - a constraint that shifts during the day.
3. **T3 Value-stream map:** step classification setting, process cycle efficiency, takt time against the constraint's cycle time.
4. **T4 CTQs and capability:** defect share, DPMO, Pp/Ppk by percentiles, censoring rules.
5. **T5 Screening experiment runner:** fractional factorial over overlays; main effects with intervals.
6. **T6 App screen "Improve my silo":**
   - the guided sequence (five focusing steps / DMAIC);
   - manager mode in plain language;
   - Advanced mode shows the evidence and thresholds.

## 9. Questions for the user (domain decisions)

1. Does the dissertation fix the order (TOC → Lean → Six Sigma → repeat) or another integration, e.g. Lean and Six Sigma inside each TOC step?
2. Which measures does the dissertation's framework require, and with which definitions (e.g. turnaround: gate to exit, or weigh-in to weigh-out)?
3. How should steps be classified (value-adding / necessary / waste), or should every site choose?
4. Should the 1.5σ shift be reported, or only DPMO and Pp/Ppk?
5. Should constraint analysis cover the grain side (elevators, belts, bins) as well as the truck side? (Proposed: yes, since a full pit is often a downstream constraint.)
