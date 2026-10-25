# Universal Silo Optimiser: requirements gap analysis and generic platform design (for review; nothing implemented)

Status (2026-10-25): an audit of the engine, configuration schema, validators and interfaces on
`feat/config-validate-port` (199d03c), against the user's twelve platform requirements (R1–R12).

**Direction (user, confirmed):** we are building one configurable simulation platform that non-programmers use to
build their own silo. Ventersdorp is the first real case-study configuration, built through the same interface as
any other site. No site-specific logic goes into the engine.

Preserved: the engine, the regression suite (451 passed, 2 xfailed), the original prototype, and the Paper 2
evidence packages. No staffing optimisation.

## 0. Audit facts (verified in code)

- **No site-specific logic in the engine.** There are no branches on site ids or names. Ventersdorp appears only in documentation links inside two comments (`calibration/fitting.py`, `experiments/staffing_search.py`). Sites A, B, C, S and the trap variant all run from configuration files.
- **Recent Ventersdorp-driven features are generic configuration fields:** `unloading_labour`, `Equipment.activities`, `Equipment.distributions`, the outcomes and clearance reporting, and the explicit-path weighbridge hold. One is narrower than it should be: `unloading_labour` applies only to the tip step (gap G6 below).
- **No API, configuration store or user interface in Python.** The only UI is the prototype HTML (`reference/prototype_js/silo_decision_lab_v0.2.0.html`), bound to the JS prototype engine. The reference documents (`references/UI_UX_SCREENS.md`, `FRONTEND_BUILD_PLAN.md`, `COMPONENT_LIBRARY.md`, `ARCHITECTURE.md`) specify screens and an indicative API but no code.
- **Two validators exist.**
  - `config/validation.py` is a port of the prototype checks: types, ids, connections allowed by type, loops, capacities, commodity compatibility, routes from hoppers to bins, payload against pit capacity, opening stock.
  - `config/rules_validation.py` covers hours, demand, grades, truck paths, outages, stock events, staffing, distributions and station activities.

  They report separately; the engine refuses to run on errors from either.
- **The process vocabulary is closed.**
  - Activities: `unload`, `load`, `weigh`.
  - Truck steps: `sample`, `grade`, `weigh_in`, `tip`, `load`, `weigh_out`, each with semantics in code.
  - Overlap exists in exactly one hardcoded form: a sample is graded off the truck, and `grade` in a truck path means "hold the current place until the result exists".

## 1. Requirements-to-code gap analysis

Status: ✅ met · ◐ partial · ✗ missing.

| # | Requirement | Existing capability (file) | Status | Gap |
|---|---|---|---|---|
| R1 | Multiple silo systems, equipment, physical connections | Flat equipment list and directed `edges`; any number of hopper→…→bin systems in one site, shared equipment allowed (Site C) (`schema.py`, `routes.py`) | ◐ | **G1:** no *system* grouping. "Silo A / Silo B" exists only as naming, so there is no per-system reporting, no per-system validation messages, and no grouping in a UI |
| R2 | Activities and sequences: receiving, dispatch, weigh-only | `sequences.unload/load/weigh`; `truck_paths`; demand per activity (`schema.py`) | ◐ | **G2:** fixed activity and step vocabularies. Receiving, dispatch and weigh-only are covered, but a site cannot add a step type (e.g. documentation office, tarpaulin check, a second inspection) without code |
| R3 | Configurable overlapping dependencies | Off-truck grading started by sampling; `grade` in a path holds the truck (`truck_flow.py` `_advance`, `_try_grade`) | ◐ | **G3:** only one overlap (sample→grade), wired in code. There is no general off-truck task, no named condition a truck waits for, and no choice of where it waits |
| R4 | Service time, occupation and release configurable separately | Service time per equipment and step (`time`, `distributions`). Occupation implicit: a truck keeps its place until it has the next (blocking, A6); `grade` adjacency extends it | ◐ | **G4:** release conditions are implicit (path adjacency, not declared), so a user cannot state "the bridge is released when weighing is done **and** the result is available". There is also a silent trap: without an explicit path the hold disappears (`tests/test_grading_blocking.py`) |
| R5 | Physical queues, bypasses, shared locations, capacities, blocking | `truck_areas` (capacity, single-file), `truck_paths` per activity, `truck_bypasses`, `located_at` (sampler at weighbridge bays), `deadlock_prevention` (`schema.py`) | ◐ | **G5:** bypasses only for trucks not needing sampling (`for: not_sampled`); shared location only for a sampler at a weighbridge; paths per activity, not per destination (separate roads to Silo A and B are impossible); no travel times |
| R6 | Equipment and labour independent; pools, skills, shifts, task requirements, release points | `operator_pools` (skills, shifts, verified), `labour` per step (operators, `whole_task`/`start_only`), `staffing_scenarios`, `crew_time`, `unloading_labour` (shared pool, task list) (`schema.py`, `ledger.py`) | ◐ | **G6:** labour phases exist only for tipping; for other steps a worker is held for the whole task or only at its start. Labour is keyed by step, not by equipment or location (one pool per step for the whole site) |
| R7 | Workers throughout a task or only during particular activities | `held: whole_task / start_only`; phased unloading tasks | ◐ | **G6** (same): phases are not available for weighing, sampling, loading or off-truck tasks |
| R8 | Grain handling, route capacity, storage compatibility, allocation, shared equipment, changeovers | Typed graph, atomic route reservation, concurrent feeds, changeover matrix, grades, bin accepts, outages, stock events (`routes.py`, `ledger.py`, `changeover.py`) | ✅ (◐) | **G7:** no internal bin-to-bin transfer jobs; allocation rules are fixed (feasible route, oldest grain first), with no configurable preference such as "fill system A first" |
| R9 | Policies separate from physical constraints | Dispatcher orders only; feasibility is decided by attempts against the ledger; policies cannot create a movement (`dispatcher.py`, `ledger.py`; `tests/test_policy_equivalence.py`) | ✅ | **G8 (minor):** the prototype-format `policies` field is accepted but ignored. A UI must hide it or map it explicitly |
| R10 | Detect missing information, incompatible rules, disconnected equipment, impossible conditions before a run | Two validators (see §0), with errors, warnings and info; the engine refuses on errors | ◐ | **G9:** no single pre-run report (two lists, no severity per location, no "how to fix" field, no machine-readable codes for a UI). Known undetected cases: (a) hold semantics lost without an explicit path; (b) clock times not representable in whole milliseconds fail at run time (`TimeFormatError`), not in validation; (c) no warning when demand exceeds storage or loading capacity over the horizon; (d) no check that an overtime cap can clear the admitted trucks given shifts; (e) unreachable truck areas or unused equipment in truck paths |
| R11 | Same engine for Sites A/B/C, Ventersdorp, others without code changes | Verified for the synthetic sites (evidence packages reproduce from configs) | ✅ for what exists | Ventersdorp needs G3–G6 to be configurable rather than coded. **No Ventersdorp-specific code will be written** |
| R12 | Non-programmers build, edit, validate, save, load, compare configurations | JSON configs loaded through `load_site_config`; `version`, `config_hash`; manager-language messages | ✗ | **G10:** no UI, API, store, version history or configuration diff. Only developers can create configurations today |

## 2. Proposed generic configuration architecture

**Principle: extend, don't rewrite.**
- The current `SiteConfig` stays the single canonical document.
- New capabilities are optional sections with defaults that reproduce today's behaviour exactly; the config hash drops unset fields, as for every recent addition.
- The existing step semantics become *named instances* of the generic primitives (§4), so old configurations keep working unchanged.

```
SiteConfig (versioned JSON; one per site version; immutable snapshot per run)
├─ site:        id, name, version, region, units
├─ systems:     [ {id, name, equipment ids} ]                    NEW (G1) grouping for UI, validation, reporting
├─ commodities, grades, grade_mixing
├─ equipment:   typed elements (station, hopper, conveyor, elevator, bin, loadpoint)
│               + activities, moves, distributions, located_at    (existing)
├─ edges:       directed grain connections                        (existing)
├─ places:      truck_areas (capacity, single_file), stations as places, travel times (later)
├─ truck_paths: per activity, optionally per destination system   (P5 later, after Q-4)
├─ processes:   per activity: steps, background tasks, holds       NEW (P1–P3); `sequences` stays as shorthand
├─ labour:      operator_pools, task requirements and phases       (P4 generalises unloading_labour)
├─ rules:       hours, end_of_day, changeovers, storage rules
├─ policies:    queue_policies (ordering only; cannot add movements)
├─ demand / inputs: arrival demand, scripted days, distributions with provenance
└─ scenarios:   named overlays (staffing, demand factor, equipment added or removed, outages)
```

Supporting layers (separate from the engine, per CLAUDE.md §8):
- **`config/report.py` (G9):** one pre-run report merging both validators, with `code`, `severity`, `location` (ids), `message`, `fix`.
- **`store/` (G10):** save and load configurations as versioned JSON with hash and history; a diff between two versions; scenario overlays applied to a base version, never editing it.
- **`api/` (G10):** a thin HTTP layer (validate, save, load, list, diff, run, results), with immutable snapshots per run. The run metadata already records the engine version, configuration hash, seeds and assumptions.
- **`ui/` (G10):** the silo builder (§3), talking only to the API, with no simulation logic.

## 3. User-facing silo builder (design)

The builder follows the workflow in `references/UI_UX_SCREENS.md`: My Silo → Configure Silo → Operating Rules →
Import Data → Test a Change → Validate → Run → Compare → Reports. It has a manager mode (plain language, defaults,
no scheduler terms) and an advanced mode (assumptions, diagnostics, policy detail). Canvas geometry never decides
routing; only ids and edges do.

| Screen | What the user does | Configuration written |
|---|---|---|
| 1. Site and systems | Name the site; add systems (e.g. "Silo A", "Silo B"); mark shared facilities | `site`, `systems` |
| 2. Equipment | Drag typed elements from a palette into a system or "shared"; fill typed forms (capacity, rate, pit tonnes, commodities, activities served, direction for weighbridges) | `equipment` |
| 3. Grain connections | Draw directed links; invalid links are refused immediately (the type rules of `ALLOWED_CONNECTIONS`); the panel highlights unreachable bins and hoppers with no route | `edges` |
| 4. Truck movement | Lay out places as a lane diagram: queues (capacity, single file), stations, bypasses (and who may use them), shared locations | `truck_areas`, `truck_paths`, `truck_bypasses`, `located_at` |
| 5. Truck processes | Per activity, a timeline with two rows: **on the truck** (steps in order: where the truck is and what is done) and **in the background** (tasks started by a step, e.g. grading). Each on-truck step has three settings: *service time*, *occupation* (holds its place until…) and *release when* (service done, and named conditions such as "grading result available"). This is where the Ventersdorp grading rule is set | `processes` (P1–P3) |
| 6. Labour | Pools (skills, shifts by period), then for each step or background task: workers needed, and whether throughout or only during named phases | `operator_pools`, task labour (P4) |
| 7. Operating rules | Hours, admission cut-off, end of day, changeovers, storage rules; queue policy in a separate box labelled "Order of service: cannot override physical limits" | `hours`, `end_of_day`, `changeovers`, `queue_policies` |
| 8. Demand and data | Arrival demand per activity and period; fitted distributions from time studies (`calibration.fitting`), with provenance; measured, calibrated and assumed labels | `demand`, `distributions` |
| 9. Validate | A pre-run checklist grouped as Errors, Warnings, Notes; each item says what, where (click to locate) and how to fix; Run is enabled only without errors | `config/report.py` output |
| 10. Versions and compare | Save a version with a note; load; diff two versions (equipment, links, rules, labour); build scenarios as overlays; compare results with paired statistics and the measurement framework | `store`, scenarios |

## 4. Minimum new modelling primitives

Only what R3, R4, R6 and R7 need. Each primitive generalises a mechanism that already exists and is verified.

| Primitive | Generalises | Configuration (sketch) | Semantics |
|---|---|---|---|
| **P1 Background task** | Off-truck grading after sampling | `background_tasks: [{id: "grading", started_by: "sample", equipment_type: "grader", time: …, labour: …, produces: "graded"}]` | When the step `started_by` finishes for a truck, the task is queued for that truck's item (sample or document). It uses equipment lanes and labour like any task. When done, it sets the named condition `produces` for that truck. It never occupies a truck place |
| **P2 Condition** | The grading result | Named per truck: `graded`, `documents_ready`, … (produced by background tasks) | A boolean per truck, set once with its time; visible in traces and audits |
| **P3 Release rule (occupation vs service)** | Implicit blocking plus `grade` in a path | Per path step: `release_when: ["service_done", "graded"]` (default `["service_done"]`) | The truck holds the place from service start until every listed condition holds **and** it has its next place. Service time is unaffected. `release_when` replaces "grade must follow weigh_in in an explicit path": the Ventersdorp rule becomes `weigh_in: release_when [service_done, graded]` |
| **P4 Task phases with labour** | `unloading_labour` (tip only), `held` | Per step or background task: `phases: [{id, time or "service", workers, pool, truck_present}]` | One step is a sequence of phases, each with its own workers, released between phases. A worker does one task at a time. Today's `unloading_labour` becomes phases on `tip`, and `held: start_only` becomes a one-phase rule |
| P5 Destination-dependent path *(later, after Q-4)* | Paths per activity | `truck_paths.unload.by_system: {A: […], B: […]}` | Branch after assignment, so different systems can have different roads and queues |
| P6 Travel time *(later, if material)* | — | `places[].travel_min` | A dwell when moving between places |

**Backward compatibility rule (tested):** with P1–P4 unset, an existing configuration compiles to exactly today's
behaviour:
- `sequences`, `truck_paths`, `grade` in a path, `labour`, `held` and `unloading_labour` are expressed internally as P1–P4 instances;
- every existing test passes unchanged;
- both evidence packages reproduce byte for byte.

## 5. Implementation plan (each step test-first; reproduction check before every commit)

| Step | Work | Deterministic verification |
|---|---|---|
| 0 | Move the simulation-only reproduction scripts from scratch into `tools/` (`repro_check.py`) so anyone can run them | Running them reports 84/84 and 105/105 identical |
| 1 | **Unified pre-run report** (G9): merge the validators; add codes, locations and fixes; new checks (a)–(e) from §1 R10 | One test per check, with a minimal config that triggers it and one that does not; existing message wording kept (parity tests) |
| 2 | **Systems** (G1): optional `systems`; per-system validation messages and per-system outcomes (trucks are attributed to a system once they reach its hopper, otherwise "unassigned") | Hand-traced two-system test; per-system figures sum to the site |
| 3 | **P2 + P3 conditions and release rules**, with today's grading hold re-expressed as `release_when: [service_done, graded]` | `tests/test_grading_blocking.py` passes with the *new* form and gives identical traces to the old form; a config with neither keeps today's behaviour; a new test without an explicit path now holds the bridge when `release_when` says so |
| 4 | **P1 background tasks**; grading becomes one instance; a second, user-defined task (e.g. documents) proves generality | Hand-traced: two background tasks with different durations, a release waiting for both; equivalence with existing grading tests |
| 5 | **P4 phases for any step**; `unloading_labour` re-expressed as tip phases; weighing with a clerk only at the start | `tests/test_unloading_labour.py` passes through the new form, with identical traces; hand-traced phased weighing |
| 6 | **Generic step types** (G2): a configurable station-service step (name, station type, phases) so a site can add a step without code | A synthetic site with an extra "documents" station runs, validates and audits |
| 7 | **Store and diff** (G10): versioned save and load, history, diff, scenario overlays | Round trip save→load gives the identical hash; the diff lists exactly the changed fields; an overlay never edits the base |
| 8 | **API** (G10): validate, save, load, diff, run (async job, snapshot), results | API tests with an in-process client; a run records the engine version, config hash, seeds and assumptions; invalid configs are refused with the report |
| 9 | **Silo builder UI**, in vertical slices (screens 1–3, then 4–5, then 6–10). Stack per `FRONTEND_BUILD_PLAN.md` (React + TypeScript proposed; needs your approval before scaffolding) | Component tests and end-to-end tests: build Site A from an empty builder and get a hash-identical config to `evidence/configs/site_a.json`; an invalid link is refused; an impossible scenario cannot run |
| 10 | P5 and P6, only when Q-4 and travel-time evidence require them | Hand-traced branch and dwell tests |

Steps 1–6 are engine and configuration work. Steps 7–9 are the platform. Dependencies such as an HTTP framework and
a frontend stack are proposed when those steps arrive, and need your approval.

## 6. Demonstration: Ventersdorp built entirely through configuration

**Acceptance:**
- the Ventersdorp configuration is created **only** through the builder or API;
- `git diff src/` is empty for the whole demonstration;
- the same engine version then runs Sites A, B and C (unchanged results) and Ventersdorp.

| Demo step | Builder screen | Ventersdorp content (source) | Primitive |
|---|---|---|---|
| 1 | Site and systems | Systems "Silo A", "Silo B"; shared facilities | `systems` |
| 2 | Equipment | Receiving sampler (shared, receiving only); incoming weighbridge (`moves: in`); outgoing weighbridge (`moves: out`); loading sampling point(s); hoppers, conveyors, elevators, bins, load points per silo (**PLC layouts, D-5/D-6**) | existing fields |
| 3 | Grain connections | Routes and interconnects from the PLC layouts, as confirmed by the silo manager | `edges` |
| 4 | Truck movement | Weighbridge queue and other waiting places with capacities (**Q-4**) | `truck_areas`, `truck_paths` |
| 5 | Truck processes | Receiving: sample → weigh in (release when weighed **and** graded) → hopper (assigned after grading) → unload → weigh out. Loading: weigh in → load → sample (loading point) → weigh out. Weigh-only per **Q-12**. Grading as a background task started by sampling | P1, P2, P3 |
| 6 | Labour | One shared unloading pool (~4, by period), tasks positioning, assisting, scraping, sweeping (**Q-3, Q-6**); sampling 2 (collector; runner as part of the grading task); weighbridge 2–3 (**Q-5**) | P4 |
| 7 | Operating rules | Hours by period (**D-4**); admission cut-off; admitted trucks processed to completion (overtime cap with clearance reporting); FIFO policy (exceptions **Q-13** not modelled) | existing |
| 8 | Demand and data | Arrival profile per period (**D-2, D-3**); fitted service times (**D-1**) with provenance | `distributions`, `calibration.fitting` |
| 9 | Validate | Zero errors; warnings reviewed | report |
| 10 | Save, run, compare | Baseline version saved; baseline run with every assumption listed. **Not a validated model** until compared with held-out historical data (AC-7) | store, API |

Until the data and answers arrive, the demonstration uses a **labelled placeholder** Ventersdorp-shaped
configuration (structure only, no site numbers), stored privately and not in the public repository. Every
screen and primitive can be exercised with it.

## 7. Decisions for you

1. Approve the primitives P1–P4 and the backward-compatibility rule (old configurations compile to identical behaviour).
2. Approve the step order: engine and configuration (1–6) before the store, API and UI (7–9).
3. The frontend stack and the HTTP framework (proposed when step 8 starts).
4. Where private case-study configurations are stored (the repository is public).
