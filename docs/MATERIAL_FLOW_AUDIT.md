# Grain-flow integrity audit (step 16)

Status: audit and plan written before any change, then carried out (2026-10-23). Results are in §5, remaining gaps in §6. No new queueing policy, dynamic bin
allocation or mechanical capacity formula is part of this stage.

## 1. How grain moves today (as implemented)

| Stage | Where | What changes |
|---|---|---|
| Tipping starts | `_try_tip` | Tipping lane plus **pit space claim** (`PitSpaceClaim`) reserved atomically. No grain moves yet. |
| Tipping ends | `_tip_done` | The claim becomes a lot (`L-<truck>`) in the pit; `received` += truck tonnes. The truck may leave: **unloading is complete**. |
| Transfer starts | `_try_intake` | Route segments (commodity lock, feed limit, merge rule) plus **bin incoming reservation** for `min(lot, bin free space)`, reserved atomically. The pit outlet starts draining after any changeover. |
| Transfer flows | `_recompute_rates` | Continuous drain from the head lot (A3). The rate is shared equally on shared segments (A2). |
| Transfer ends | `_intake_done` | The bin receives the reserved kg; the pit's head lot is reduced. The route is released after the clear time. **The lot is in storage only when all its kg have arrived** (a lot can be split over several transfers when a bin fills). |
| Loading starts | `_try_load` | Load point, load-out route and **bin outgoing commitment** reserved atomically. |
| Loading ends | `_load_done` | Stock leaves the bin; `dispatched` += kg; route released after the clear time. |
| End of run | `result()` | Balance = opening + received − dispatched − (bins + pits) must be 0. |

**Where grain is counted.** Pits (lots), bins (tonnage) and dispatched. Conveyors, elevators and reclaim conveyors
hold **no inventory**. Grain that has drained from a pit but not yet arrived in a bin stays counted in the pit's lot
until the transfer ends; the bin receives it all at the end. The prototype does the same.

## 2. What is verified already (existing tests)

- **Atomic reservations** (`test_ledger_and_pit`): all-or-nothing reservation and release; exclusive and shared
  segments; lane plus pit space.
- **Transfers** (`test_intake_transfers`): independent and shared routes; truck leaves before its grain is stored; full-load-space and
  empty-pit rules; one commodity per pit; lot split when a bin fills.
- **Concurrent feeds and changeovers** (`test_concurrent_feeds`, `test_changeovers`): equal sharing, feed limit,
  merge rule, joining during a changeover; route held for the clear time.
- **Loading** (`test_loading`).
- **End of day** (`test_operating_hours`): transfers after close, or held to the next day.
- **Bins** (`test_storage_bin`): reservations, exact space, identity, mixing rules, misuse.
- **Engine invariants after every event** (`ledger.check_invariants`, pit and bin invariants); end-of-run balance.

## 3. Gaps found by the audit

1. **Conservation is checked only as one end-of-run total**, computed from the engine's own counters. Nothing
   independent checks, from the run's records alone:
   - that each pit, bin and lot balances;
   - that bin capacity was never exceeded over time;
   - that streams on a shared segment were compatible over time;
   - that routes were released after their clear time.
2. **Unloading completion and storage completion are not reported separately.** A truck's tip end is recorded, but not
   when its lot fully reached storage, or how much is still in the pit or in transit at the end.
3. **Termination**: no test stops a run *during* a transfer and a load together and checks where every kilogram is.
4. **Bin availability**: no test of two concurrent transfers competing for the last space in a bin, or of all eligible
   bins full (the grain waits in the pit: `BIN_FULL`).
5. **Single-bin and hardcoded assumptions** (source scan: no equipment ids or site names in `src/`):
   - A load is filled from **one** bin.
   - Each pit has **one** outlet (one transfer at a time, head lot first).
   - Each transfer feeds **one** bin; a lot that does not fit is split over later transfers in preference order.
   - Bin choice is a fixed preference: same grain first, then route order. Dynamic allocation is out of scope.
   - Equipment holds no in-transit inventory (§1).

## 4. Plan (smallest safe steps)

1. **Independent flow audit** (`src/silo_engine/checks/flow_audit.py`). It reads only the configuration, the arrival
   list and the run's records (transfers, loads, truck records, closing bins and pits) and checks:
   - global, per-pit and per-bin conservation, and per-lot accounting;
   - bin capacity, identity and stock over time;
   - segment compatibility, feed limit and merge rule over time;
   - route release after the clear time;
   - transfers starting only after their truck finished tipping;
   - loads matching their trucks.

   It does not import the engine's internal state. Reporting only; no engine change.
2. **Lot flow reporting** (`TruckFlowResult.lots`): per lot, when it was tipped, when its first transfer started,
   when it was fully stored, kg stored / in transit / still in the pit, and the bins it went to. Experiment figures:
   lot-to-storage time. Bookkeeping only; no decision changes.
3. **Deterministic tests** (`tests/test_material_flow.py`), hand-traced:
   - truck departure versus storage completion;
   - lot split over two bins;
   - two transfers competing for a bin's last space;
   - all bins full (grain stays in the pit);
   - shared conveyor (second stream waits; the route is released after the clear time);
   - run stopped mid-transfer and mid-load (every kilogram located);
   - transfers stopped at close (grain left in the pit at the end of the last day);
   - the audit itself catching corrupted records.
4. Run the audit on generated Site A days (both policies, two demand levels).
5. Regression: the full suite, the engine fingerprint, configuration hashes, the fairness baseline and the prototype
   selftests.

## 5. Results (2026-10-23)

**Built** (reporting and checking only; no change to any decision):
- `src/silo_engine/checks/flow_audit.py`: the independent flow audit (§4.1).
- `TruckFlowResult.lots` (`LotFlow`): tipping-to-storage record per lot, including opening pit grain.
- Experiment figures: `lots.mean_to_storage_min`, `lots.max_to_storage_min` and `lots.not_stored_t`.

**Deterministic tests** (`tests/test_material_flow.py`, 19, hand-traced, all passing on the first run):
- the truck leaves at 07:01; its lot is stored at 07:10;
- stopped mid-transfer: the 30 t are in transit and counted in the pit, the bin is empty, the audit lists the open
  transfer;
- a lot split 20 t / 10 t over two bins;
- two lines competing for a 40 t bin: 30 t + 10 t reserved, the remaining 20 t to the next bin; never over capacity;
- all eligible bins full: a stall with `BIN_FULL`, the lot stays in the pit, the grain balances;
- a shared conveyor held 2 min clear time: the next stream reserves it at release;
- termination during loading (stock committed, not dispatched) and during intake (in transit) on a shared elevator;
- transfers stopped at close on the last day: the running transfer finishes, the next lot stays in the pit;
- opening pit grain as a lot without a truck;
- the audit rejecting 8 kinds of corrupted records;
- generated days on prototype sites A and B under both policies: clean.

**Further evidence:**
- **Audit on 40 generated runs** (sites A and B × 2 policies × 2 demand levels × 5 seeds): 0 problems, nothing in
  transit at the end.
- **Engine fault injection:** 4/4 detected (route released without clear time; storage time from the first part
  of a split lot; in-transit grain counted as stored; bin space ignoring incoming reservations).
- **Regression:**
  - `pytest -q`: 291 passed, 2 expected failures (the known tie-break, step 15);
  - engine fingerprint, configuration hashes and fairness baseline unchanged;
  - prototype selftests 12/12.

**No engine defect was found.** No behaviour was changed.

## 6. Remaining gaps

1. **No inventory on conveyors and elevators.** Grain in transit is counted in its source pit until the transfer
   ends, and the bin receives it all at the end. Belt and leg contents, and the delay between pit and bin, are not
   modelled. This matters for very long routes and for stopping mid-transfer.
2. **One bin per load** (no multi-bin loads). **One outlet per pit** (one transfer at a time, head lot first).
   **Fixed bin preference** (same grain first, then route order). Dynamic allocation is out of scope by decision.
3. **Interrupted transfers: done in step 17** for scheduled outages of route equipment (hold and resume; see
   `docs/INTERRUPTED_TRANSFERS.md`). Still missing:
   - random breakdowns;
   - outages of hoppers, bins or load points;
   - an operator abort that releases the route and credits what reached the bin.
4. **Grain left in a pit when every eligible bin is full** is reported as a stall. No overflow rule, emergency bin
   or operator action is modelled.
5. **No authorised adjustments** (shrinkage, moisture loss, cleaning losses, stock counts). CLAUDE.md requires these
   to be explicit; none is modelled yet, so every run must balance to the kilogram.
6. **Grading rejection is not modelled**, so no rejected grain leaves with its truck.
7. **Lot-to-storage times** are reported, not yet summarised per commodity in experiments.
8. **Equal-age intake tie-break** differs from the prototype (step 15). It is unchanged and still open for your
   decision.
