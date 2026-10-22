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

**Next step:** after review of the interfaces and assumptions, build order item 1 in ENGINE_INTERFACES.md §7: truck stations with unlimited areas plus the dispatcher skeleton (FIFO and feasible-first), with hand-traced scripted tests.
