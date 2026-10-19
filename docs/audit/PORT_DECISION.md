# Port decision — recommendation pending your approval

## Options

| Option | Summary | For | Against |
|---|---|---|---|
| A. Keep JavaScript as-is | Extend the single-file engine | Zero rework; runs in the browser | No module structure, no types, no test runner, no backend. Every extension deepens the monolith. |
| B. TypeScript engine + Node backend | Move the JS engine into typed modules; same language front to back | Lowest porting risk (near line-for-line); the engine can also run in the browser for instant previews; one language for you to review | Weaker data and statistics ecosystem for SAP import, distribution fitting and reporting. Your spec states a Python preference. |
| C. **Python engine + FastAPI backend, React/TypeScript frontend** | Port the engine incrementally into a typed Python package, with the JS engine kept as the reference oracle | pandas/scipy for data preparation and fitting; pydantic for the configuration schema; pytest/hypothesis; workers (RQ/Arq); matches CLAUDE.md | About 950 lines to re-implement; Python is slower (estimated 20–50× per replication, still about 0.05–0.3 s per day of operation, **not measured**). Two languages overall. |

## Recommendation: **C, done as a restructure, not a transliteration**

The deciding argument is not the language. The engine has to change shape anyway, for reasons that apply in either language:

- one central dispatcher with pluggable policies and blocked reasons,
- an explicit reservation ledger with release on completion, cancellation and failure,
- an event log plus an independent invariant checker,
- a typed, versioned and hashed configuration schema,
- deterministic fixture input,
- multi-day horizon and censoring.

Doing that restructure in the language of the backend and data pipeline avoids doing it twice. Keep the prototype's good decisions: the heap calendar, per-entity seeded RNG (common random numbers), typed route enumeration, manager-language validation messages, and paired three-arm experiments.

## Conditions and safeguards

1. The JS engine stays runnable (`extracted/`) until parity is shown.
2. Port module by module behind tests: calendar → config schema and validation → routing → reservation ledger → dispatcher → streams → experiments.
3. Parity = **invariants exact** plus **macro metrics statistically equivalent** on the BASELINE_RESULTS benchmark grid (Site A/B × demand ×1.0/1.2/1.5 × 20 reps). Same-seed path identity is not required.
4. Every existing prototype test gets a Python equivalent, strengthened per TEST_INVENTORY.md.

## What would change this recommendation

- If you want an offline, browser-only product (no server), Option B is better.
- If Python performance measured on the benchmark grid exceeds about 1 s per replication-day, profile first, then consider a compiled core. This is unlikely to be needed.
