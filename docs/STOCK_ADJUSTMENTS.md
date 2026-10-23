# Stock adjustments and inventory reconciliation: audit and design (step 18, before implementation)

Status: **design for review, no code changed** (2026-10-23). Software-independent. All quantities are integer
kilograms, as everywhere in the engine.

## 1. Audit: what exists today

| Topic | Current state |
|---|---|
| Inventories | One inventory only: the **simulated physical mass**. Bins hold tonnage + identity (commodity, grade). Pits hold lots (with truck identity). A running transfer's modelled in-transit mass is counted in its source pit (`INTERRUPTED_TRANSFERS.md` §8). |
| Opening stock | Configuration: bin `inv` / `invCommodity` (/ grade), hopper `level0` / `levelCommodity`. Part of the versioned configuration and its hash. |
| Site boundary | In: tipped trucks (`received`). Out: loaded trucks (`dispatched`). Nothing else enters or leaves. |
| Conservation | Opening + received − dispatched = closing, exact to the kg. Checked by the engine and, independently, by `checks/flow_audit.py` (global, pit, bin, lot, over time). |
| Adjustments | **None.** No moisture or drying shrink, cleaning or screenings, handling loss, sample removal, grading rejection, stock count, survey or administrative correction. |
| Recorded (book) inventory | **None.** The model has no book inventory separate from physical mass, so it has no reconciliation. |
| Lot identity | Kept in pits (one lot per truck, plus opening lots). Lost on entering a bin: a bin is an aggregate of tonnage + identity, with no lot traceability inside it. |
| Prototype | No adjustments or reconciliation either. |

**Gap:** CLAUDE.md requires conservation "through receive, transfer, storage, dispatch and **explicit authorised
adjustments**". The last part does not exist yet.

## 2. Two ledgers: the core rule

| Ledger | Symbol | Meaning | Changed by |
|---|---|---|---|
| **Physical mass** | P | The grain the simulation moves: what is really in each bin and pit (the model's truth) | Physical events only: receive, transfer, dispatch, **process loss** |
| **Recorded inventory (book)** | R | What the silo's records say, per location, commodity and grade | Postings of the physical events, **measurement adjustments**, **administrative adjustments**, opening book |

**Reconciliation** is D = R − P per location, commodity and grade. It is reported, **never fed back into P**.

**Safeguard:** P can change only through physical event types. A measurement or administrative adjustment has no
code path that touches P; applying one to P is an engine error. So an administrative adjustment cannot create or
destroy physical grain, and every difference it causes appears as a reported discrepancy.

## 3. Definitions: effect of each kind of change

| Kind | Physical mass P | Recorded inventory R | Lot identity | Reconciliation D = R − P |
|---|---|---|---|---|
| **Physical transfer** (exists: receive, intake, load) | Moves between locations; enters at receive, leaves at dispatch | Posted identically (no measurement error yet) | Kept in pits; merged into the bin aggregate | Unchanged |
| **Process loss**: moisture or drying shrink, cleaning losses, handling dust | **Decreases** at the location; the mass goes to a **loss sink** with a cause: `L[cause] += kg` | Decreases if the loss is *posted*; unchanged if not | Commodity and grade unchanged (mass only); a bin emptied by it clears its identity (existing rule) | Unchanged if posted; **+kg** ("unposted loss") if not |
| **Opening-stock correction** | Only by changing the **configuration** (P0 is input data); a new configuration version and hash. Never an event during a run. | R0 may be given separately (`opening_book`); default R0 = P0 | Opening lots or bin identity as configured | Starts at R0 − P0 ("opening difference") |
| **Measurement adjustment**: stock survey, dip or volumetric measurement | **Unchanged.** The survey measures; it does not move grain. | **Set to the measured value** (posted as a variance entry, measured − R) | Unchanged | Becomes measured − P ("measurement variance"). With no measurement error modelled yet, this is the size of the survey error. |
| **Administrative correction**: posting error, write-off, book transfer | **Unchanged** | **+delta** (signed), with reason and authority recorded | Unchanged | **+delta** ("administrative") |

**Reconciliation identity** (checked; the "unexplained" part must be exactly 0 in the simulation):

```
D_close = (R0 - P0)                       opening difference
        + Σ administrative deltas
        + Σ measurement variances
        + Σ unposted process losses
        + unexplained                     (= 0, otherwise an engine/audit failure)
```

**Physical conservation with losses**, at every event:
`P_open + received − dispatched − Σ L = P_close`.

**Book equation:** `R_open + received − dispatched − Σ posted losses + Σ admin + Σ measurement variances = R_close`.

## 4. State variables to add

| Variable | Where | Content |
|---|---|---|
| `losses` | physical side (engine) | kg per (location, cause, commodity, grade); totals per cause |
| `book` | new `BookLedger` (domain) | R in kg per (location, commodity, grade); starts at R0 (default P0) |
| `adjustment_log` | result | Per event: id, time, kind, location, commodity, grade, quantity (delta or measured value), cause or reason, authority, **applied or refused** (with reason), ΔP, ΔR |
| `reconciliation` | result | Per location and commodity: P, R, D and its components (§3), at the end and after every measurement event |
| Configuration | `SiteConfig` | `opening_book` (optional R0); `stock_events` (deterministic list, §5). Left out of the configuration hash when empty, so existing hashes stay unchanged. |

No change to transfers, reservations, routing, queue policies or interruption handling.

## 5. Event definitions (deterministic, scheduled; no random distributions yet)

| Event | Inputs | Preconditions (else **refused**, logged, nothing changes) | Effect |
|---|---|---|---|
| `PROCESS_LOSS` | bin, kg, cause (`moisture`, `cleaning`, `handling`), commodity (+grade), `posted` (default true) | bin holds that grain; **available** stock (tonnage − outgoing commitments) ≥ kg | bin P −kg; `L[cause]` +kg; if posted, R −kg |
| `STOCK_MEASUREMENT` | bin, measured kg, commodity (+grade) | measured ≥ 0 | R := measured (variance = measured − R before); P unchanged; reconciliation snapshot |
| `ADMIN_ADJUSTMENT` | location, signed delta kg, commodity (+grade), reason, authority | R + delta ≥ 0; reason given | R +delta; P unchanged |
| Opening correction | configuration only (P0 and/or R0) | validated with the configuration | new configuration version |

**Calendar priority:** CONTROL. At an equal instant, completions come first, as for outages. Events refer to
configured locations only: no built-in names, validated against the network.

**Interactions:**
- **Loads:** a loss cannot take stock already committed to a loading truck. Loading truck checks always use **P**,
  so stock that exists only in the book can never be loaded.
- **Bins:** a loss frees space (capacity check unaffected). Incoming reservations are untouched.
- **Scope:** losses apply to **bins only** in the first increment. Not to pits or modelled in-transit mass.

## 6. Implementation plan (smallest safe steps, each test-first)

1. Configuration: `opening_book`, `stock_events` (typed by `kind`), with validation. Hash unchanged when empty.
2. Domain:
   - `StorageBin.remove_loss(kg)` (available-stock check, identity clears at 0);
   - `BookLedger` with apply and refuse operations that can never touch a bin.
3. Engine:
   - schedule the events;
   - physical events post to the book automatically (receive, transfer, dispatch, posted loss);
   - measurement and admin events touch the book only;
   - refused events are logged.
4. Results:
   - `losses`, `book`, `adjustment_log`, `reconciliation`;
   - experiment figures: loss t per cause, closing discrepancy t, unexplained (must be 0).
5. Independent audit extended:
   - physical conservation with the loss term;
   - book equation;
   - reconciliation identity;
   - **ΔP = 0 for every measurement and admin entry** (rebuilt from bin records, not from the log's own claim).
6. Regression: all existing tests, the version-tolerant fingerprint, configuration hashes, the fairness baseline,
   and the prototype selftests are unchanged for configurations without stock events.

## 7. Deterministic verification cases (hand-traced before implementation)

Site: one bin B1 opening 100 t yellow maize, plus the loading and intake equipment of `tests/test_loading.py`
where needed.

| Id | Case | Expected |
|---|---|---|
| V1 | No events | R = P everywhere at all times; D = 0; results and fingerprint unchanged |
| V2 | Posted moisture loss 2 t at 10:00 | P 98 t, R 98 t, L[moisture] 2 t; D = 0; physical equation with loss holds |
| V3 | Unposted loss 2 t | P 98 t, R 100 t; D = +2 t, all "unposted loss" |
| V4 | Loss 80 t while a loading truck has 30 t committed (available 70 t) | **Refused**, logged; P, R and L unchanged; the load still completes |
| V5 | Admin +5 t on B1, then a 103 t loading order | R 105 t, P 100 t, D = +5 t "administrative"; the truck waits `STOCK_SHORT` (phantom book stock cannot be loaded) |
| V6 | Admin −120 t on B1 | **Refused** (R would be negative); nothing changes |
| V7 | Survey measures 97 t while P = 100 t | R 97 t; P 100 t; D = −3 t "measurement variance"; later loads use P |
| V8 | Opening book R0 = 105 t, P0 = 100 t | D starts at +5 t "opening difference" and carries through intake and loads |
| V9 | Loss empties B1 | B1 identity cleared; white maize may then enter (existing bin rule) |
| V10 | Losses, admin entries and a survey during a day of intake and loading | Physical equation, book equation and reconciliation identity hold after every event; independent audit clean |
| V11 | Audit fed corrupted records: an admin entry that changed bin P; a loss missing from L; an unexplained D | Each detected |
| V12 | Generated Site A day without stock events | Identical to current engine (version-tolerant fingerprint) |

## 8. Decisions that need operational confirmation (before or during implementation)

- **S1** Cleaning screenings: a **loss** leaving the system, or a **by-product** kept on site? A by-product would
  be a physical transfer to a screenings bin or commodity.
- **S2** Moisture shrink: **mass only**, or does it also change grade or moisture class?
- **S3** Losses in **pits and in transit** (handling losses during transfer), or **bins only** for now?
- **S4** Book method for shrink: post the **actual** loss, or a **formula** (shrink tables)? Formulas would be
  future work: no mechanical or process formulas in this stage.
- **S5** Regrading or reclassifying stored grain: a **physical identity change** (affects bin compatibility), or an
  **administrative relabel** (book only)?
- **S6** A loss larger than available stock: **refuse whole** (proposed), apply partially, or allow it to reduce
  committed stock?
- **S7** Measurement adjustment: **set the book to the survey** (proposed, posted as a variance), or record the
  survey without changing the book?
- **S8** Tolerances: the simulation is exact to the kg. What discrepancy threshold (e.g. % of stock) should be
  flagged in reports?
- **S9** Authority: free text recorded with each admin entry (proposed), or a fixed list of roles?
