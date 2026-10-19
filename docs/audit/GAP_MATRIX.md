# Gap matrix — requirements vs prototype v0.2.0

Key: **Done** = implemented and tested by a meaningful test · **Partial** = implemented but limited or weakly tested · **Untested** = implemented, no meaningful test · **Missing** = not implemented.
Urgency: **P0** blocks a trustworthy engine · **P1** needed for a pilot · **P2** needed for a product.

| # | Requirement (source) | Implemented | Tested | Status | Urgency | Note |
|---|---|---|---|---|---|---|
| 1 | Independent DES engine, no FlexSim (CLAUDE §1) | Yes, heap calendar | T9 | **Done** | — | Keep the design. |
| 2 | Stable simultaneous-event tie-break (CLAUDE §1) | Yes: (t, class, seq) | indirect | **Partial** | P0 | Needs an explicit test. |
| 3 | Central dispatcher over pending requests (CLAUDE §2) | Three separate routines | — | **Partial** | P0 | Refactor into one dispatcher with pluggable policies and blocked reasons. |
| 4 | Feasible-first can overtake a blocked truck (CLAUDE §2) | Hoppers, weighbridges | B2 probe only | **Untested** | P0 | No deterministic fixture. |
| 5 | FIFO as a distinct documented policy (CLAUDE §2) | Yes | — | **Untested** | P0 | |
| 6 | Starvation and fairness measured (DOMAIN) | No | — | **Missing** | P1 | Max-overtake count, age at service. |
| 7 | Atomic whole-route reservation (CLAUDE §3) | Implicit check-then-claim | in-engine monitor | **Partial** | P0 | No ledger object, no release-on-failure path. |
| 8 | Configurable reservation scope (ARCH) | Fixed at whole path × whole lot | — | **Missing** | P1 | **Domain decision needed first.** |
| 9 | Typed directed graph for grain (CLAUDE §4) | Yes, typed edges and CONNECT rules | T2, T10 | **Done** | — | |
| 10 | Typed graph for truck paths (CLAUDE §4) | No: virtual queues only | — | **Missing** | P1 | Yard/lane capacity, weighbridge blocking. |
| 11 | Route feasibility incl. equipment state (ARCH) | Commodity, capacity, busy; no breakdowns | partial | **Partial** | P1 | |
| 12 | Explainable blocked reasons (ARCH) | Configuration only (validate) | T10 | **Partial** | P0 | Runtime "why is this truck waiting" is missing. |
| 13 | Quantity-aware lots, conservation (CLAUDE §5) | Float lots + ledger check | T5 | **Partial** | P0 | Decide Decimal/kg; tolerance policy; bin-full case. |
| 14 | Independent invariant checks (CLAUDE §6) | In-engine monitors | T4/T5/T8/T12 | **Partial** | P0 | Needs an event log plus a separate checker. |
| 15 | Versioned configuration, no site branches (CLAUDE §7) | Config objects, version number. **Python (2026-10-19):** typed schema, `validate()` parity on 17 golden cases, `config_hash()` | T1; pytest parity suite | **Partial** | P1 | Config storage and versioning (backend) still to do. |
| 16 | Separation engine/domain/config/experiments/API/UI (CLAUDE §8) | Engine separated from UI; rest monolithic | — | **Partial** | P1 | |
| 17 | Run metadata: engine version, config hash, data, seeds, reps, scope (CLAUDE §9) | Engine version, config version, seed, reps. Python `config_hash()` available | hash tests | **Partial** | P1 | No immutable snapshot or run record yet. |
| 18 | Unloading stream (DOMAIN) | Yes | T1/T8 | **Done** | — | |
| 19 | Loading stream (DOMAIN) | Yes, single source bin | T8 | **Partial** | P1 | No multi-bin loads, no booked windows. |
| 20 | Weighbridge-only stream (DOMAIN) | Yes | T8 | **Done** | — | |
| 21 | Sample-to-truck identity, out of order (DOMAIN) | Yes, keyed | T12 (tautological) | **Partial** | P1 | Timeout/lost-sample case missing. |
| 22 | Commodity segregation on shared paths (DOMAIN) | Yes, exclusive paths | T4 | **Partial** | P0 | |
| 23 | Changeover clearance / flush (DOMAIN) | Time penalty only | — | **Partial** | P1 | **Domain decision needed.** |
| 24 | Grade segregation (DOMAIN) | Grade drawn, not used | — | **Missing** | P2 | Confirm whether grades must be kept apart in bins. |
| 25 | Truck may leave before grain reaches bin (DOMAIN) | Assumed yes | — | **Unconfirmed** | P0 | Needs your confirmation. |
| 26 | Opening backlog and inventories (DOMAIN) | Yes | T11 | **Done** | — | |
| 27 | Shift end, carry-over, multi-day (VERIF 9) | Hard stop, single day | — | **Missing** | P1 | Turnaround is biased by trucks that never departed (B1). |
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
| 40 | Turnaround survivorship bias (found in audit) | — | — | **Defect** | P0 | Report unfinished trucks and censored waiting time. |
| 41 | Deterministic fixture input for hand-checked tests (VERIF) | No | — | **Missing** | P0 | Allow scripted arrivals with fixed commodity, quantity and times. |
