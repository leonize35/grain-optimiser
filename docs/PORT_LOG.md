# Port log — prototype engine v0.2.0 (JavaScript) → silo_engine (Python)

Rule: each step ports one module behind tests. The JS engine in `reference/prototype_js/` stays unmodified and runnable as the oracle until parity is shown (see docs/audit/PORT_DECISION.md).

## Repository provenance (2026-10-19)

No original Git repository exists for the prototype. It was found only as the private claude.ai artifact "Silo Decision Lab" (artifact version `1792415835-5506`), which has no Git history. This repository was created new. The prototype is preserved byte-for-byte:

| File | SHA-256 |
|---|---|
| `reference/prototype_js/silo_engine_v0.2.0.js` (lines 243–1193 of the artifact) | `b46c2bc707adf27d60f405377a321366220c89fb3d7fc42dea16d960e08a1628` |
| `reference/prototype_js/silo_decision_lab_v0.2.0.html` (full artifact) | `35f39d4ef14ae4fd7af479afc9111f3d9cebff9fdf50a354eaa05749b491e5e9` |

## Step 1 — configuration schema and validation (branch `feat/config-validate-port`)

**Ported:** `buildRoutes` → `silo_engine.config.routes.build_routes`; `validate` → `silo_engine.config.validation.validate`. New: `silo_engine.config.schema` (typed pydantic model, `load_site_config`, `config_hash`).

**Behaviour proved (tests executed 2026-10-19, 44 passed):**
- For 17 configurations (prototype Site A and Site B, plus 15 broken or edge-case variants), the Python validator reproduces the prototype's output **exactly**: every error, warning and info message, their order, the equipment ids each one highlights, `ok`, hopper-to-bin and bin-to-load-point routes including tie-break order, shared-equipment users and unreachable bins.
- Route tie-breaking reproduces the browser's `localeCompare` order for letters, digits, space, `_`, `-`, `,` and `.`.
- Fault injection: replacing locale ordering with ASCII ordering, or allowing a hopper to feed a bin directly, each makes the parity tests fail.

**Intentional differences from the prototype (tested in tests/test_config_schema.py):**
1. Unknown fields are rejected, with their location reported (e.g. `equipment.3.capacity`).
2. Operating rules must be `tip ∈ {fifo, feasible, batch}`, `weigh ∈ {fifo, load_first, out_first}`, `transfer ∈ {fifo, batch, load_first}`.
3. Truck steps must be one of the six supported steps. The prototype accepts unknown steps, and a truck reaching one would never advance.
4. Weighbridge `moves` must be `in`, `out` or `both`.
5. A connection touching equipment of an unsupported type is skipped (the type itself is reported). The prototype throws a `TypeError` in this case.
6. `config_hash()`: SHA-256 of the canonical JSON, for run records (CLAUDE.md §9).

**Known limitations:**
- `locale_sort_key` approximates ICU collation. It is verified only for the characters listed above; other punctuation follows the ICU root order as documented, not as tested.
- JS objects order integer-like keys (e.g. an equipment id `"7"`) before other keys; the Python `users` dict does not. This is irrelevant for normal ids and not tested.
- Numbers in messages print like JavaScript for ordinary values. Exponent notation (below 1e-6 or at/above 1e21) differs.
- Validation semantics are inherited unchanged, including the prototype's simplifications (no truck path graph, no grade segregation, whole-route reservation assumed). Those are engine gaps (see docs/audit/GAP_MATRIX.md), not validator bugs.

**Commands run:**
- Before: `tools\run_prototype_selftests.ps1` → 12/12 passed; `pytest` → no tests.
- After: `tools\run_prototype_selftests.ps1` → 12/12 passed (twice, same engine hash); `pytest -v` → 44 passed.

## Step 2 — event calendar, time and quantity policy, scripted arrivals

**Ported:** prototype `Calendar` → `silo_engine.sim.calendar.Calendar`. Same ordering: (time, priority class, scheduling sequence) with RELEASE 0 < CONTROL 1 < ARRIVAL 2.
**New:** `sim/time.py` (integer-millisecond clock, clock-string parsing and formatting), `domain/quantities.py` (integer kilograms), `inputs/scripted.py` (explicit truck list, site check in manager language).

**Behaviour proved (tests executed, 67 passed in total):**
- Chronological execution regardless of scheduling order.
- Same-instant order: release, then control, then arrival; equal priority in scheduling order. This includes events scheduled *during* execution at the current instant (hand-derived A1, R, A2, A3).
- Refusal to schedule in the past (1 ms early) and of non-integer times; scheduling at the current instant is allowed.
- Cancellation, `run(until)` semantics, identical logs for identical schedules.
- A worked single-weighbridge trace whose start and finish times and waits (0, 1, 3 min) are written out by hand.
- Exact time and tonnage conversion. Over-precise or non-positive tonnages are refused, e.g. `0.1 + 0.2` t.
- Scripted arrivals are scheduled in hand-derived order: the opening-queue truck uses CONTROL priority, and simultaneous trucks keep script order. Duplicate ids and missing or extra cargo fields are refused with the truck id. Unknown commodities and arrivals outside opening hours are reported in plain language.
- Fault injection: switching the calendar to newest-first ordering makes 5 tests fail.

**Intentional differences from the prototype:** scheduling in the past raises an error (the prototype records a violation and continues); integer milliseconds instead of float minutes; events can be cancelled.

**Not yet connected:** the calendar is not used by any truck or grain logic yet. The dispatcher, reservation ledger and changeover rules wait for confirmation of docs/DOMAIN_DECISIONS.md.

**Commands run:** `pytest -q` → 67 passed; `tools\run_prototype_selftests.ps1` → 12/12 passed, engine sha256 unchanged (`b46c2bc7…1628`).

## Step 3 — confirmed domain rules specified; storage bin model

**Decisions D1–D6 confirmed by the domain owner (2026-10-22).** These are now specified as rules R1–R7 in docs/DOMAIN_DECISIONS.md, each with configuration parameters, expected behaviour, edge cases and verification tests, and each tagged confirmed / site input / assumption / default. Eight engineering assumptions (A1–A8) are listed for confirmation. docs/ENGINE_INTERFACES.md drafts the contracts for the route planner, reservation ledger, changeover policy and requests. None of those is implemented yet.

**Implemented:** `domain/storage.py`, covering `StorageBin` (R7) and `MixingRules` (R4): capacity, tonnage, fill fraction, commodity and grade identity, incoming reservations, outgoing commitments, availability, safe reassignment and independent invariants. Refusals are all-or-nothing and return reason codes. Misuse raises `BinError`.

**Behaviour proved (20 new tests, 87 in total):** exact space and stock arithmetic in kilograms; partial delivery with release of unused space; refusal of another commodity or grade without a mixing rule; a mixing rule classifying the mixture; refusal when the mixture's grade is not assigned to the bin; an empty bin's identity fixed by a pending reservation, preventing segregation breaches before grain arrives; identity cleared when emptied; reassignment refused when it would contradict contents or pending reservations; out-of-service behaviour (assumption A8); and atomicity (state snapshot unchanged after a refusal). Fault injection: ignoring incoming reservations in free space, or ignoring pending reservations in identity, each fails 2 tests.

**Commands run:** `pytest -q` → 87 passed; `tools\run_prototype_selftests.ps1` → 12/12 passed, engine sha256 unchanged.

## Step 4 — central dispatcher skeleton and truck stations (build step 1)

Assumptions A1–A8 and the interface draft were approved by the domain owner on 2026-10-22.

**Implemented:**
- `sim/dispatcher.py`: queue groups with `strict_fifo` or `feasible_first`, rescanning after every start, waiting reasons, overtake counts.
- `sim/truck_flow.py`:
  - samplers, graders and weighbridges as pooled lanes, with weighbridge direction respected;
  - samples as separate entities, each truck waiting for its own grading result;
  - unlimited waiting areas (R5 default), and unfinished trucks reported at the end of a run;
  - tipping and loading refused explicitly as not yet built.
- `sim/service_times.py`: fixed durations for hand-checked tests.

**Behaviour proved (16 new tests, 103 in total), every expected time derived by hand in the test docstring:**
- arrival-order service on one weighbridge and on a two-lane weighbridge;
- the head-of-line case with in-only and out-only weighbridges: under feasible-first the later truck overtakes, and the overtake is counted; under strict FIFO it waits behind the blocked truck, with the full trace timed by hand;
- waiting reasons `EQUIPMENT_BUSY` and `QUEUE_ORDER`;
- grading results returning out of order; another truck's result being back never releases a truck;
- unfinished trucks reported when a run stops early;
- reproducibility; explicit refusal of unbuilt steps, missing stations and unknown policies.

**Fault injection:**
- ignoring strict FIFO fails 3 tests;
- not rescanning after a start fails 5;
- releasing a truck on *any* returned result first went undetected. That exposed a test gap, so a test was added, and it now fails 1.

**Discrepancy flagged:** the prototype's weighbridge policy `fifo` is feasible-first in arrival order (see ENGINE_INTERFACES.md §0).

**Commands run:** `pytest -q` → 103 passed; `tools\run_prototype_selftests.ps1` → 12/12 passed, engine sha256 unchanged.

**Limitations:** fixed service times only (stochastic durations next to this interface); no rejection at grading; no grade values on trucks yet (R4); stations are not yet connected to the reservation ledger. The ledger arrives with pits and transfers in build step 2.

## Step 5 — hopper pits, intake transfers and the atomic reservation ledger (build step 2)

**Implemented:**
- `sim/ledger.py`: one atomic owner of every claim (station lanes, hopper tipping lanes, pit space, conveyor/elevator streams with commodity lock, bin incoming space). It checks everything first and then takes everything, or nothing. Release frees every claim. Every reservation and release is logged, and invariants can be checked independently.
- `sim/pit.py`: lots carry truck, commodity and grade; the level falls continuously while draining (A3); one grain per pit (A4); the `full_load_space` and `empty_pit` rules (R2); exact calculation of when space for a load will exist.
- `sim/routing.py`: intake candidates from the configured graph, preferring bins that already hold the grain.
- `sim/truck_flow.py`:
  - the `tip` step, with hopper choice following the prototype rule (a pit already holding the grain first);
  - intake transfers on exclusive segments, with route rate = slowest of the hopper and segments, and durations rounded up to the next millisecond;
  - partial fills split across bins, pit-space re-check events, and material balance plus ledger invariants checked after **every** event.
  - Station lanes now also go through the ledger.
- Schema: `tip_admission` (`full_load_space` / `empty_pit`, default `full_load_space`) and `max_concurrent_feeds` (default 1) on equipment. Golden parity is unaffected.

**Behaviour proved (26 new tests, 129 in total):**
- T1.1 independent routes carry different commodities at once;
- T1.2 an exclusive shared elevator, with H2 waiting 07:09–07:18 and its reasons naming C1 and E1;
- T2.1 a truck leaving (07:05) before its grain reaches the bin (07:12);
- T2.2 `full_load_space` tipping at 07:03, and T2.3 `empty_pit` at 07:12;
- T2.4 another commodity waiting for an empty pit;
- a lot split 20 t / 10 t when the preferred bin fills;
- ledger all-or-nothing, with a full-state snapshot unchanged after a refusal;
- the commodity lock on a shared segment;
- explicit refusal of changeovers (R3), concurrent feeds and loading, which are not built yet.

**Fault injection:** non-exclusive segments fail 3 tests; prototype-style stepwise pit space fails 3; no partial fill fails 1; a non-atomic ledger fails 7.

**Found and fixed during testing:** a pit-space re-check was scheduled only when lack of space was the *sole* reason a truck waited. A truck waiting for both reasons kept a stale "no space" reason. It is now re-checked whenever space is among the reasons.

**Commands run:** `pytest -q` → 129 passed; `tools\run_prototype_selftests.ps1` → 12/12 passed, engine sha256 unchanged.

**Limitations:**
- grades use a placeholder `*` until R4 (build step 5);
- no `clear_minutes` hold yet (R1 default 0);
- waiting reasons are as of the most recent evaluation, which happens at every state-changing event;
- the independent replay checker over the ledger log is not written yet (the log exists).

## Step 6 — commodity-pair changeovers (R3) and route clear time (build step 3)

**Implemented:**
- Schema: site `changeovers` (`default_minutes`, `rules` with `from`/`to`/`minutes`/`equipment`) and equipment `clear_minutes`. Golden parity is unaffected.
- `domain/changeover.py`: `ChangeoverMatrix`:
  - asymmetric pair rules; the most specific rule wins (equipment id > type > `*`, then grade > commodity > `*`);
  - the default applies to commodity changes only;
  - a grade-only change needs a changeover only if a grade rule exists;
  - equally specific rules that disagree are refused.
  - Prototype-format sites (no `changeovers` section) use each conveyor's and elevator's single `changeover` value for any commodity change.
- `config/rules_validation.py`: `validate_rules` checks the confirmed rules that go beyond the prototype, kept separate so `validate()` stays an exact prototype port. For R3 it reports:
  - unknown commodities or equipment in rules;
  - every commodity pair that can meet on the same conveyor or elevator (derived from the configured routes) with no rule or default;
  - disagreeing rules.
  - Prototype-format sites get a visible warning. The engine refuses to run with errors.
- `sim/truck_flow.py`: a transfer's timeline is now reserve → changeover (longest segment, A5) → flow → clear time → release. Changeovers are recorded per segment, including 0-minute ones. The temporary "changeover not yet supported" stop is removed.

**Behaviour proved (16 new tests, 144 in total):**
- T3.1 asymmetric pair (yellow → white 10 min: lot reserved 07:11, flows 07:21–07:30);
- a 0-minute changeover counted without delay;
- T3.2 missing pair as a configuration error naming the pair and equipment;
- only pairs that can actually meet are required;
- T3.3 parallel segments, longest wins (6 min over 4 min);
- prototype-format changeover in a run (8 min);
- T3.4 a route held 2 min after the last grain, with the next lot starting 07:11 instead of 07:09;
- rule specificity, the default's scope, grade rules, and ambiguity.

The prototype's demo sites A and B pass `validate_rules` with no errors and the prototype-format warning.

**Fault injection:**
- summing changeovers instead of taking the longest fails 3 tests;
- ignoring changeover time fails 3;
- taking the first matching rule instead of the most specific fails 2;
- applying the default to grade-only changes fails 1;
- ignoring clear time fails 1;
- not reporting missing pairs fails 2.

**Test change:** one build-step-2 test that expected the old "changeover not yet supported" stop is replaced by the new timing tests. The pit tests that carry two commodities now state an explicit `default_minutes: 0`.

**Commands run:** `pytest -q` → 144 passed; `tools\run_prototype_selftests.ps1` → 12/12 passed, engine sha256 unchanged.

**Limitations:**
- volume-based flushing (`flush_tonnes`) is specified but not built, pending site confirmation;
- all segments of a route are released together, after the longest clear time;
- grade-level rules are evaluated but grain still carries the placeholder grade `*` until R4 (build step 5).

## Step 7 — concurrent feeds on shared equipment (build step 4)

**Implemented:**
- Concurrent feeds (`max_concurrent_feeds` > 1) are now built, so the interim refusal is removed.
- Rate model (A2): each flowing transfer runs at the slowest of its pit's discharge rate and each segment's rate divided by the streams *flowing* on it. A stream in its changeover holds a slot but takes no throughput.
- Rescheduling: when a flow starts or ends, every flowing transfer's remaining kilograms are updated exactly, and its completion event is cancelled and rescheduled. The pit drain now supports variable rates, so waiting trucks get fresh pit-space predictions after every rate change.
- Merge rule (A1) in the ledger: a stream may share a segment only if its whole remaining route to the bin matches (`MERGE_PATH_DIFFERS`). The rule is also an invariant.
- Joining a segment that already carries the same grain needs no changeover. The joiner may not flow before a changeover already under way on its segments has finished.

**Behaviour proved (8 new tests, 152 in total), every timeline hand-computed:**
- T1.3 two streams at 100 t/h each, 07:00–07:18;
- T1.6 the remaining stream speeds up, finishing at 07:13:30;
- a feed limit of 2 making a third stream wait until 07:18;
- T1.4 the commodity lock on shared equipment;
- T1.5 merging only towards the same bin, including a part-lot followed by a merge (07:03 → 07:15 / 07:18, bins 1000 t and 50 t);
- pit space following changing drain rates (truck tips at 07:10:30 instead of 07:12);
- a joiner waiting for a changeover under way (both flow from 07:08);
- a joiner after a changeover needing none (07:11 → 07:23 / 07:26);
- the ledger merge refusal.

**Fault injection:** no rate sharing fails 5 tests; no speed-up when a stream leaves fails 4; merge rule ignored fails 2; pit prediction ignoring rate history fails 1; a joiner charged a changeover fails 2; a joiner ignoring a changeover under way fails 1.

**Bug found and fixed:** the fault "joiner charged a changeover" first went undetected. Investigating it showed that a stream joining **during** another stream's changeover would have started flowing onto equipment still being cleaned. Two tests now cover both cases, and the model waits for the changeover to finish.

**Test change:** the build-step-2 test expecting concurrent feeds to be refused is removed, because the feature now exists.

**Commands run:** `pytest -q` → 152 passed; `tools\run_prototype_selftests.ps1` → 12/12 passed, engine sha256 unchanged.

**Limitations:**
- equal sharing is assumption A2; proportional sharing is not built;
- all segments of a route are released together after the longest clear time;
- rates are exact fractions and completion times are rounded up to the next millisecond.

## Step 8 — grades end to end (build step 5)

**Implemented:**
- Schema:
  - commodity `grades`;
  - bin `accepts` (`[{commodity, grades}]`);
  - opening-stock grades `invGrade` / `levelGrade`;
  - site `grade_segregation` (`by_grade` default / `none`) and `grade_mixing` (`[{commodity, grades, result}]`);
  - scripted-truck `grade`.

  Ungraded commodities behave exactly as before, so golden parity and every earlier test are unaffected.
- `config/grades.py` (`GradePolicy`): one place that turns configuration into commodity-and-grade identities, bin grade lists and mixing rules. With segregation `none`, grades are recorded but grain is handled as `*`.
- `sim/pit.py`: pits combine grades only through the mixing rules (A4 with R4).
- `sim/truck_flow.py`: grain identity, hopper choice, pit admission, routing and bins all use commodity and grade. Scripted trucks with graded commodities must state a valid grade.
- `config/rules_validation.py`, new R4 checks:
  - mixing rules, bin grade lists, opening stock and changeover rules must refer to real grades;
  - every bin holding a graded commodity lists its grades (unless segregation is `none`), and grade lists contradicting `none` are errors;
  - every grade must reach a bin that accepts it (T4.3);
  - grading must come before tipping wherever bins keep grades apart (T4.5).

**Behaviour proved (13 new tests, 165 in total), timelines hand-computed:**
- T4.1 each grade goes only to its bin. The pit holds grade 2 until 07:15, so grade 1 tips then.
- A grade-level changeover rule is applied in a run (4 min).
- T4.2 a mixing rule lets grades share the pit and bin, and the bin stays grade 2.
- T4.4 a truck cannot tip before its own grading result.
- Segregation `none` records grades without restricting.
- A graded truck must state a known grade.
- Every configuration check has a test, plus one confirming that ungraded sites are unaffected.

The prototype's demo sites A and B still pass `validate_rules` with no errors.

**Fault injection:**
- ignoring grade in grain identity fails 4 tests;
- bins accepting every grade fails 4;
- pits ignoring mixing rules fails 1;
- not reporting grading after tipping fails 1;
- not reporting an unreachable grade fails 1;
- accepting a graded truck without a grade fails 1.

**Adjustments made while testing:**
1. One missing grade list produced a knock-on "grade unreachable" error. The reachability check now skips a commodity whose bins have not listed grades yet, so only the root cause is reported.
2. The mixing test's own site was invalid under T4.3 (no bin took grade 3). The test site was corrected; the rule was kept.

**Commands run:** `pytest -q` → 165 passed; `tools\run_prototype_selftests.ps1` → 12/12 passed, engine sha256 unchanged.

**Limitations:**
- two different grades of the same commodity cannot flow on a shared segment at the same moment, even if mixing is allowed (the commodity lock compares commodity and grade, a conservative choice);
- a grade-only change with no grade rule is recorded as a 0-minute changeover;
- stochastic grade mixes for generated demand (`grade_mix`) come with generated arrivals, not built yet;
- grading rejection is not modelled yet.

**Next step:** build step 6: finite staging areas, truck paths and blocking (R5), including the deadlock policy (`reserve_next_space` / `detect_only`).
