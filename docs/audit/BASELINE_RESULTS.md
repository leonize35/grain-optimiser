# Baseline results — prototype engine v0.2.0

## Execution record

| Field | Value |
|---|---|
| Date/time | 2026-10-19T20:43:57Z |
| Engine | `SiloEngine.VERSION` = 0.2.0, extracted unchanged from artifact version `1792415835-5506` (lines 243–1193) |
| Runtime | Chromium 152.0.7977.149 (Claude desktop built-in browser), Windows 11 |
| Why not Node | Node.js is not installed on this machine. The engine was loaded headless by `extracted/run_tests.html` (no UI code), served from localhost by `serve.ps1`. |
| Command equivalent | `SiloEngine.selfTests()` |
| Result | **12 / 12 passed in 299 ms** |

## A. Prototype acceptance tests (verbatim output)

```
PASS Test 1: two different layouts run from configuration only
     2-hopper shared-elevator site and 4-hopper two-route site both ran; rule failures: 0.
PASS Test 2: changed hopper-to-bin reach is respected
     After rerouting, Hopper 3 sent 0 t to Bin B1 (expected 0).
PASS Test 3: additional hopper shares the same downstream limits
     Hopper 3 was used 12.1% of the day; Elevator 1 never exceeded one stream.
PASS Test 4: incompatible commodities never share a route at once
     71 changeovers enforced; overlap or mixing failures: 0.
PASS Test 5: fractional payloads keep the material balance
     Largest balance error 1.82e-12 t across 5 days.
PASS Test 6: arrivals reproduce the hourly profile
     Mean 195.9 arrivals per day for 200 configured; largest hourly share gap 0.75 points.
PASS Test 7: FIFO and commodity batching compared without code changes
     Changeovers FIFO 79, batching 43.
PASS Test 8: concurrent activities share the weighbridge
     Departed: 64 unloading, 6 loading, 7 weighbridge-only; weighbridge busy 33%.
PASS Reproducibility: same seed gives identical results
     Seed 42 run twice matched; seed 43 differed.
PASS Invalid layout is blocked with a plain explanation
     Hopper 2 cannot deliver Soybeans to any eligible storage bin because Top conveyor is not connected to Bin 4.
PASS Opening backlog and stock are loaded
     Opening stock 3100 t; 68 unloading trucks including 15 waiting at the gate.
PASS Sample results match their own trucks
     Highly variable grading times reorder samples; mismatches: 0.
12/12 passed in 299 ms (engine v0.2.0)
```

## B. Audit probes (written during the audit, not prototype tests)

**B1 invariant sweep**: 2 sites × demand ×1.0/1.2/1.5 × 20 seeds = 120 replications. **0 violations of any rule.**

| Site | Demand | Max balance error (t) | Mean unload turnaround ± 95% half-width (min) | Trucks still on site at end | ms/rep |
|---|---|---|---|---|---|
| A | 1.0 | 2.7e-12 | 128.3 ± 17.1 | 6.0 | 1.5 |
| A | 1.2 | 1.8e-12 | 170.7 ± 17.4 | 16.9 | 1.8 |
| A | 1.5 | 1.8e-12 | 208.8 ± 13.5 | 37.1 | 2.0 |
| B | 1.0 | 2.7e-12 | 64.4 ± 7.6 | 0.4 | 2.6 |
| B | 1.2 | 2.7e-12 | 90.9 ± 5.8 | 5.7 | 3.6 |
| B | 1.5 | 5.5e-12 | 118.2 ± 5.5 | 29.7 | 6.0 |

Observation: at higher demand, many trucks are still on site at the hard stop. Turnaround is computed **only for trucks that departed**, so the mean is biased low exactly when congestion is worst (survivorship bias). This must be fixed before the results are used for decisions.

**B2 FIFO vs feasible-first** (Site A, demand ×1.2, 20 paired seeds): mean tip wait 171.7 (FIFO) vs 148.1 min (feasible). Paired turnaround difference (feasible − FIFO) **−23.7 ± 7.2 min**. 0 violations. No fairness or starvation output exists.

**B3 head-of-line micro-fixture**: **not constructible** from configuration. Truck commodities are random draws, so "first truck blocked, second feasible" cannot be forced.

**B4 reservation scope (trace, Site A seed 1)**:
```
376.5 Transfer 33.24 t White maize: Hopper 1 > Pit conveyor 1 > Elevator 1 > Top conveyor > Bin 3
386.5 Transfer 30.69 t Yellow maize: Hopper 2 > Pit conveyor 2 > Elevator 1 > Top conveyor > Bin 1 (changeover 8 min)
403.7 Transfer 29.93 t White maize: Hopper 1 > Pit conveyor 1 > Elevator 1 > Top conveyor > Bin 3 (changeover 8 min)
420.7 Transfer 30.47 t Soybeans: Hopper 2 > Pit conveyor 2 > Elevator 1 > Top conveyor > Bin 4 (changeover 8 min)
```
This confirms whole-path, whole-lot exclusive reservation, with the elevator alternating between hoppers.

**B5 low-stock loading** (Bin 4 = 10 t soybeans, all loading trucks want soybeans): a validation warning was shown. 7 loading trucks arrived, 4 departed, 3 still waiting at close, 0 violations.

**B6 three-arm comparison** (Site A, 20 seeds, common random numbers): unload turnaround baseline 128.3, +20% demand 170.7, +20% + hopper 146.1 min. **Hopper effect under growth −24.6 ± 6.1 min** (demand-only vs demand + hopper, as FRONTEND_BUILD_PLAN requires). 0 violations.

## Numerical tolerances in use

- Material balance: |error| < 1e-6 t (engine EPS). Observed maximum is 5.5e-12 t.
- Statistical: 95% t-interval; "significant" means |mean| > half-width (paired).

## Benchmark scenarios for future parity checks

Site A and Site B (as shipped), demand ×1.0/1.2/1.5, 20 replications at base seed 20261019, together with the metrics in the B1 table. A port must match the **invariants exactly** and the **macro metrics statistically**, not path-for-path (VERIFICATION_PLAN.md).
