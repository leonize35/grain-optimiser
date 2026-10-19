# Verification and validation plan

## Prototype baseline: unverified externally
User reports **12 passing acceptance tests** from a Claude-created prototype. No code/test outputs are in this package. Import actual tests and create an inventory with: test identifier, claim, fixtures, assertions, branch/version, last run status, supporting log, gaps. Never invent names or outcomes.

## Mandatory behavioural categories (tests below are requirements, not claims of already passing tests)
1. Scheduler: chronological events, stable simultaneous-event priority/tiebreak, reproducible seeds, no events in past.
2. FIFO vs feasible-first: first truck blocked while second feasible; second progresses in feasible-first, remains queued in strict FIFO; no silent starvation.
3. Route reservations: competing paths share a conveyor/elevator; all-or-none reservation with no resource leakage; no circular wait / deadlock.
4. Capacity and topology: different graph topologies operate using identical code; impossible path blocks with clear reason; shared equipment capacity is not doubled.
5. Commodity integrity: blocked incompatible shared route; batch-close/clearance releases only after permitted transition; independent monitor catches deliberate violations.
6. Mass conservation: fractional tonnes, full loads, partial transfer, source/destination limits, storage to dispatch; all ledgers balance within defined tolerance.
7. Sample synchronisation: grading finishes out of order and matches original truck; timeout/error if unmatched.
8. Concurrent activity streams: unloading, loading and weighbridge-only share constrained weighbridge without double-booking.
9. Failures/shift boundaries: interrupted event releases or preserves reservations according to explicit policy; queues and inventories carry across operating day.
10. Stochastic inputs: time-of-day arrival distribution, nonuniform commodity mix, correlated payload if explicitly modelled.
11. Experiments: baseline and +20% demand vs +20% demand plus hopper, paired comparative settings, replication seeds, CI computation, failed run handling.
12. Job system: browser disconnect does not terminate run, asynchronous statuses, cancellation, retries and immutable scenario snapshot.
13. Model-to-observation validation: distinct site-specific checks for time-study gate-to-exit, SAP weigh-in/out, throughput and activity patterns. Document acceptance thresholds before assessing.

## Differential comparison when porting prototype
Do **not** demand identical sample paths or outputs from the same seed if RNG algorithms, consumption ordering or event scheduling differ. Compare (a) invariants exactly and (b) expected macro behaviour and statistical metrics over enough paired or independent replications with documented tolerances and power; investigate divergences. Where possible introduce deterministic event fixture traces with manually calculated expected transitions.

## Safety and transparency
A simulation can pass all code tests and still misrepresent real plant operation. Keep verification, calibration and validation distinct. Reject results from runs with invariant violations. Reports carry assurance status and assumptions. Commercial investment advice should not rely on a single unvalidated test configuration.
