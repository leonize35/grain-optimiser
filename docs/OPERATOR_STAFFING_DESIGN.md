# Operator staffing as a resource: audit and design (for review; nothing implemented)

Status: design for review (2026-10-25). The Paper 2 baseline (`paper2-v1`, commit `6345377`) and the sampler-access
extension (`paper2-ext-sampling-v1`, commit `3c54428`) are unchanged. Any staffing experiment will be a further,
separately versioned extension.

**No operator count, shift, task assignment or staffing policy below is a fact about any silo.** Every number in an
example is a placeholder marked `UNVERIFIED`. Baseline staffing must come from the silo manager (§6).

## 1. Audit: how labour is represented today

| Element | Current representation | Problem for staffing questions |
|---|---|---|
| Sampler, grader, weighbridge | `cap` = "trucks served at once", one lane per unit | **Equipment and staff merged.** `cap: 2` cannot say whether there are 2 probes, 2 people for 1 probe, or 2 of each. |
| Sampling at a weighbridge bay | The sampler's `cap` = number of "sampling units" (probe or crew, undefined) | The same ambiguity: is the probe or the person the constraint? |
| Hoppers (tipping) | One tipping lane per hopper; no attendant | Cannot represent a tipping supervisor shared by several pits |
| Load points | One lane per load point; setup time | No load-out operator; setup assumed always staffed |
| Grain transfers | No labour | A control-room operator who starts or monitors transfers is not represented |
| Operating hours | Opening, cut-off, overtime per day | No shifts or seasonal staff periods |
| Results | Equipment occupancy derivable from records | No operator utilisation; no labour waiting reason |

**Conclusion:** the model cannot currently tell whether labour or equipment constrains a station. Adding staff can
only be represented today by raising `cap`, which silently adds equipment as well. That is exactly the false
inference the requirements rule out.

## 2. Modelling principle: four separate things

| Concept | Meaning | Changed by |
|---|---|---|
| **Equipment** | Physical positions and machines: probes, weighbridge bays, pits, load points, lab benches | Site configuration (unchanged) |
| **Labour requirement** | Which tasks need how many operators of which skill, and for which part of the task | Site configuration (`labour`) |
| **Operator pools** | Groups of operators with given skills, and their availability over the day | Staffing: baseline (verified) or scenario |
| **Task time** | Service-time distributions | Unchanged by default. More operators shorten a task **only** if a crew-size time table is explicitly configured and verified. |

A task starts only when its equipment **and** its operators are available, reserved in one atomic transaction, the
same ledger mechanism as routes and bays. More operators never create parallel equipment. A second sampler operator
does nothing for a single probe unless the configuration says one task can use two people, and how that changes its
duration.

## 3. Proposed configuration (software-independent)

```json
"operator_pools": [
  {"id": "samplers", "name": "Sampling operators", "skills": ["sample"],
   "staffing": {"baseline": [{"from": "06:00", "to": "18:00", "count": 1}]},
   "verified": false}
],
"labour": [
  {"step": "sample", "pool": "samplers", "operators": 1, "held": "whole_task"},
  {"step": "weigh_in", "pool": "weighbridge_clerks", "operators": 1, "held": "whole_task"}
],
"staffing_scenarios": {
  "plus_one_seasonal_sampler": {"samplers": [{"from": "06:00", "to": "18:00", "count": 2}]},
  "reassign_clerk_to_sampling": {"weighbridge_clerks": [...], "samplers": [...]}
}
```

- **`operator_pools`:**
  - Each pool has skills (the task steps its operators may do) and a staffing schedule (count by time window).
  - A pool with several skills is **shared**; separate pools are **dedicated**.
  - `verified: false` marks unconfirmed inputs; it is reported in every result.
- **`labour`:** per task step, the pool and number of operators.
  - `held` says when the operators are needed: `whole_task` (default proposal), or `start_only` (e.g. a clerk who
    only issues a ticket). The choice is for the manager to confirm.
  - Steps without a `labour` entry are **automated or not labour-constrained**. That is today's behaviour, so all
    existing configurations are unchanged.
  - Candidate steps: `sample`, `grade` (lab staff), `weigh_in`, `weigh_out`, `tip` (pit attendant), `load` (setup
    and/or whole load), and intake-transfer start (control room).
- **Optional `crew_time`:** a table of task-time multipliers by crew size, e.g. `{"sample": {"1": 1.0, "2": 0.8}}`.
  Absent means no effect. It may be used only with verified figures.
- **Staffing scenarios:** a run or experiment selects one (precedence: experiment > site baseline), like queue
  policies. The result records which staffing was used and whether it is verified.
- **Schedule changes:** when a pool's count drops (end of a seasonal shift), operators finish their current task.
  No pre-emption (assumption L4).

## 4. Engine extension (smallest, for later implementation)

1. Operator pools as counted resources in the reservation ledger (a new `LabourClaim`), with time-varying capacity
   from the staffing schedule.
2. Each station, tip, load or transfer start adds its `labour` claims to the transaction that reserves its
   equipment. All or nothing. New waiting reason: `LABOUR_UNAVAILABLE`.
3. Operators are released at task end (`whole_task`) or at task start (`start_only`).
4. Staffing schedule events change pool capacity; a re-check runs when capacity rises.
5. Optional crew-time multipliers, applied only where configured.
6. Results:
   - per pool: utilisation (busy operator-minutes / available operator-minutes) by hour and day;
   - per truck and step: labour waiting, kept apart from equipment waiting;
   - per resource: a constraint indicator (§5).
7. Audit invariants:
   - operators in use never exceed the scheduled count;
   - every labour-requiring task held its operators for its whole required phase;
   - no task ran without its equipment.
8. Defaults: no pools, no labour, so behaviour, fingerprints and both evidence packages reproduce unchanged.

## 5. Constraint analysis (reassessed after every staffing change)

For each resource (equipment positions and operator pools), each run reports:
- **utilisation**;
- **waiting attributed to it** (trucks waiting with reason `EQUIPMENT_BUSY` for that equipment, or
  `LABOUR_UNAVAILABLE` for that pool), in truck-minutes;
- **share of total waiting.**

The **binding constraint** is the resource with the largest attributed waiting. Experiments report it per scenario
and demand level. When a staffing change relieves one constraint, the next one (for example the weighbridge, the
hoppers or the downstream grain line) shows up in the same table. No staffing change is credited with an
improvement that the table does not show.

## 6. Information required from the silo manager (all currently unknown)

| # | Question | Affects |
|---|---|---|
| M1 | Which tasks need an operator: sampling, grading, weighing in/out, tipping supervision, load-out (setup / whole load), transfer control? Which are automated? | `labour` entries |
| M2 | For each task, how many operators, and for which part (whole task, start only, setup only)? | `operators`, `held` |
| M3 | Are operators dedicated to one station or shared (e.g. one person for sampling and weighbridge)? Who may be reassigned, and how quickly? | Pools and skills; reassignment scenarios |
| M4 | Baseline staffing per role in average, busy and peak periods; shift times; breaks | Staffing schedules (baseline) |
| M5 | Seasonal staff: how many can be hired, for which roles, from when, with what training limits? | Feasible scenarios |
| M6 | Equipment limits that staff cannot overcome: number of probes, weighbridge bays, unloading positions, lab benches, load points | Equipment configuration (check against current site data) |
| M7 | Does a second operator ever shorten a task (e.g. two people at a probe)? By how much? | `crew_time` (absent unless verified) |
| M8 | What defines average, busy and peak demand (truck arrivals per hour and day, commodity mix)? | Demand levels in experiments |
| M9 | Is there a control-room operator for transfers? Can one person run several transfers at once? | Transfer labour |
| M10 | Staffing costs per role and period, if cost is to be reported beside performance | Cost reporting (kept apart from performance) |

## 7. Provisional modelling assumptions (until M1-M10 are answered)

- **L1** Tasks without verified labour data are treated as not labour-constrained (today's behaviour).
- **L2** Operators are needed for the whole task unless verified otherwise.
- **L3** No crew-size effect on task times.
- **L4** No pre-emption at shift changes; a running task is finished.
- **L5** No walking time when a shared operator moves between stations.
- **L6** Operators are interchangeable within a pool (equal skill and speed).

## 8. Experiment design (after verification; separately versioned)

- **Sites:** controlled Site S (grain handling cannot confound), plus the verified site configuration once
  available.
- **Factors:**
  - demand level: average / busy / peak, as defined by M8;
  - staffing: baseline / each feasible seasonal addition / each feasible reassignment, as defined by M4 and M5.
- **Common random numbers** (arrivals, service draws). 20 or more replications. Paired comparisons against
  baseline staffing, Holm-adjusted.
- **Measures:**
  - turnaround and waiting by truck class;
  - labour waiting versus equipment waiting;
  - throughput;
  - equipment utilisation and operator utilisation;
  - the binding constraint per cell (§5).
- **Reporting** keeps three categories apart:
  - **baseline staffing:** verified actual;
  - **scenario staffing:** evaluated alternatives;
  - **recommended staffing:** supported by results, subject to cost, feasibility and managerial judgement.

  Performance gains are reported separately from staffing cost. No recommendation is made from unverified inputs.
- **Verification before the experiment:** hand-traced tests, for example:
  - one probe with two operators: no gain without `crew_time`;
  - one shared operator for sampler and weighbridge: tasks serialise;
  - a seasonal shift ending: running tasks finish, new ones wait;
  - labour and equipment reserved atomically;
  - audit sensitivity to over-allocation.

## 9. Implementation (framework only; no staffing experiment)

**Implemented as designed in §3-§4:**

| Area | What exists |
|---|---|
| Configuration | `operator_pools` (skills, daily schedule windows, `verified`); `labour` (step, pool, operators, `held`: `whole_task` / `start_only`; steps `sample`, `grade`, `weigh_in`, `weigh_out`, `tip`, `load`, `intake`); `staffing_scenarios` (replacement schedules and/or operators per step); `crew_time` (task-time factor by crew size). All empty by default; left out of the configuration hash when empty. |
| Validation (`_validate_staffing`) | Unknown pools; missing skill; a requirement that can **never** be met by the schedule (baseline or scenario); bad shift times; crew-time factors (positive; station tasks and tipping only) |
| Ledger | `LabourClaim` reserved in the **same transaction** as the task's equipment. Waiting reason `LABOUR_UNAVAILABLE`. Pool capacity follows the schedule; a drop never interrupts a running task. |
| Engine | Labour wired into truck stations, sampling at a weighbridge bay (and weighing on the held bay), grading, tipping, loading and intake-transfer start. `TruckFlowModel(staffing=...)` selects a scenario. Durations change only through `crew_time`. |
| Results | `staffing` (scenario; per pool busy and available operator-minutes, utilisation, verified); `labour_use` (one record per task with its operators); `waiting_attribution` (truck-minutes per waiting reason and resource, the constraint table of §5). All empty when no labour is configured. |
| Assumptions in results | The labour assumptions (L2-L5) and the list of **unverified** pools are added to every run that uses them. |
| Audit | Operators in use at any task start never exceed the scheduled count; every truck task needing labour held its operators for the required phase. |

**Verification:**
- **New tests:** `tests/test_staffing.py`, 16 tests, hand-traced. They cover:
  - no labour configured changes nothing;
  - one shared operator serialises sampling and weighing (exact timeline and the waiting split: 14 truck-minutes for
    labour, 11 for the sampler);
  - a second operator at a single probe gives no gain without `crew_time`;
  - `crew_time` applies only where configured;
  - a shift end doesn't interrupt a running task;
  - a scenario changes staffing without changing equipment;
  - `start_only` versus `whole_task`;
  - atomic reservation of labour and equipment;
  - validation;
  - audit sensitivity to over-allocation and to a task without its operators.
- **Full suite:** 378 passed, 2 expected failures (all 362 earlier tests unchanged).
- **Backward compatibility:** the version-tolerant fingerprint (32 runs) and the configuration hashes are identical.
  Reproduction of `paper2-v1` and `paper2-ext-sampling-v1` with the new engine is recorded in §10.

**Not done, by instruction:**
- No staffing experiment.
- No operator counts, shifts or policies for any real site.
- All test pools are marked unverified.

The experiment of §8 waits for answers to M1-M10.

**Limitations of the framework:**
- **Schedules** repeat daily, with no breaks unless entered as separate windows.
- **Operators** are interchangeable within a pool (L6), with no walking time (L5).
- **During an equipment outage** a suspended transfer or load keeps its operators (consistent with I1, hold).
- **`crew_time`** applies to station tasks and tipping only, not loading or transfers.
- **The audit's "held its operators" check** covers truck tasks; for grading and transfers only the capacity check
  applies.
- **Waiting attribution:** a truck waiting for two reasons at once is counted under each.

## 10. Reproduction with the staffing engine (2026-10-25)

With the staffing framework in place and no operators configured:
- **`paper2-v1`:** all 84 compared deterministic experiment files identical. Excluded: engine-digest and test-run
  files.
- **`paper2-ext-sampling-v1`:** all 105 deterministic files identical.
- **Fingerprint and hashes:** version-tolerant engine fingerprint (32 runs) and configuration hashes identical.
- **Tests:** 378 passed, 2 expected failures.
- **No site staffing anywhere:** no site or evidence configuration contains operator pools or labour requirements.
  The only staffing values are the test inputs in `tests/test_staffing.py`, all marked unverified.

## 11. Shared unloading workers by task (2026-10-25)

**Confirmed (user):** about four unloading workers are **shared between Silo A and Silo B**, not four per silo.
Unloading includes manual tasks: guiding and positioning trucks, assisting the discharge, scraping and sweeping
spilled grain into hoppers. The objective is to find appropriate staffing by simulation, not to assume today's
staffing is optimal.

### 11.1 Configuration (`unloading_labour`, optional; absent = unchanged behaviour)

```json
"operator_pools": [{"id": "unloaders", "skills": ["tip"], "verified": false,
                    "schedule": [{"from": "07:00", "to": "18:00", "count": 4}]}],
"unloading_labour": {
  "pool": "unloaders",
  "allocation": "oldest_task_first",
  "tasks": [
    {"id": "position",  "operators": 1, "time": [1, 2, 4]},
    {"id": "discharge", "operators": 0, "time": "tip"},
    {"id": "scrape",    "operators": 1, "time": [2, 3, 6]},
    {"id": "sweep",     "operators": 1, "time": [2, 4, 8], "truck_present": false}
  ]
}
```

All numbers above are placeholders, not Ventersdorp data.

| Requirement (user) | How it is represented |
|---|---|
| 1. Workers dynamically assignable to either silo | One pool; a task at any hopper draws from it. No worker belongs to a silo or hopper |
| 2. Both silos operate simultaneously, subject to workers and equipment | Each task starts only when its hopper (first task, atomically with the hopper and pit space) and its workers are free |
| 3. A worker cannot do two tasks at once | The pool's scheduled count caps workers in use (ledger), and the flow audit checks it independently |
| 4. Manual activities | A configurable ordered task list per unloading. Tasks with the truck present run in order while the truck holds the hopper. Tasks after the truck occupy workers only |
| 5. Workforce per normal, busy and peak period | Staffing scenarios replace the pool's schedule (e.g. scenarios `busy`, `peak`). Scenarios may also change a task's workers (`labour: {"tip:scrape": 2}`) |
| 6. Staffing levels against targets | `experiments.staffing_search.minimum_workforce` (§11.3). It reports every level's turnaround, completion, tonnage, overtime and worker use, so trade-offs between levels are visible. The smallest level meeting all targets is one output, not the objective (approved correction C3: balance turnaround, throughput, overtime and labour) |
| 7. No dedicated operator per hopper assumed | Workers are required **per task** (0 allowed, e.g. a discharge needing nobody). Between tasks a truck releases its workers; it waits on the hopper if none are free for its next task |

**Allocation rules** (configurable until the actual arrangement is verified):
- `oldest_task_first`: any waiting task that fits the free workers may start, oldest request first.
- `strict_order`: no task starts while an older task is waiting.
- `started_trucks_first`: tasks of trucks already at a hopper come before new trucks and cleaning.

The first task's workers are claimed together with the hopper, so a new truck's first task competes under the hopper
queue's policy.

### 11.2 Provisional assumptions (reported with every run)

- **No walking time** between hoppers or silos. This may understate the cost of sharing workers between silos.
- **Cleaning after the truck** (`truck_present: false`) does not hold the hopper (Q-3 of the calibration plan).
- **Task times do not depend on the number of workers.** Crew-time factors are not available for tasks. Task workers are fixed per task, or per scenario.
- **Running tasks finish** at a shift end (as for other labour).
- The **discharge task uses the hopper's tipping time**. Grain enters the pit when it ends, so intake may start while scraping goes on.

### 11.3 Staffing levels against targets

`minimum_workforce(site, pool, levels, targets, replications, …)` runs every level over the same seeds (common
random numbers). It sets the pool's count to the level in each shift window that has workers.

**Targets** (any subset):
- mean turnaround of completed trucks (reported with the completion rate);
- completion rate;
- tonnes received;
- overtime after closing on the last day. Overtime needs every admitted truck finished; a replication that did not clear fails it.

**How a level is judged:**
- Criterion `ci` (default) uses the conservative 95% CI bound; `mean` uses the mean.
- A level with any stalled or invalid replication fails (MEASUREMENT_FRAMEWORK §3).
- Every level is reported. A non-monotonic result is flagged.
- The result states that it is a calculation on unverified inputs and not a staffing recommendation.

No Ventersdorp staffing experiment has been run. That waits for the calibration plan's acceptance criteria (AC-1 to
AC-10) and the staffing questions (M1–M10, Q-3, Q-6, Q-9).

### 11.4 Verification (tests/test_unloading_labour.py, hand-traced)

| Test | Proves |
|---|---|
| Two workers serve both silos at once | Requirements 1 and 2 |
| One worker cannot do two tasks | Requirement 3; the truck waits on the hopper for its next task's worker; waiting attributed to the pool |
| Allocation rule is configurable | `oldest_task_first` and `started_trucks_first` give the hand-traced orders |
| Cleaning occupies workers, not the hopper | Requirement 4 and its provisional assumption |
| Workforce per period is a staffing scenario; a scenario can change a task's workers | Requirement 5 |
| Stochastic task times leave the discharge draw unchanged | Common random numbers |
| Invalid configurations refused (8 cases); audit detects a task without its workers and over-use of the pool | Validation and the independent audit |
| Minimum workforce meets turnaround and overtime targets; failed runs count against a level | Requirement 6 |

The flow audit now takes a lot's tipping time from the discharge task when unloading tasks are configured. It checks
that this time lies within the truck's unloading step.
