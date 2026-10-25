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
