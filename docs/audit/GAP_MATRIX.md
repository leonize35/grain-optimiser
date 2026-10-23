# Gap matrix — requirements vs prototype v0.2.0

Key: **Done** = implemented and tested by a meaningful test · **Partial** = implemented but limited or weakly tested · **Untested** = implemented, no meaningful test · **Missing** = not implemented.
Urgency: **P0** blocks a trustworthy engine · **P1** needed for a pilot · **P2** needed for a product.

| # | Requirement (source) | Implemented | Tested | Status | Urgency | Note |
|---|---|---|---|---|---|---|
| 1 | Independent DES engine, no FlexSim (CLAUDE §1) | Yes, heap calendar | T9 | **Done** | — | Keep the design. |
| 2 | Stable simultaneous-event tie-break (CLAUDE §1) | Yes: (t, class, seq). **Python calendar ported 2026-10-19** | test_calendar.py | **Done** (calendar) | — | Integer ms time. |
| 3 | Central dispatcher over pending requests (CLAUDE §2) | **Python Dispatcher: stations, tipping and intake transfers through one dispatcher with reasons** | test_dispatcher.py, test_truck_stations.py | **Partial** | P0 | Loading and batching policy still to come. |
| 4 | Feasible-first can overtake a blocked truck (CLAUDE §2) | Hoppers, weighbridges | B2 probe only | **Untested** | P0 | No deterministic fixture. |
| 5 | FIFO as a distinct documented policy (CLAUDE §2) | **Python: `strict_fifo` (strict global FIFO) and `feasible_first` (work-conserving) behind one policy interface; selectable per site (`queue_policies`) and per run/experiment (2026-10-23)** | test_dispatcher.py, test_queue_policy.py | **Done** | P0 | Prototype `policies` translated by one table (`from_prototype`), not applied (noted in assumptions); equivalence with the prototype tested (test_policy_equivalence.py); equal-age intake tie-break differs; BATCH/load_first/out_first not ported. |
| 6 | Starvation and fairness measured (DOMAIN) | **Python: per-truck waiting, overtakes by later arrivals, unfinished; per-commodity waits; configurable starvation threshold; experiment figures (2026-10-23)** | test_fairness.py, test_starvation_diagnostics.py; FAIRNESS_BASELINE.md | **Done** (reporting, verified 2026-10-23) | P2 | Overtake definition ambiguities open (DOMAIN_DECISIONS §9.1); optional overtaking-limit policy to come. |
| 7 | Atomic whole-route reservation (CLAUDE §3) | **Python ReservationLedger (2026-10-22): all-or-nothing over lanes, pit space, segments, bin space; release on completed/cancelled/failed** | test_ledger_and_pit.py, test_intake_transfers.py | **Partial** | P0 | Failure/interruption paths not exercised by a running model yet. |
| 8 | Configurable reservation scope (ARCH) | **D1 confirmed; Python: exclusive by default, max_concurrent_feeds with equal sharing, merge rule, rescheduling (2026-10-22)** | test_concurrent_feeds.py | **Done** (intake) | — | Proportional sharing not built (A2). |
| 9 | Typed directed graph for grain (CLAUDE §4) | Yes, typed edges and CONNECT rules | T2, T10 | **Done** | — | |
| 10 | Typed graph for truck paths (CLAUDE §4) | **Python truck paths with finite waiting areas, blocking after service, reserve_next_space / detect_only, stall detection (2026-10-22)** | test_staging.py | **Done** (station steps) | — | Loading paths follow when loading is built. |
| 11 | Route feasibility incl. equipment state (ARCH) | Commodity, capacity, busy; no breakdowns | partial | **Partial** | P1 | |
| 12 | Explainable blocked reasons (ARCH) | Configuration only (validate) | T10 | **Partial** | P0 | Runtime "why is this truck waiting" is missing. |
| 13 | Quantity-aware lots, conservation (CLAUDE §5) | **Python: integer kg lots; independent flow audit (global, pit, bin, lot, bins and segments over time); lot-to-storage records (2026-10-23)** | test_material_flow.py, test_ledger_and_pit.py, test_storage_bin.py | **Partial** | P0 | No equipment-level contents (modelled in-transit mass only); interrupted transfers: scheduled route outages (step 17); adjustments: explicit bin losses, observations, book corrections, reconciliation (step 18); no formula shrink, by-products or regrading; bin-full = stall. |
| 14 | Independent invariant checks (CLAUDE §6) | In-engine monitors | T4/T5/T8/T12 | **Partial** | P0 | Needs an event log plus a separate checker. |
| 15 | Versioned configuration, no site branches (CLAUDE §7) | Config objects, version number. **Python (2026-10-19):** typed schema, `validate()` parity on 17 golden cases, `config_hash()` | T1; pytest parity suite | **Partial** | P1 | Config storage and versioning (backend) still to do. |
| 16 | Separation engine/domain/config/experiments/API/UI (CLAUDE §8) | Engine separated from UI; rest monolithic | — | **Partial** | P1 | |
| 17 | Run metadata: engine version, config hash, data, seeds, reps, scope (CLAUDE §9) | Engine version, config version, seed, reps. Python `config_hash()` available | hash tests | **Partial** | P1 | No immutable snapshot or run record yet. |
| 18 | Unloading stream (DOMAIN) | Yes | T1/T8 | **Done** | — | |
| 19 | Loading stream (DOMAIN) | **Python loading: load point + route + bin stock reserved atomically, setup, changeovers, grade-specific orders (2026-10-23)** | test_loading.py | **Partial** | P1 | Single source bin; no booked windows; no load_first/batch policies. |
| 20 | Weighbridge-only stream (DOMAIN) | Yes | T8 | **Done** | — | |
| 21 | Sample-to-truck identity, out of order (DOMAIN) | Yes, keyed | T12 (tautological) | **Partial** | P1 | Timeout/lost-sample case missing. |
| 22 | Commodity segregation on shared paths (DOMAIN) | Yes, exclusive paths | T4 | **Partial** | P0 | |
| 23 | Changeover clearance / flush (DOMAIN) | Time penalty only. **D3 confirmed; Python commodity-pair matrix, validation of missing/ambiguous pairs, clear_minutes (2026-10-22)** | test_changeovers.py | **Partial** | P1 | Volume-based flush specified, awaiting site confirmation. |
| 24 | Grade segregation (DOMAIN) | **D4 confirmed; Python grades end to end: bins, pits, routing, mixing rules, grading before tipping, configuration checks (2026-10-22)** | test_grades.py, test_storage_bin.py | **Done** (intake) | — | Stochastic grade mix with generated demand still to come. |
| 25 | Truck may leave before grain reaches bin (DOMAIN) | Assumed yes | — | **Unconfirmed** | P0 | Needs your confirmation. |
| 26 | Opening backlog and inventories (DOMAIN) | Yes | T11 | **Done** | — | |
| 27 | Shift end, carry-over, multi-day (VERIF 9) | **Python: admission cut-off, overtime hard stop, carry-over / send away, late arrivals, multi-day horizon (2026-10-23)** | test_operating_hours.py | **Done** | — | Single site-level cut-off. |
| 28 | Failures / breakdowns (VERIF 9) | No | — | **Missing** | P2 | |
| 29 | Time-of-day arrivals, commodity mix (VERIF 10) | Yes | T6 | **Done** | — | |
| 30 | Historical data import and preparation (PRD) | CSV import, fitting, exclusions (UI) | — | **Untested** | P1 | Move to the backend; add tests with sanitised fixtures. |
| 31 | Replications, CIs, paired comparison (VERIF 11) | Yes | probe B6 | **Untested** | P1 | |
| 32 | Three-arm scenario (baseline / demand / demand + change) (FRONTEND D) | Yes (UI) | probe B6 | **Untested** | P1 | |
| 33 | Model-to-observation validation (VERIF 13) | Three KPIs with tolerances (UI) | — | **Partial** | P1 | Thresholds need to be documented per site. |
| 34 | Async jobs survive browser disconnect (VERIF 12) | Web Worker in tab | — | **Missing** | P1 | Needs a backend worker. |
| 35 | Persistence, audit trail, multi-user (UX) | localStorage, local audit list | — | **Partial** | P1 | |
| 36 | Manager UI workflow (UX) | 7-tab prototype UI | — | **Partial** | P2 | A useful reference design, not production code. |
| 37 | Visual network editor (UX) | Auto-layout diagram + forms | — | **Partial** | P2 | Forms first; a drag-drop canvas is expensive. |
| 38 | Reports (PDF/PPT/CSV) | No | — | **Missing** | P2 | |
| 39 | Financial outcomes with explicit assumptions (UX) | NPV view | — | **Untested** | P2 | Must not infer revenue from shorter queues. |
| 40 | Turnaround survivorship bias (found in audit) | **Fixed in Python: summary reports completed, unfinished (waiting so far) and turned away; lower-bound turnaround includes unfinished** | test_operating_hours.py | **Done** | — | Prototype itself unchanged (reference). |
| 41 | Deterministic fixture input for hand-checked tests (VERIF) | **Python scripted arrivals (2026-10-19)** | test_scripted_arrivals.py | **Partial** | P0 | Not yet driving truck logic. |
