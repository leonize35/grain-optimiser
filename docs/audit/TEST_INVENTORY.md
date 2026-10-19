# Test inventory — prototype engine v0.2.0

Source: `SiloEngine.selfTests()` in `extracted/silo_engine_v0.2.0.js` (lines 862–944 of the extract). These are all the tests that exist; there are no others. All 12 ran on 2026-10-19 and **all passed** (see BASELINE_RESULTS.md).

Strength rating: **Strong** = the assertion would catch a realistic regression; **Weak** = it passes for many wrong implementations; **Tautological** = it effectively cannot fail given how the code is written.

| # | Name | Input | Assertion | Result (observed) | Strength and comment |
|---|---|---|---|---|---|
| 1 | Two different layouts run from configuration only | Site A, Site B; 3 reps each | 0 violations, and unloading trucks departed > 0 | PASS, 0 failures | **Weak.** Proves both run; says nothing about whether behaviour is correct. |
| 2 | Changed hopper-to-bin reach is respected | Site B rerouted: C4↛B4, C3→B4, H4→C1; seed 7 | Config valid, `transfers['H3>B4']` = 0, 0 violations | PASS, 0 t | **Medium.** A genuine negative test of connectivity, but only one path and one seed. |
| 3 | Additional hopper shares the same downstream limits | Site A + H3 → C1; seed 11 | 0 violations, H3 utilisation > 0, E1 utilisation ≤ 1 | PASS, H3 12.1% | **Weak.** E1 utilisation ≤ 1 holds by construction. It does not show that throughput is capped by E1. |
| 4 | Incompatible commodities never share a route at once | Site A, 50/50 yellow maize/soybeans; seed 5 | 0 violations, changeovers > 0 | PASS, 71 changeovers | **Weak.** It relies on the in-engine monitor, which sits in the code it checks. |
| 5 | Fractional payloads keep the material balance | Site A, payload 21.37/29.91/37.73; 5 reps | Maximum balance error < 1e-6, 0 violations | PASS, 1.82e-12 t | **Medium.** A real ledger check. It does not test bin-full partial transfers or end-of-day work in progress explicitly. |
| 6 | Arrivals reproduce the hourly profile | Site A, 200/day; 30 reps | Hourly share gap < 2 points, mean within ±12 of 200 | PASS, 195.9/day, 0.75 pts | **Strong** for the arrival generator. |
| 7 | FIFO and commodity batching compared without code changes | Site A FIFO vs batch; seed 3 | No violations, and changeovers **or** mean turnaround differ | PASS, 79 vs 43 changeovers | **Weak.** Passes if anything differs. It does not assert direction (batching should reduce changeovers). |
| 8 | Concurrent activities share the weighbridge | Site A; seed 9 | All three activities depart, WB1 utilisation ≤ 1, 0 violations | PASS, 64/6/7 trucks, 33% | **Weak.** Utilisation ≤ 1 holds by construction. The double-booking check is in-engine. |
| 9 | Reproducibility: same seed gives identical results | Site B, seeds 42, 42, 43 | JSON(42) = JSON(42) ≠ JSON(43) | PASS | **Strong.** |
| 10 | Invalid layout is blocked with a plain explanation | Site A minus C3→B4 | A specific error message exists **and** the run throws | PASS | **Strong.** |
| 11 | Opening backlog and stock are loaded | Site A, backlog 15; seed 2 | Opening stock = 3100 t, arrived ≥ 15 | PASS | **Medium.** |
| 12 | Sample results match their own trucks | Site B, grading time [1, 6, 25]; 3 reps | 0 `sample-match` violations | PASS, 0 | **Tautological as written.** Matching is by key, so mismatches cannot occur. It does not check that reordering actually happened, or what happens on a timeout or a lost sample. |

## Coverage against VERIFICATION_PLAN categories

| Category | Covered by | Status |
|---|---|---|
| 1 Scheduler ordering and tie-break | 9 (indirectly) | Partial: no explicit simultaneous-event test |
| 2 FIFO vs feasible-first blocking | none | **Missing.** Test 7 is FIFO vs *batch*. There is no head-of-line blocking fixture and no starvation measure. |
| 3 All-or-none reservation, no leakage, no deadlock | 4, 8 (in-engine monitor) | Weak |
| 4 Topology variation, impossible path, shared capacity not doubled | 1, 2, 3, 10 | Partial |
| 5 Commodity integrity and clearance | 4 | Partial: no clearance or flush rule exists to test |
| 6 Mass conservation | 5 | Partial: no storage-to-dispatch or bin-full case |
| 7 Sample synchronisation incl. timeout | 12 | Weak: no timeout or error case |
| 8 Concurrent streams sharing the weighbridge | 8 | Partial |
| 9 Failures and shift boundaries | none | **Missing** (feature absent) |
| 10 Stochastic inputs | 6 | Partial |
| 11 Experiments, paired, CI, failed runs | none in suite | **Missing from the suite** (exercised by audit probe B6 only) |
| 12 Job system | none | **Missing** (browser worker only) |
| 13 Model-to-observation validation | none | **Missing** (UI computes it; no test) |

## Audit probes (not part of the prototype suite)

These are in `extracted/run_tests.html`, section B. They were written during the audit for evidence and should not be counted as prototype tests: B1 invariant sweep, B2 FIFO vs feasible-first paired comparison, B3 head-of-line fixture (not constructible), B4 reservation-scope trace, B5 low-stock loading, B6 three-arm comparison. Results are in BASELINE_RESULTS.md.
