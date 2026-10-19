# Prototype audit — Silo Decision Lab engine v0.2.0

Audit date: 2026-10-19. Status: **observed facts** unless marked *assumption* or *not inspected*.

## 1. What was found and where

| Item | Finding |
|---|---|
| Location | Not in the starter ZIP (the ZIP holds specifications only). Found as a private claude.ai artifact **"Silo Decision Lab"** (`claude.ai/artifact/X8N6xhwyuUSrbU1nHmgcgr`, updated 2026-10-19). Copied to `silo_decision_lab_v0.2.0.html`. |
| Older version | A second artifact with the same name (`MVNCzXmqb7M5CSzAd8x8F1`) is an earlier, simpler build (single-function `simulate()`, plain FIFO `seize/free`, no tests). Not the prototype under audit. |
| Language | JavaScript (ES2017), single HTML file, 2,335 lines. Engine = lines 243–1193 (951 lines) in a self-contained IIFE exporting `SiloEngine`; it also exports via `module.exports`, so it can run headless in Node or a Web Worker. Extracted to `extracted/silo_engine_v0.2.0.js`. |
| Dependencies | None (no npm packages, no SimPy, no FlexSim). Google Fonts only for UI. |
| Version control | **None.** No Git history, no package manifest, no licence/authorship file. Version string `0.2.0` only. |
| Test harness | `SiloEngine.selfTests()` returns 12 result objects; it ran from a UI button. No CI, no pytest/jest. |

## 2. Engine architecture (as implemented)

- **Event calendar:** binary-heap `Calendar`, ordered by `(time, class, insertion sequence)`, with classes 0 = completion/release, 1 = control/backlog, 2 = arrival. The ordering is deterministic and stable. An event in the past raises a `clock` violation.
- **Clock and horizon:** minutes from midnight; **one operating day** (open → close → overtime, then hard stop). There is no multi-day run, no carry-over of queue or stock to the next day, and no shift breaks.
- **Randomness:** `mulberry32` PRNG, keyed per entity: `hash(seed, activity, truckIndex)` for truck attributes and `hash(seed,'arrivals',activity)` for arrival streams. This gives good common random numbers: adding a hopper does not change the arrival stream or truck attributes.
- **Arrivals:** non-homogeneous Poisson per hour from a 24-value profile × daily volume × demand factor, plus an opening backlog per activity.
- **Truck flows:** configurable step sequence per activity (`sample, grade, weigh_in, tip, load, weigh_out`). All three streams are implemented: unloading, loading and weighbridge-only.
- **Dispatch:** there is **no single central dispatcher object**. There are three event-triggered dispatch routines:
  - `dispatchPool(kind)` for samplers, graders and weighbridges. It scans the whole queue for the first item that fits any free unit. With directional weighbridges this already behaves as feasible-first. Weighbridge policies: `fifo`, `load_first`, `out_first`.
  - `dispatchTip()` for hoppers, with policies `fifo` (head only), `feasible` (first truck with any compatible free hopper) and `batch` (each free hopper prefers its current commodity).
  - `dispatchTransfers()` for grain, a unified candidate list of hopper lots (intake) and loading trucks (load-out), ordered oldest-first or `load_first`. The `batch` transfer policy prefers routes that avoid a changeover.
- **Route model:** routes are enumerated by DFS (up to 400 paths per hopper or bin) over typed directed edges. Allowed edge types come from a `CONNECT` table. Cycles among conveyors and elevators are rejected; bins legitimately break cycles (reclaim → elevator).
- **Reservation:** check-then-claim inside a single synchronous dispatch call, so it is atomic in practice. There is no explicit reservation ledger object. What gets claimed:
  - Intake: all intermediate equipment on the path (`busy` = 1, exclusive), plus bin space (`resIn`, `resInC`), for **the whole lot or the bin's remaining space, whichever is smaller**. Partial transfers into a filling bin are supported.
  - Load-out: bin stock (`resOut`), all route equipment **and** the load point.
  - Hopper pit: space is claimed at the start of tipping. A hopper holds one commodity at a time, and one truck tips at a time.
  - Release: all claimed equipment is released at transfer end, then the engine re-dispatches transfers and tipping. **No failure or interruption path exists**, so release-on-failure is untested.
- **Commodity rules:** hopper, bin and route compatibility. A changeover is a **time penalty** (the maximum segment changeover where the last commodity differs). There is no clearance or flush state: segments are treated as empty when a transfer ends. Grade is drawn (85/15) but **not used for segregation**.
- **Grain quantities:** JavaScript `float` tonnes with tolerance `EPS = 1e-6`. Lots carry an id, truck, commodity, grade, quantity and remaining quantity. Material balance is checked after every transfer and at the end of the run.
- **Samples:** a separate entity `S<truckId>` is created at sampling, queued for grading, and matched back by id. The truck waits at the `grade` step. Out-of-order results are handled. The rejection probability is per grader.
- **Truck departure:** an unloading truck continues to weigh-out as soon as tipping finishes, without waiting for the grain to reach a bin. *This is an unconfirmed domain decision* (DOMAIN_RULES lists it).
- **Monitors:** `fail(rule, …)` calls sit **inside** the same engine functions. They record double-allocation, commodity mixing, route overlap, unsupported route, material balance, negative inventory, sample mismatch, truck completion, clock and runaway. They are useful, but **they are not independent of the logic they check**: there is no separate event-log replay.
- **Outputs:** turnaround (mean/median/p90/p95) per activity, ERP weigh-in→weigh-out interval separately, waits per step, time-weighted queues, utilisation, hopper blocked time, changeovers, tonnes per segment, grain ledger summary, hourly arrivals, optional trace and per-truck records.
- **Experiments:** `runExperiment` (seeded replications), t-based 95% CIs, `paired()` differences with a significance flag, `applyScenario` operations (add, set, policy, hours, connect, disconnect, profile), and `constraintCandidates` (add capacity to each resource in turn and measure the paired effect).
- **Validation (configuration):** `validate(cfg)` returns errors, warnings and info in manager language. It covers unsupported types, illegal connections, missing capacities, opening stock above capacity, loops, missing sequence resources, unreachable hoppers and bins, commodity-to-bin reachability (it names the missing link), payload larger than hopper capacity, loading without stock, and shared-equipment notices. **This is the strongest part of the prototype.**

## 3. UI layer (inspected in part)

Lines 1195–2335 cover: manager/advanced modes; seven tabs (My silo, Configure, Data, Performance, Test a change, Decision, Engine); configuration drafts with saved versions and an audit log; an SVG network diagram (auto layout); a Web Worker job runner with job states and cancel; CSV import (column guessing, duplicate, missing and impossible-duration exclusions, process log); fitting of four candidate distributions with a KS test; comparison of history against simulation (weigh-in→out, trucks per day, tonnes per day, with tolerances); a constraint finder; three-arm scenario runs; and an NPV-style financial view. Persistence is browser `localStorage` only. Lines 1415–1745 and 1871–2335 were **skimmed, not reviewed line by line**.

## 4. Supported workflow (observed)

Configure facility → validate → (optional) import a CSV → baseline → constraint test → test a change (hopper, capacity, policy, demand, hours) → compare paired results → financial view. Two demo facilities: Site A (2 hoppers sharing one elevator, reclaim through the same elevator) and Site B (4 hoppers on two independent lines, directional weighbridges). **Both contain illustrative values, not customer data.**

## 5. Observed gaps and weaknesses

1. **No central dispatcher abstraction.** The policy logic is spread across three closures, so adding a policy means editing engine internals. There is no explainable "blocked reason" per waiting request, which the spec requires.
2. **Reservation scope is fixed** at whole path × whole lot, exclusive even when the same commodity follows. This is safe, but it may understate throughput (ARCHITECTURE.md flags exactly this). It is not configurable.
3. **No truck path graph or yard capacity.** Trucks queue in unlimited virtual queues. There are no physical lanes, no blocking of a weighbridge by a waiting truck, and no routing restrictions for trucks.
4. **Single-day horizon only**, with no carry-over and no breakdowns or failure events.
5. **Changeover modelled as a time penalty only.** There is no segment clearance or flush state, and grade segregation is not enforced.
6. **Monitors are not independent** (see §2).
7. **Float quantities**: acceptable observed error is about 1e-12 t, but there is no declared tolerance policy.
8. **No persistence beyond the browser.** There is no server, no immutable run snapshot, and no configuration hash. Run records hold an engine version and a config version number, but not a content hash.
9. **Tests are weak** (see TEST_INVENTORY.md).
10. **No feasible-first fairness or starvation metric.** Overtaking is unbounded.
11. **No deterministic micro-fixture input.** A specific truck sequence cannot be forced from configuration, so hand-calculated trace tests are impossible today.
