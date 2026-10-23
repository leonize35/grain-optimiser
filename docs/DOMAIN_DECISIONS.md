# Domain rules specification — confirmed decisions D1–D6 and storage bins (R7)

Decisions confirmed by the domain owner on 2026-10-22. This file specifies each rule **before implementation**: configuration parameters, expected behaviour, edge cases and verification tests.

Tags used throughout:
- **[CONFIRMED]** physical or operating rule confirmed by the domain owner; the engine must implement it.
- **[SITE INPUT]** behaviour that differs per silo; it is a configuration parameter, and its value must come from the site.
- **[ASSUMPTION]** a modelling choice made by the engineer, not yet confirmed. It is listed in §8 for review.
- **[DEFAULT]** what the engine does when a site has not supplied a value. Every default is reported in the run's assumptions list. None is silent.

No site's layout (including Ventersdorp) appears in engine code. Sites differ only by configuration.

Field names below are proposals for the configuration schema (schema v2). Existing prototype fields keep working, and missing new fields take the default.

---

## R1 (D1) Grain transfer equipment: shared, independent and hybrid routes

**Rules**
- [CONFIRMED] The physical connections (typed directed graph) are the only source of possible routes. Example: H1/H2 → bottom conveyor A and H3/H4 → bottom conveyor B is expressed purely as edges.
- [CONFIRMED] Different commodities never overlap on the same commodity-locked equipment at the same time.
- [CONFIRMED] Separate routes (no shared equipment) may carry different commodities at the same time.
- [CONFIRMED] Concurrent feed of compatible grain onto shared equipment is allowed **only** where the equipment is configured to support it, and the combined flow may not exceed that equipment's transfer capacity.
- [ASSUMPTION A1] When two streams merge onto one piece of equipment, they cannot be separated again, so they must share the **entire remaining path to the same bin**, and both must be compatible with that bin (commodity *and* grade, R4).

**Configuration** (per conveyor or elevator)

| Field | Type | Meaning | Default |
|---|---|---|---|
| `rate` | t/h | Rated transfer capacity | required |
| `max_concurrent_feeds` | int ≥ 1 | How many streams may feed it at once | **1** [DEFAULT]: exclusive, as in the prototype |
| `commodity_locked` | bool | Carries one commodity at a time while grain is on it | `true` |
| `clear_minutes` | minutes ≥ 0 | Time for the last grain to leave the equipment after the feed stops (route held until clear) | **0** [DEFAULT, SITE INPUT] |

**Expected behaviour**
- A stream may start on a segment if: active streams < `max_concurrent_feeds`; the segment is idle, or every active stream has the same commodity (and grade, A1); and no changeover is in progress (R3).
- With *n* streams sharing a segment, the combined rate is capped at that segment's `rate`. [ASSUMPTION A2] The capacity is shared equally (each stream gets `rate / n` on that segment, and a stream's speed is the slowest of its segments). When a stream joins or leaves, the remaining tonnes of the others are recomputed and their completion events rescheduled.

**Edge cases:** a merge where the downstream paths differ is refused (blocked reason `MERGE_PATH_DIFFERS`); a commodity mismatch is refused (`COMMODITY_LOCK`); an equipment rate of 0 is caught by configuration validation; a stream finishing early speeds up the remaining stream.

**Verification tests** (hand-computed)
- T1.1 Independent routes: maize on line A and soybeans on line B both start at 07:00. Neither waits.
- T1.2 Exclusive shared elevator (`max_concurrent_feeds` = 1): lot 1, 30 t at 200 t/h, runs 07:00–07:09. Lot 2, arriving at 07:01, starts at 07:09 and ends at 07:18.
- T1.3 Concurrent (= 2), same commodity and same bin: both 30 t lots run at 100 t/h each, 07:00–07:18.
- T1.4 Concurrent (= 2) but different commodity: the second lot waits as in T1.2.
- T1.5 Concurrent (= 2), same commodity but different destination bins: refused, `MERGE_PATH_DIFFERS`.
- T1.6 In T1.3, lot A is only 15 t: A runs 07:00–07:09 at 100 t/h. B has 15 t left at 07:09, then runs alone at 200 t/h and ends at 07:13:30.

## R2 (D2) Hopper pit inventory and truck tipping

**Rules**
- [CONFIRMED] Pit inventory and its discharge are modelled separately from the truck. A truck can finish tipping before its grain reaches the bin.
- [CONFIRMED] A truck may only start tipping when the pit has enough available capacity and the operating rules allow it.
- [SITE INPUT] Partial tipping, and whether a truck must wait for the pit to be clear.
- [ASSUMPTION A3] Pit level falls **continuously** while discharging, so space becomes available gradually. The prototype frees space only when a whole transfer finishes. Continuous is more realistic but differs from the prototype.
- [ASSUMPTION A4] A pit holds one commodity and grade at a time, unless the R4 mixing rules allow two grades together.

**Configuration** (per hopper): `cap_t`, `rate` (discharge t/h), `tip` (tipping time distribution), `accepts` (commodity/grade list, R4), and:

| Field | Values | Meaning | Default |
|---|---|---|---|
| `tip_admission` | `full_load_space` / `partial` / `empty_pit` | When a truck may start tipping | `full_load_space` [DEFAULT]: as in the prototype |

**Expected behaviour**
- `full_load_space`: start when free space (capacity − level − already-claimed space) ≥ truck load.
- `empty_pit`: start only when the pit is empty.
- `partial`: tip what fits, then wait for space for the remainder. **Not implemented until confirmed.**
- The truck is released when tipping ends. The grain becomes a lot in the pit, carrying the truck id, commodity, grade and kilograms.

**Edge cases:** a load larger than the pit is a configuration error (already validated); tipping while the pit is discharging is allowed; a truck waiting for space gets a re-check event scheduled at the exact time enough space will exist (A3).

**Verification tests**
- T2.1 After tipping, the truck proceeds to weigh-out while its lot is still in the pit.
- T2.2 `full_load_space`: 60 t pit holding 40 t yellow maize and discharging at 200 t/h from 07:00. A 30 t truck arrives at 07:00 and needs 10 t of space, which takes 3 min, so tipping starts at **07:03**.
- T2.3 `empty_pit`, same situation: 40 t at 200 t/h takes 12 min, so tipping starts at **07:12**.
- T2.4 Pit holds yellow maize and a white maize truck arrives: it waits until the pit is empty (A4).

## R3 (D3) Commodity changeovers: configurable clearance

**Rules**
- [CONFIRMED] Commodities stay segregated along the whole route.
- [CONFIRMED] A route is released only when the required equipment is clear and any configured cleaning or changeover conditions are met.
- [CONFIRMED] Changeover requirements come from a **commodity-pair matrix**; different pairs may differ. No changeover time is hard-coded. The earlier 5- and 8-minute figures were estimates, not measurements.
- [SITE INPUT] All matrix values.
- [ASSUMPTION A5] When several segments of a route need a changeover, they are cleared **in parallel**, so the route waits for the longest one, as in the prototype. The alternative is in sequence (sum of times).

**Configuration** (site level)

```json
"changeovers": {
  "default_minutes": null,
  "rules": [
    {"from": "YM", "to": "WM", "minutes": 10, "equipment": "*"},
    {"from": "WM", "to": "YM", "minutes": 0},
    {"from": "YM:2", "to": "YM:1", "minutes": 4, "equipment": ["elevator"]}
  ]
}
```

- `from` / `to`: a commodity, or `commodity:grade` for grade-level rules. Rules may be asymmetric.
- `equipment`: `"*"`, a list of equipment types, or equipment ids. The most specific rule wins (id over type over `*`).
- `default_minutes`: `null` means *no default*. Any commodity pair that can meet on shared equipment without a rule is then a **configuration error**, naming the pair and the equipment.
- [SITE INPUT, later] `flush_tonnes` and a destination bin for volume-based flushing. Specified only, not implemented until a site confirms it.

**Expected behaviour:** a segment remembers the last commodity and grade it carried. A new stream with a different commodity (or grade, if a grade rule exists) triggers the changeover. The route is reserved during the changeover, and no grain moves. The changeover is recorded per segment and reported. First use of a segment needs no changeover.

**Edge cases:** a 0-minute rule (a recorded changeover with no delay); a missing rule with no default (configuration error); a long idle period (residue still counts, so the changeover is still needed); `clear_minutes` (R1) applies before release even with no commodity change.

**Verification tests**
- T3.1 Asymmetric pair: yellow → white maize 10 min, white → yellow 0 min. A 30 t white maize lot after yellow maize at 200 t/h takes 10 + 9 = 19 min.
- T3.2 Missing rule and `default_minutes` null: validation error "No changeover rule for Yellow maize → Soybeans on Elevator 1".
- T3.3 Two segments needing 6 and 10 min: the route waits **10 min** (A5).
- T3.4 `clear_minutes` 2 on the elevator: the route is released 2 min after the last tonne is fed.

## R4 (D4) Commodity and grade drive storage allocation

**Rules**
- [CONFIRMED] Every lot carries commodity **and** grade, and the engine tracks both everywhere (truck, sample, pit lot, transfer, bin).
- [CONFIRMED] Storage compatibility uses commodity, grade and explicitly permitted mixing rules. Grain of the same commodity cannot automatically share a bin.
- [CONFIRMED] Where the configured process requires it, grading must be completed and matched to the correct truck (by sample id) before unloading.

**Configuration**
- Commodity: `grades: ["1", "2", "3"]`.
- Bin: `accepts: [{"commodity": "YM", "grades": ["1"]}]`. If omitted, the bin accepts every grade of its listed commodities, but only after an explicit setting `grade_segregation: "none"` (otherwise a configuration error).
- Site `grade_mixing: [{"commodity": "YM", "grades": ["1", "2"], "result": "2"}]`: these grades may share a bin (or pit), and the mixture is classified as `result`. No rule means no mixing.
- Truck process: the `grade` step before `tip` in the unloading sequence means "grading must be complete before tipping".
- Demand: `grade_mix` per commodity (stochastic runs). Scripted trucks state their grade.

**Expected behaviour:** hopper and bin selection use the graded commodity and grade. A truck whose grading result is not yet back cannot tip, even if a hopper is free. Results returning out of order are matched by sample id.

**Edge cases**
- A grade arrives that no reachable bin accepts: configuration error.
- Grade-restricted bins, but grading happens *after* tipping (grade unknown at allocation): configuration error.
- Mixing changes the bin's grade, e.g. a grade-1 lot into a grade-2 bin stays grade 2.
- A rejected truck leaves without tipping.

**Verification tests**
- T4.1 Grade-2 maize is never placed in a grade-1-only bin.
- T4.2 With the mixing rule {1, 2 → 2}, grade-1 grain goes into a grade-2 bin, and the bin stays grade 2.
- T4.3 No bin accepts yellow maize grade 3, which arrives: configuration error.
- T4.4 Scripted: truck A's grading result returns after truck B's. A cannot tip before its own result, and B's result never releases A.
- T4.5 Grade-restricted bins with grading after tipping: configuration error.

## R5 (D5) Physical truck queues, staging and blocking

**Rules**
- [CONFIRMED] Unlimited waiting space is allowed only as an explicitly documented simplification.
- [CONFIRMED] The engine supports finite staging areas, physical truck connections, and blocking when downstream space is unavailable.
- [SITE INPUT] Staging capacities, and whether a full queue can block a weighbridge.
- [ASSUMPTION A6] A truck that has finished service but cannot enter the next area **stays on the station and blocks it** (blocking after service). The station is released when the truck physically leaves, not when service ends.

**Configuration**

```json
"truck_areas": [
  {"id": "gate", "name": "Road queue", "capacity": null},
  {"id": "yard", "name": "Hopper waiting area", "capacity": 6}
],
"truck_paths": {"unload": ["gate", "sample", "grade", "weigh_in", "yard", "tip", "weigh_out"]}
```

- `capacity: null` means unlimited, and this is reported as a simplification in the run's assumptions.
- Paths alternate areas and service steps, so they are a typed truck graph, separate from the grain graph.
- [SITE INPUT] `deadlock_prevention`: `reserve_next_space` (a truck may start a service only if a place is reserved in the area after it) or `detect_only`.

**Expected behaviour:** before moving on, a truck must claim a place in the next area. If none is free, it stays where it is and keeps that station busy. Weighbridges used in both directions, combined with finite areas, can deadlock. This is either prevented (`reserve_next_space`) or detected and reported as a run failure; it is never silently ignored.

**Edge cases:** every area unlimited reproduces today's behaviour; an area of capacity 0 is a configuration error; a circular wait between weigh-in and weigh-out across a full yard (see T5.3).

**Verification tests**
- T5.1 All areas unlimited: identical times to the current non-blocking model.
- T5.2 Yard capacity 1, occupied by a truck waiting for a busy hopper. The next weighed truck stays on the weighbridge, and a third truck's weigh-in waits. Times are hand-computed.
- T5.3 Shared in/out weighbridge with a full yard: under `detect_only`, the deadlock is reported with the trucks involved; under `reserve_next_space`, no deadlock occurs.

## R6 (D6) Operating hours, admission cut-off and unfinished work

**Rules**
- [CONFIRMED] Every unfinished truck is reported with its waiting time. None silently disappears from performance reporting.
- [CONFIRMED] Admission cut-off, operating hours and overtime rules are configurable.
- [CONFIRMED] In multi-day scenarios, unfinished trucks carry over according to the site's policy.
- [ASSUMPTION A7] A service in progress at the hard stop (e.g. tipping) is completed. Grain transfers already running may finish if `transfers_after_close` allows it.

**Configuration**

| Field | Meaning | Default |
|---|---|---|
| `hours.open`, `hours.close` | Operating hours | required |
| `hours.admission_cutoff` | Last time a new truck may enter (per activity optional) | = `close` [DEFAULT] |
| `hours.overtime_minutes` | Service continues after close up to this | 0 [DEFAULT] |
| `end_of_day.unfinished_trucks` | `carry_over` (next opening, original arrival time kept) or `turned_away` (counted as lost) | `carry_over` [DEFAULT, SITE INPUT] |
| `end_of_day.late_arrivals` | Trucks arriving after cut-off: `queue_for_next_day` or `turned_away` | `queue_for_next_day` [DEFAULT, SITE INPUT] |
| `end_of_day.transfers_after_close` | Pits and conveyors keep running until clear: `true`/`false` | `true` [ASSUMPTION] |

**Expected behaviour:** KPIs report (a) completed-truck statistics and (b) unfinished trucks: count, plus waiting time so far (censored at the end of the run). They also report (c) turned-away trucks. Turnaround including unfinished trucks is shown as a lower bound. Grain in pits and bins always carries over.

**Verification tests**
- T6.1 The last truck cannot finish: it is reported as unfinished, with a hand-computed waiting time.
- T6.2 Two-day run: an unfinished truck is first in the day-2 queue, and its turnaround spans the night from its original arrival.
- T6.3 Arrival after cut-off with `turned_away`: counted as turned away, not in the queue.

## R7 Storage bins

**Rules [CONFIRMED]** Each bin tracks capacity, current tonnage, fill percentage, commodity, grade, incoming reservations, outgoing commitments and availability. A bin's allowed commodity and grade may change over time, but a change must never overwrite existing inventory or violate segregation.

**Configuration:** `capT`, `accepts` (R4), opening stock (`inv`, `invCommodity`, `invGrade`), `in_service` (default true), and later `assignment_schedule` (timed changes of `accepts`).

**State and behaviour** (quantities in whole kilograms)
- `free_space` = capacity − tonnage − incoming reserved.
- `available_stock` = tonnage − outgoing committed.
- The bin's identity (commodity, grade) comes from its contents. If it is empty, the identity comes from its pending incoming reservations. If neither exists, it is unassigned (any allowed grain may come).
- `reserve_incoming(c, g, kg)` succeeds only if the bin is in service, (c, g) is allowed, the grain is compatible with the identity (including mixing rules), and kg ≤ free space. It is all-or-nothing: on refusal nothing changes, and reasons are returned.
- `receive(reservation, kg)` must not exceed what was reserved. The unused remainder can be released.
- `reserve_outgoing(c, kg)` requires kg ≤ available stock and a matching commodity. `dispatch(reservation, kg)` removes the grain.
- When tonnage reaches 0 with no reservations, the identity is cleared.
- `reassign(accepts)` is refused if current contents or pending reservations would violate the new assignment. Otherwise it takes effect for future grain only.
- [ASSUMPTION A8] An out-of-service bin accepts no new incoming or outgoing reservations. Reservations already made are honoured.

**Invariants (checked independently):** 0 ≤ tonnage ≤ capacity; tonnage + incoming reserved ≤ capacity; outgoing committed ≤ tonnage; contents and all pending incoming have one compatible identity.

**Verification tests:** tests/test_storage_bin.py (implemented in this step).

---

## 8. Assumptions awaiting your confirmation

| Id | Assumption | Alternative |
|---|---|---|
| A1 | Merged streams must share the whole remaining path to the same bin | Diverters after merge points (would need explicit modelling) |
| A2 | Shared capacity is split equally between concurrent streams | Proportional to each pit's discharge rate |
| A3 | Pit level falls continuously during discharge | Space frees only when a whole lot has left (prototype) |
| A4 | A pit holds one commodity and grade at a time (unless mixing rules allow) | Pits may hold mixed grades |
| A5 | Changeovers on several segments run in parallel (longest wins) | In sequence (sum) |
| A6 | Blocking after service: a truck stays on the station until it can move on | Trucks wait elsewhere (no blocking) |
| A7 | A service in progress at the hard stop is completed; transfers may run until clear | Everything stops at the hard stop |
| A8 | Out-of-service bin: no new reservations; existing ones honoured | Existing reservations are also cancelled |

## 9. Open question found by simulation (2026-10-23)

**Q1. Starvation under feasible-first with single-commodity pits.** On prototype Site A at +20 % demand, under
feasible-first, white maize and soybean trucks waited on average 165–170 min for a hopper, against 63 min for
yellow maize, with worst cases over 8 hours. Three rules combine to cause this:
- feasible-first lets later trucks overtake blocked ones;
- each pit holds one commodity at a time (A4);
- trucks prefer a pit that already holds their grain (the prototype's rule).

With continuous drain (A3), yellow maize keeps both pits busy, so other commodities rarely get one. Under strict
FIFO the waits even out (about 127–159 min mean for every commodity). The overtake count per truck is already
recorded; no limit is applied.

**Options to decide:**
- (a) leave as is, and report fairness (per-commodity waits, maximum overtakes);
- (b) an anti-starvation rule: after a truck has been overtaken N times, or has waited M minutes, it may not be
  overtaken any further;
- (c) reserve a pit for a commodity that has waited too long;
- (d) a different default policy.

**What happens at real silos?** Do staff hold back trucks of the main commodity to let others in?

**Decision (2026-10-23, domain owner): report only, for now.**
- Starvation reporting stays separate from queue selection. The FIFO and feasible-first policies are unchanged. (The prototype's batch policy has not been ported yet.)
- Every result records, per truck: total waiting time (time on site not in service, including gate, queues, waiting for a grading result and time blocked on a station); the number of times later-arriving trucks overtook it; and whether it was still unfinished (or turned away) at the end.
- The starvation threshold is configurable per site: `fairness.starvation_wait_minutes` (default 120, listed in the run's assumptions when not set) and optionally `fairness.starvation_overtakes`. A truck is counted as starved when it reaches either.
- Per-commodity waits, maximum overtakes and starved counts are experiment figures, so they can be compared across replications.
- **Later:** overtaking limits as an *optional* queue-management policy (e.g. no further overtaking after N overtakes or M minutes), so fairness and throughput can be compared across silo configurations. Not implemented yet.

**Observed case-study practice (2026-10-23, domain owner): trucks are served in queue order.** This is recorded as the case-study baseline, *not* hardcoded:
- Queue-order service corresponds to the dispatch policy `strict_fifo`. The policy stays a run setting: `TruckFlowModel(policy=...)` and `run_experiment(policy=...)`, either one policy for every queue or a mapping per queue group (`sample`, `grade`, `weigh`, `tip`, `load`, `move`, `intake`).
- To reproduce the case study, run with `policy="strict_fifo"`. **Not changed:** `run_experiment`'s default is still `feasible_first`, so existing results do not shift silently. Whether to make `strict_fifo` the default (or move the policy into the site configuration) is open.
- No fairness intervention is active. Baseline figures for both policies are in `docs/audit/FAIRNESS_BASELINE.md`.

### 9.1 How queue order and overtaking are defined (verified 2026-10-23; ambiguities open)

Current definitions (`TruckMetrics`; tests in `tests/test_starvation_diagnostics.py`):
- **Queue entry**: the moment a truck reaches a step and starts waiting for it (`queue_entered[step]`). For the hopper this is `hopper_queue_entered`; **hopper admission** is the start of tipping (`hopper_admitted`, when the tipping lane and pit space are reserved), not entry through the gate (`gate_admitted`).
- **Overtake**: truck X overtakes truck Y when X starts a step while Y is still waiting in the same queue group, Y entered that queue first, **and** Y arrived at the gate first. Each start counts once per waiting truck. Completion order is irrelevant.
- `overtaken_by_later` counts every queue group; `overtaken_at_hopper` counts tipping only.

**Decisions (2026-10-23, domain owner)**, implemented as reporting in step 14 (docs/QUEUE_POLICY_DESIGN.md §4):
1. Record both gate-arrival order (`arrival_seq`) and queue-entry order (`queue_seq`). FIFO applies at the configured physical queue stage (per queue group). Gate-arrival fairness is reported separately (`hopper_admitted_ahead_by_later_arrivals`); the queue-stage count is `overtaken_in_queue`.
2. `overtaken_by_later` keeps its definition. It is optionally split into `overtaken_feasible` / `overtaken_infeasible` (configuration test of whether the waiting truck could use the overtaker's equipment).
3. Strict global FIFO (`strict_fifo`) and work-conserving feasible-first FIFO (`feasible_first`) stay distinct and configurable. The case-study description does not settle head-of-line blocking at parallel hoppers.
4. Simultaneous arrivals: deterministic arrival-sequence tie-breaker (script order; generated arrivals by time, backlog, activity, truck id).
5. `pre_opening_wait_min` and `operational_wait_min` are separated; `total_waiting_min` is unchanged.
6. Unfinished trucks' waits are right-censored (`wait_censored`), with completed-only and censored statistics kept apart.

The questions as originally raised:
1. **Gate arrival versus queue entry.** Q arrives 07:01 and reaches the hopper queue at 07:02. P arrived 07:00 but weighed slowly and reaches the hopper queue at 07:05. If P then tips before Q, it is **not** counted as an overtake, because P arrived first. Counting by queue entry alone would count it. Which does the site consider fair?
2. **Several hoppers form one queue.** A later truck admitted to *any* hopper while an earlier truck waits counts as an overtake, even if the waiting truck could not use that hopper (for example, a commodity the hopper does not take). An alternative is to count only hoppers the waiting truck could have used.
3. **What strict FIFO means with several hoppers.** `strict_fifo` is head-of-line across the whole hopper queue: a truck waiting for a busy or incompatible hopper also holds back later trucks that could use an idle one. Is this what "queue order" means on site? Or do trucks for a free hopper go ahead (e.g. separate queues per hopper or per commodity)? The prototype's weighbridge rule called `fifo` actually behaves like `feasible_first`.
4. **Ties.** Trucks with the same arrival time keep the order in the arrival script (or generation order).
5. **Waiting before opening.** Time at the gate before the plant opens counts as waiting and towards starvation. Should it?
6. **Unfinished trucks.** Their waiting runs to the last day's hard stop, so it is a lower bound. Turned-away trucks stop counting when sent away.

## 10. Interrupted transfers I1-I7 (2026-10-23): provisional

Accepted as a verified simplified modelling capability. I1-I7 are recorded as **provisional modelling assumptions**,
not confirmed silo practice; see `docs/INTERRUPTED_TRANSFERS.md` §8. In short:
- hold-and-resume is the default recovery;
- source, in-transit and destination quantities are accounted, without grain positions on equipment;
- changeover and setup behaviour during outages are future configurable rules;
- whole-route stoppage, with no accumulation or PLC sequences;
- immediate restart; restart delay and permissives come later;
- outages of transfer equipment only.

## Engineering decisions already taken

| Decision | Choice | Where |
|---|---|---|
| Time resolution | Whole milliseconds from midnight of day 1 | `sim/time.py` |
| Grain quantities | Whole kilograms; inputs at most 3 decimal tonnes | `domain/quantities.py` |
| Same-instant event order | Releases, then control, then arrivals; then scheduling order | `sim/calendar.py` |
| Scripted arrival at exactly closing time | Accepted (assumption, easy to change) | `inputs/scripted.py` |
