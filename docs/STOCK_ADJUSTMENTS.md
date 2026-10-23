# Stock adjustments and inventory reconciliation (step 18)

Software-independent specification. Status: revised after the domain decisions S1-S9 of 2026-10-23, then implemented and
verified; results in §10. All quantities are integer kilograms.

## 1. Audit: what existed before this step

| Topic | State before step 18 |
|---|---|
| Inventories | One: the **simulated physical mass**. Bins hold tonnage + identity (commodity, grade). Pits hold lots with truck identity. A running transfer's modelled in-transit mass is counted in its source pit. |
| Opening stock | Configuration: bin `inv` / `invCommodity` (/ grade), hopper `level0` / `levelCommodity`. |
| Site boundary | In: tipped trucks. Out: loaded trucks. |
| Conservation | Opening + received − dispatched = closing, exact to the kg; checked by the engine and by the independent `checks/flow_audit.py`. |
| Adjustments, book inventory, observations | **None.** |
| Moisture | **No moisture attribute** anywhere (lots, bins, commodities, trucks). |
| Lot identity | Kept in pits; **lost inside bins** (aggregate tonnage + identity; no lot traceability). |

## 2. Three independent records

| Record | Symbol | Meaning | Changed only by |
|---|---|---|---|
| **Physical stock** | P | The grain the simulation moves (the model's truth) | Physical events: receive, transfer, dispatch, **process loss** |
| **Book inventory** | R | What the silo's records say | Postings of physical events, posted process losses, **BOOK_CORRECTION**, opening book |
| **Observed stock** | O | What a survey measured | **STOCK_MEASUREMENT** (observations are kept as a history; never applied automatically) |

**Safeguard:**
- No book or observation event has a code path to P, so an administrative correction cannot create or destroy
  physical grain.
- Loading checks use P only, so stock that exists only in the book can never be loaded.
- Conservation of P is checked to the kilogram at every event.

**Scope of R:** R is kept per **bin**. Pits and modelled in-transit mass have no book entries of their own: their
book value equals P, and no event can correct them. Site book = Σ R(bins) + Σ P(pits).

## 3. Impact of the revised decisions S7 and S2 on the first proposal

| Item | First proposal | Revised (implemented) |
|---|---|---|
| **S7: STOCK_MEASUREMENT** | Set R to the measured value (posted as a variance) | **Records an observation only.** It records O, P and R at that moment and the variances O − R and O − P, flagged against the configured tolerance. **P and R are unchanged.** |
| S7: posting a survey | (part of the measurement) | New, explicitly authorised **BOOK_CORRECTION** with `basis: "measurement"` and a reference to the observation. Its delta is computed when it is posted: O − R(now). |
| S7/S9: administrative correction | `ADMIN_ADJUSTMENT` | The same **BOOK_CORRECTION** event with `basis: "administrative"` and a signed delta. Reason and authority are required for both bases. |
| S7: reconciliation | Components included "measurement variance" | Components: opening difference, administrative corrections, survey-based corrections, unposted losses. Observation variances are reported **beside** reconciliation, not inside it. |
| S7: verification V7 | Survey 97 t → R becomes 97 t | Survey 97 t → R stays 100 t, P stays 100 t, variance −3 t. **New V7b:** BOOK_CORRECTION accepting the survey → R 97 t, D −3 t ("survey-based correction"). |
| **S2: moisture** | Cause `moisture` reduces mass | No moisture attribute exists, so a `moisture` loss is an **explicitly labelled generic physical loss** (mass only). No moisture attribute is updated, and grade and identity are unchanged. Drying and shrink calculations are deferred. The run's assumptions say so. |
| S2: verification V2 | "moisture loss 2 t" | The same quantities, plus a check that the loss is labelled generic and that bin identity and grade are unchanged. |
| S1 | Loss sink for cleaning | Only **explicitly recorded irrecoverable losses**. Recoverable screenings and by-products are a future extension, and are not called waste. |
| S8 | (open) | No universal percentage. Tolerances are optional, per site (`reconciliation`) or per run or experiment (an argument that overrides the site). Without a tolerance nothing is flagged, but every variance is still reported. |
| S9 | Free-text authority | A reason and an authority are required. Optional site list `authorised_by`: when set, the authority must be one of them. Roles belong in the operator application. |

## 4. Definitions: effect of each kind of change

| Kind | P | R | O | Lot / bin identity | D = R − P |
|---|---|---|---|---|---|
| Physical transfer (intake, load) | moves | posted identically | — | pits keep lots; bins aggregate | unchanged |
| **PROCESS_LOSS** (`moisture`, `cleaning`, `handling`, `other`), posted | −kg in the bin; `L[cause]` +kg | −kg | — | unchanged; a bin emptied clears its identity (existing rule). **No lot attribution** (bins are aggregates). | unchanged |
| PROCESS_LOSS, not posted | −kg; `L[cause]` +kg | unchanged | — | as above | **+kg** (unposted loss) |
| Opening-stock correction | configuration change (P0); new version and hash | `opening_book` (R0), default P0 | — | as configured | starts at R0 − P0 |
| **STOCK_MEASUREMENT** | unchanged | unchanged | observation recorded | unchanged | unchanged; variances O − R and O − P reported |
| **BOOK_CORRECTION**, administrative | unchanged | +delta | — | unchanged | +delta |
| **BOOK_CORRECTION**, measurement | unchanged | +(O − R at posting) | — | unchanged | +(O − R at posting) |

**Equations** (checked; per bin and for the site):
- **Physical:** `P0 + received − dispatched − Σ L = P_close`, at every event and per bin.
- **Book (per bin):** `R0 + Σ intake into the bin − Σ loads from it − Σ posted losses + Σ corrections = R_close`.
- **Reconciliation:**
  ```
  D_close = (R0 − P0) + Σ administrative corrections + Σ survey-based corrections + Σ unposted losses + U
  ```
  where U is **unexplained**. It is reported, never absorbed. In the simulation U must be exactly 0; any other value
  is an engine or audit failure.

## 5. State variables (added)

| Variable | Content |
|---|---|
| `losses` (result) | Applied losses: id, time, bin, kg, cause, posted |
| `book` (result) | R per bin at the end; history of postings |
| `observations` (result) | Per measurement: id, time, bin, O, P, R, O − R, O − P, flagged |
| `stock_log` (result) | Every stock event: applied or **refused** (with reason), ΔP, ΔR |
| `reconciliation` (result) | Per bin and for the site: P, R, D, components, U |
| Configuration | `opening_book`, `stock_events`, `reconciliation` (tolerance in tonnes and/or as a fraction of book), `authorised_by`. Left out of the configuration hash when unset, so existing hashes are unchanged. |

## 6. Events

Deterministic and scheduled, at calendar priority CONTROL. At an equal instant completions come first, as for
outages.

| Event | Inputs | Refused (logged, nothing changes) when | Effect |
|---|---|---|---|
| `process_loss` | bin, tonnes, cause, `posted` (default true), optional commodity | bin empty or holding another commodity; tonnes > **uncommitted** physical stock (S6) | P −kg; L +kg; R −kg if posted |
| `stock_measurement` | id, bin, observed tonnes | — | observation only |
| `book_correction` | bin, basis (`administrative` + signed tonnes, or `measurement` + observation id), reason, authority | missing reason or authority (configuration error); authority not in `authorised_by`; the observation has not happened yet; R would become negative | R +delta |

Physical events are never refused for book reasons. R may go negative through postings, for example when R0 < P0;
this is reported, not prevented.

## 7. Scope restrictions (not physical assumptions)

- Physical losses are applied to **bins only** in this increment (S3). Losses also occur in pits, on conveyors,
  in dryers and cleaners; they are not yet modelled.
- **Explicit quantities only** (S4): no formula shrink, no commercial deductions.
- **Not included:** regrading, reclassification (S5), recoverable by-products or screenings (S1), drying, blending.
- **Traceability:** bins are aggregates, so a loss or correction in a bin cannot be attributed to the trucks' lots
  that filled it.

## 8. Implementation plan (smallest safe increment)

1. Configuration and validation.
2. `StorageBin.remove_loss` (uncommitted-stock check; identity clears at 0).
3. `domain/book.py`: `BookLedger` and observations, which hold no reference to bins.
4. Engine: schedule events; post physical events to the book; results; mass balance includes losses.
5. Audit: physical equations with losses (bin replay incl. S6 check), book equation, reconciliation identity
   (U = 0), and observations re-derived from the replay.
6. Tests §9; full regression; version-tolerant fingerprint; fault injection.

## 9. Deterministic verification cases

Site: `tests/test_loading.py`. B1 opens with 100 t of yellow maize. L1 (30 t) loads 07:00-07:14. U1 tips 30 t
from 07:00; its lot flows into B1 after the load (07:14-07:23).

| Id | Case | Expected |
|---|---|---|
| V1 | No events | R = P per bin; D = 0; U = 0; no flags; engine fingerprint unchanged |
| V2 | Posted `moisture` loss 2 t on B1 at 07:30 (after all flows) | P 98 t, R 98 t, L[moisture] 2 t, D 0; labelled generic; identity unchanged |
| V3 | Same loss, not posted | P 98, R 100, D +2 t, all "unposted loss" |
| V4 | Loss 80 t at 07:05 while 30 t are committed to L1 (70 t uncommitted) | Refused and logged; P, R, L unchanged; the load completes; B1 closes at 100 t |
| V5 | Administrative correction +5 t at 06:00, then a 103 t loading order | R 105, P 100, D +5 t "administrative"; the order waits STOCK_SHORT (book stock cannot be loaded) |
| V6 | Administrative correction −120 t | Refused (R negative); nothing changes |
| V7 | Survey 97 t at 07:30 | O 97; P and R unchanged (100 t after U1 and L1); O − R = O − P = −3 t; flagged with a 1 t tolerance, not with 5 t, and not without a tolerance |
| V7b | V7 then a measurement-based correction at 08:00 | R 97, P 100, D −3 t "survey-based correction" |
| V8 | Opening book 105 t | D +5 t "opening difference", carried through intake and load |
| V9 | Posted loss of all 100 t on an idle B1 | B1 identity cleared; L 100 t |
| V10 | Mixed day: intake, load, posted and unposted losses, survey, both correction bases | All equations hold; U = 0; independent audit clean |
| V11 | Audit fed corrupted records: a correction that changed P; a missing loss; a tampered component; a wrong observation | Each detected |
| V12 | Validation | Missing reason or authority, unknown bin or observation, negative tonnes, authority not authorised: refused |
| V13 | Tolerance from the run argument overrides the site | Flag follows the argument |

## 10. Implementation and verification (step 18)

**Code** (no change to transfers, reservations, routing, queue policies or interruptions):

| Area | Change |
|---|---|
| Configuration | `StockEvent`, `OpeningBook`, `ReconciliationSettings`, `authorised_by` in `config/schema.py`. Left out of the configuration hash when unset. `_validate_stock` in `config/rules_validation.py`. |
| Domain | `StorageBin.check_loss` / `remove_loss` (uncommitted stock only; identity clears at 0). `domain/book.py`: `BookLedger` (book balance, postings, explanations), with no reference to bins. |
| Engine | Scheduled stock events; physical intake and loads posted to the book; `losses`, `book`, `observations`, `stock_log` and `reconciliation` (per bin + site) in results; mass balance includes losses. A generic-moisture assumption is listed when moisture losses occur. Run argument `reconciliation_tolerance` overrides the site. |
| Experiments | `losses.total_t`, `losses.<cause>_t`, `reconciliation.difference_t`, `reconciliation.unexplained_t`, `observations.flagged` |
| Audit | Bin and global equations with losses; S6 check in the bin replay; book rebuilt from postings; reconciliation components and unexplained part rebuilt; observations checked against replayed physical and book stock; refused events must change nothing. |

**Deterministic tests** (`tests/test_stock_adjustments.py`, 27, hand-traced, V1-V13 of §9):
- Two of my own test expectations were wrong and were corrected: the book at the V10 survey is 102 t, and a
  case-sensitive text check.
- The first run also showed the independent audit correctly rejecting losses before it had been taught about them.

**Further evidence:**
- **Generated days with stock events** (sites A and B; 16 events per day on 4 bins: posted and unposted moisture
  losses, surveys, survey-based and administrative corrections; both policies; 5 seeds): 20 runs, 300 events
  applied, 20 refused (every one a loss on an empty bin), 0 audit problems, unexplained 0 kg, grain balanced
  everywhere.
- **Fault injection** (9 faults, all detected):
  - a correction changing physical stock;
  - a survey silently setting the book;
  - a loss taking committed stock;
  - an unposted loss not explained;
  - a loss missing from the mass balance;
  - intake not posted;
  - a survey correction explained as administrative;
  - a refused correction still applied;
  - the flag ignoring the tolerance.
- **Normal behaviour unchanged:**
  - `pytest -q`: 337 passed, 2 expected failures (all 310 earlier tests unchanged);
  - version-tolerant engine fingerprint (32 runs) identical;
  - configuration hashes and fairness baseline unchanged;
  - prototype selftests 12/12.

**Limitations (explicit):**
- Losses apply to bins only (scope, §7).
- No moisture attribute: moisture losses are generic mass losses.
- No formula shrink or commercial deductions.
- No regrading, by-products, drying or blending.
- Bins are aggregates: no lot attribution of losses or corrections.
- Observations have no measurement-error model: O comes from the event.
- The book is kept per bin only (pits: book = physical).
