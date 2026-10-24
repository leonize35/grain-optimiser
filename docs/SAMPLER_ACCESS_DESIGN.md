# Sampler access, physical queue blocking and sampler location: audit and design (Paper 2 extension)

Status: **design for review. Nothing implemented** (2026-10-24). The Paper 2 evidence package `paper2-v1`
(commit `6345377`, manifest sha256 `71ca9133…`) stays the baseline. Any experiment here will be a separately
versioned extension (`paper2-ext-sampling-v1`) and will not replace or alter baseline results.

## 1. Audit: what the engine supports today

| # | Distinction | Supported now? | How it is represented (code) | Gap |
|---|---|---|---|---|
| 1 | Whether a truck requires sampling | **No** | Steps are fixed **per activity** (`sequences.unload`). Every unloading truck performs `sample` if the sequence has it. `ScriptedTruck` has no sampling attribute. | A per-truck operational requirement |
| 2 | Every truck must physically join the sampler approach queue | **No** | Waiting areas (`truck_areas`) are **capacity counters, not ordered lanes**. Trucks in an area have no physical order. Order comes only from the queue policy, per service step (`QUEUE_GROUP`). A sampled and an unsampled truck heading for different steps are in different queues, so one never physically blocks the other. | Ordered single-file queues where only the front truck can leave |
| 3 | A truck not needing sampling can bypass the sampler queue | **No** | `truck_paths` gives **one path per activity**; there are no alternative branches. | Declared physical bypass paths, used only where they exist |
| 4 | Sampling at the weighbridge or at an upstream station | **Upstream only** | `sampler` and `weighbridge` are separate station types with separate lanes. A truck holds **exactly one place at a time** (`_occupy_station` releases the previous place). | Sampling in a weighbridge bay: one truck position holding the bay and the sampling resource together |
| 5 | Space between sampler and weighbridge can hold trucks | **Yes** | With a configured path: a finite `truck_area` between `sample` and `weigh_in`, or none. Without an area, the truck keeps the sampler lane until the weighbridge is free (blocking after service, A6; `test_staging.py`). | Only the time-averaged queue length is not reported (peak only) |
| 6 | Sampling and weighing simultaneously on different trucks, or in the same position | **Separate positions only** | Separate stations serve different trucks at once. The same-position case is not representable. | Same as row 4 |

**Related behaviour found by the audit:**
- **Grading-result wait:** a truck waits for its grading result **where it currently is** (`_advance`, step `grade`).
  If `grade` follows `sample` without a waiting area in between, the truck waits in the sampler bay and blocks it.
- **Unconfigured paths:** without a configured path, implicit unlimited areas between steps make trucks
  non-blocking. That is a simplification, listed in the run's assumptions.
- **No travel times:** moving between places is instantaneous.
- **Truck-path validation:** `_validate_truck_paths` requires a path's steps to equal the activity's sequence.

**Conclusion:** a configurable truck path does **not** model physical bypass restrictions. A path fixes the order of
places for every truck of an activity. It does not make trucks that skip a service still physically pass through,
or wait behind, the station that provides it.

## 2. Modelling principle: requirement versus layout

| Layer | Answers | Changed by |
|---|---|---|
| **Operational requirement** (per truck) | Does this truck need sampling? Which services must it receive? | Arrival data or a sampling rule |
| **Physical layout** (per site) | Which positions exist (ordered queues, holding areas, bays)? Can a truck leave a queue other than from the front? Is there a bypass? Where is the sampling resource? | Site configuration |
| **Queue policy** (unchanged) | Among requests that are physically able to go, which goes first? | `queue_policies` |

Physical order is a **feasibility constraint in the engine**, like route reservation. A queue policy cannot let a
truck pass another truck where the layout does not allow it. This keeps the policy/physics separation already
verified for Paper 2 (EV-P1).

## 3. Proposed configuration fields (software-independent)

**Operational:**
- `ScriptedTruck.requires_sampling` (arrival data, optional).
- `demand.<activity>.sampling_share`: a fraction, optionally per commodity. Each truck draws once from its own
  stream, keyed by truck id, so the requirement is identical across layout variants (common random numbers).
- Default: every truck whose activity sequence contains `sample` requires it, so existing configurations are
  unchanged.
- Trucks not requiring sampling skip the **services** `sample` and `grade`.

**Physical:**
- `truck_areas[].single_file: bool`, default `false` (today's behaviour). In a single-file area, trucks are ordered
  by entry and only the front truck may move to its next place. A truck behind it waits with reason
  `PHYSICAL_QUEUE_ORDER`, even if its own next place is free.
- `stations[].pass_through_minutes` (sampler bays; triangular `[a, m, b]`, default `[0, 0, 0]`). When the layout
  makes a truck traverse a sampler bay it does not need, the truck **occupies the bay for this time without
  service**: no sampling resource is used and no sample is taken.
- `truck_paths.bypasses`: a list of declared physical bypasses, e.g.
  `{"activity": "unload", "around": "S1", "from": "gate", "to": "between", "for": "not_sampled", "capacity": 2}`.
  The bypass leaves from a place the truck can actually reach. In S2 it starts at the gate, before the
  single-file approach: a truck already inside a single-file queue cannot leave it except from the front.
  A truck not requiring sampling uses the bypass **only if one is declared** from its current place. Otherwise it
  follows the full path and passes through the sampler bay. `capacity` is the number of trucks the bypass lane
  holds (`null` = unlimited, listed as a simplification).
- `equipment[sampler].located_at`: `{"weighbridge": "WB1", "lanes": [0]}` for a sampling probe at given weighbridge
  bays.
  - A sampled truck at such a bay holds **the bay lane and the sampler unit together** while sampling. It then
    keeps the bay lane for weighing; the sampler unit is released at the end of sampling.
  - `sampling_overlaps_weighing: bool` (default `false`: sampling, then weighing).
  - Trucks not requiring sampling may use any bay that serves their step. Sampled trucks only bays with a probe.
- Existing and unchanged: `truck_areas[].capacity` (holding space; 0 is expressed as no area between two steps),
  sampler and weighbridge `cap` (bays), `deadlock_prevention`.

**Where the grading result is awaited:** controlled by the position of `grade` in the sequence and path (unchanged).
The experiment uses `sample, weigh_in, grade, tip, weigh_out`, with the result awaited in the yard after weigh-in
(assumption O8).

## 4. Smallest engine extension (for later implementation, after review)

1. A per-truck `requires_sampling`, and skipping `sample`/`grade` for trucks that don't need them.
2. Single-file areas: an ordered entry list per area, and a front-of-queue check before a truck leaves it (engine
   feasibility, not policy).
3. Pass-through occupancy of a sampler bay: a lane claim for `pass_through_minutes`, without service or sample.
4. Declared bypasses: an alternative next place for trucks not requiring sampling, from the declared `from` place
   only.
5. A co-located sampler: one transaction reserving bay lane + sampler unit; the sampler unit released after
   sampling, the bay kept for weighing.
6. Reporting:
   - per truck: physically blocked time (ready, but behind another truck or with no place ahead) and pass-throughs;
   - per area: time-averaged and peak occupancy;
   - per station: busy, blocked-occupied and idle time.
7. Audit invariants:
   - no out-of-order exit from a single-file area except through a declared bypass;
   - no trucks that don't need sampling are sampled;
   - a sampler unit is held only together with the bay lane of the same truck (co-located);
   - existing conservation and segregation checks unchanged.
8. Defaults reproduce today's behaviour. Acceptance: the version-tolerant fingerprint is identical for all existing
   configurations, and the `paper2-v1` package reproduces unchanged.

## 5. Test configurations S1-S4 (deterministic, hand-traced)

**Shared resources in all four**, so only the layout differs:
- **Stations:** one sampling unit and two weighbridge bays (WB1#0, WB1#1).
- **Durations:** sampling 4 min, weighing 2 min, pass-through 0.5 min.
- **Simplifications:** no travel time; no grading step in these traces.

**Arrival script** (all at the gate):

| Truck | Arrives | Sampling |
|---|---|---|
| T1 | 07:00 | yes |
| T4 | 07:00 | yes |
| T2 | 07:00 | no |
| T3 | 07:01 | no |

Script order is T1, T4, T2, T3.

### S1: separate upstream sampler, no bypass, holding space for 1 truck between sampler and weighbridges

Layout: gate → single-file approach → sampler bay → holding area (capacity 1) → weighbridge bays.
S2 adds a bypass from the gate to the weighbridge: a truck that needs no sampling waits at the gate if both bays are
busy. (Implementation finding: a bypass into the one-place holding area gives no benefit. Under
`reserve_next_space`, the truck being sampled holds the promise of that place continuously, 07:00-07:08 in this
trace. This is tested as its own case.) In S4, trucks not needing sampling may pass a sampled truck
waiting at the front of the approach to reach the bay without a probe.

| Time | Event |
|---|---|
| 07:00 | T1 enters the sampler bay and is sampled 07:00-07:04. T4, T2 and T3 queue behind (single file). |
| 07:04 | T1 → WB bay 0, weighs 07:04-07:06. T4 enters the sampler bay, sampled 07:04-07:08. **T2 is blocked behind T4, although both weighbridge bays are idle.** |
| 07:08 | T4 → bay 0 (free since 07:06), 07:08-07:10. T2 passes through the sampler bay **without sampling**, 07:08-07:08:30. |
| 07:08:30 | T2 → bay 1, 07:08:30-07:10:30. T3 passes through, 07:08:30-07:09. |
| 07:09 | T3 → holding area (both bays busy). |
| 07:10 | T3 → bay 0, 07:10-07:12. |

**Expected:**
- weigh-in done: T1 07:06, T4 07:10, T2 07:10:30, T3 07:12;
- samples taken: 2 (T1, T4);
- T2 physically blocked 07:00-07:08 (8 min) without receiving sampling service;
- sampler bay occupied by unsampled trucks 07:08-07:09.

### S2: separate upstream sampler, bypass available (same resources)

| Time | Event |
|---|---|
| 07:00 | T2 takes the bypass and weighs at bay 0, 07:00-07:02. T1 sampled 07:00-07:04. |
| 07:01 | T3 takes the bypass and weighs at bay 1, 07:01-07:03. |
| 07:04 | T1 → bay 0, 07:04-07:06. T4 sampled 07:04-07:08. |
| 07:08 | T4 → bay 0, 07:08-07:10. |

**Expected:**
- weigh-in done: T2 07:02, T3 07:03, T1 07:06, T4 07:10;
- the trucks needing sampling finish at the same times as in S1;
- T2 and T3 are never blocked and never enter the sampler bay;
- samples: 2.

### S3: sampling at the weighbridge (probe at bay 0 only), single-file approach, no bypass

| Time | Event |
|---|---|
| 07:00 | T1 takes bay 0 **and** the sampler unit: sampled 07:00-07:04, then weighs 07:04-07:06 (the sampler unit is released at 07:04). T4 (sampled) is at the front of the queue. It needs the probe bay, which is busy, and bay 1 has no probe, so T4 waits. **T2 and T3 are blocked behind T4 although bay 1 is idle.** |
| 07:06 | T4 takes bay 0 + sampler unit: sampled 07:06-07:10, weighs 07:10-07:12. T2 → bay 1, 07:06-07:08. |
| 07:08 | T3 → bay 1, 07:08-07:10. |

**Expected:**
- weigh-in done: T1 07:06, T2 07:08, T3 07:10, T4 07:12;
- T2 blocked 6 min and T3 blocked 5 min without sampling service;
- reservations: bay 0 + sampler unit held together 07:00-07:04 and 07:06-07:10; bay 0 alone 07:04-07:06 and
  07:10-07:12;
- no sampling in bay 1.

### S4: sampling at the weighbridge, physical bypass permitted (unsampled trucks may pass a waiting sampled truck)

| Time | Event |
|---|---|
| 07:00 | T1 takes bay 0 + sampler unit (07:00-07:06 as in S3). T2 passes T4 and weighs at bay 1, 07:00-07:02. |
| 07:02 | T3 (arrived 07:01) → bay 1, 07:02-07:04. |
| 07:06 | T4 takes bay 0 + sampler unit, 07:06-07:12. |

**Expected:**
- weigh-in done: T2 07:02, T3 07:04, T1 07:06, T4 07:12;
- sampled trucks unchanged from S3;
- unsampled trucks never blocked.

### Hand-trace tests to write (before implementation)

- **Blocking without service:** in S1 and S3, unsampled trucks are physically blocked (reason
  `PHYSICAL_QUEUE_ORDER`), never sampled, and in S1 pass through the sampler bay with zero service.
- **Bypass only where a path exists:**
  - S2 and S4 trucks that don't need sampling use the declared bypass;
  - removing the declaration from S2 gives exactly S1's times;
  - a truck that needs sampling never uses a bypass.
- **Co-located reservations:**
  - in S3 and S4 the sampler unit is held only while the same truck holds bay 0;
  - bay 1 never samples;
  - with `sampling_overlaps_weighing: true`, T1 occupies bay 0 for max(4, 2) = 4 min.
- **Holding space:** in S1 with holding capacity 0, T3 stays in the sampler bay until a weighbridge bay frees, so
  the sampler is blocked by an unsampled truck.
- **Backward compatibility:** all existing tests pass, the version-tolerant fingerprint is unchanged, and
  `paper2-v1` reproduces unchanged.

## 6. Controlled experiment (proposed; `paper2-ext-sampling-v1`)

- **Base grain systems:** Site A and Site C (two different grain networks). The truck-access block is replaced by
  the S1-S4 layouts through overlays, with equal resources: 1 sampling unit and 2 weighbridge bays.
- **Unloading sequence:** `sample, weigh_in, grade, tip, weigh_out`.
- **Factors:**
  - layout S1-S4;
  - sampled share {0.3, 0.7, 1.0};
  - demand {×1.0, ×1.2};
  - one policy mapping stated explicitly (M-FF, engine default; M-PT as a sensitivity run).
- **Common random numbers:**
  - arrivals from the same seeds;
  - the sampling requirement from a per-truck stream (identical across layouts);
  - service and pass-through durations from per-(truck, step) streams.
- **Replications:** 20 per cell, because the baseline's 5 seeds left most differences descriptive.
- **Measures**, reported by truck class (sampled / unsampled) and overall:
  - total waiting;
  - physically blocked time;
  - turnaround;
  - time-averaged and peak queue length per area;
  - sampler and weighbridge-bay utilisation (busy / blocked-occupied / idle);
  - completed trucks;
  - grain received.
- **Comparisons:** paired by seed, Holm-adjusted.
  - Bypass effect: S2 − S1 and S4 − S3.
  - Location effect: S3 − S1 and S4 − S2.
- **Verification acceptance:** all existing physical invariants, plus the new ones (§4 item 7), in every run. Stalls
  are reported separately.

**Expected outcomes** (hypotheses to test, not results):
1. Bypass reduces waiting and blocked time of unsampled trucks, most at high sampled shares. Sampled trucks are
   nearly unchanged, or slightly worse through more weighbridge contention.
2. Sampling at the weighbridge raises weighbridge-bay occupancy per sampled truck (sampling + weighing). This lowers
   effective weighing capacity and lengthens queues as the sampled share rises.
3. A separate sampler with little holding space produces sampler blocking by trucks waiting for the weighbridge.
4. Where one sampler serves one probe bay, S4 approaches S2 for unsampled trucks. S3 can be worse than S1 at high
   sampled shares.

## 7. Assumptions requiring confirmation from silo operators

- **O1** Which trucks require sampling (all; by commodity; a random audit share), and is it known when the truck
  arrives?
- **O2** Is the approach to the sampler single-file? Can a truck pass another in the approach lane?
- **O3** Is there a bypass around the sampler (or around a probe bay)? Where does it start and end, and how many
  trucks does it hold?
- **O4** Sampler location: upstream station or probe at the weighbridge? At which bays? Is the probe fixed to a bay,
  or can one sampling crew serve several bays?
- **O5** How many trucks fit between the sampler and the weighbridge?
- **O6** At a probe bay, is sampling done before, during or after weighing? Can they overlap?
- **O7** How long does an unsampled truck take to drive through a sampler bay?
- **O8** Where does a truck wait for its grading result: in the bay, in the yard, or after weigh-in? Does it block
  a bay while waiting?
- **O9** Travel times between positions (currently zero).
- **O10** Do staff control the order (e.g. a gatekeeper calling trucks forward), or is order purely physical?
- **O11** Are sampled and unsampled trucks served in arrival order at the weighbridge, or is either class given
  priority?

## 8. Provisional decisions for implementation (2026-10-24)

Every choice below is a **provisional modelling assumption, not verified operating practice**, until silo operators
confirm it.

| Q | Provisional default (as implemented) | Simulation behaviour affected |
|---|---|---|
| O1 Which trucks need sampling; known at arrival? | Default: every truck whose activity sequence contains `sample` (unchanged behaviour). Override per truck (`requires_sampling` in arrival data) or by share (`demand.<activity>.sampling_share`, one seeded draw per truck). The requirement is known at arrival. | Which trucks receive `sample` and `grade` service; sampler load; the mix of trucks in each queue |
| O2 Is the approach single-file; can trucks pass? | Areas are unordered unless configured `single_file: true` (unchanged default). S1-S4 set the approach to single-file. | Physical blocking behind the front truck (`PHYSICAL_QUEUE_ORDER`) |
| O3 Bypass around the sampler? | None unless declared (`truck_paths.bypasses`). A bypass lane holds no trucks: a truck uses it only when its target place is free, otherwise it waits where it is. | Whether unsampled trucks skip the approach queue and the sampler bay |
| O4 Sampler location, probe bays, crew mobility | Separate upstream station (unchanged default). Co-location via `located_at` (weighbridge id) and `located_lanes` (probe bays). The sampler's `cap` = number of sampling units; a unit may serve any listed probe bay. | Which positions sampled trucks need; bay occupancy; sampler-unit utilisation |
| O5 Holding space between sampler and weighbridge | As configured: a finite area, or none. With none, a truck keeps the sampler bay until a weighbridge bay is free. | Upstream blocking of the sampler |
| O6 At a probe bay: sampling before, during or after weighing? | Sampling, then weighing, on the same bay, with no overlap. The overlap option is **not implemented** in this increment. | Bay occupancy per sampled truck (sampling + weighing) |
| O7 Drive-through time of an unsampled truck through a sampler bay | Default 0 min (`pass_through` not configured). S1 tests use 0.5 min. | Sampler-bay occupancy by unsampled trucks |
| O8 Where a truck waits for its grading result | Where `grade` sits in the configured path. Experiment: in the yard after weigh-in. Unsampled trucks skip `grade`. | Whether waiting for the result blocks a bay |
| O9 Travel times between positions | Zero (unchanged). | All times (lower bounds) |
| O10 Who controls order: staff or physical order? | Physical order plus the configured queue policy; no discretionary calling forward. | Order of service within physical constraints |
| O11 Priority of sampled or unsampled trucks | None. The queue policy treats both classes alike (M-FF in the experiment, stated). | Waiting by class |
