# Copy this into Claude after adding the actual prototype repository

Read `CLAUDE.md` and all references. Your first task is **an audit, not coding**.

Inspect the existing prototype and its actual test suite. Run tests and record full commands, version information and results. Identify whether the implementation uses a discrete-event calendar, central dispatcher, whole-route atomic reservations, feasible-first, commodity changeover, conservation ledger, truck/sample matching, all three activity streams, configurable site graph and multiple replications. Never assume a feature exists because it was discussed in ChatGPT or claimed in feedback.

Create: `PROTOTYPE_AUDIT.md`, `TEST_INVENTORY.md`, `GAP_MATRIX.md`, `PORT_DECISION.md`, and `BASELINE_RESULTS.md`. Do not rewrite the engine or port languages until I approve your evidence-based recommendation. Preserve the 12 reported acceptance tests, plus any additional tests you actually find. Identify one smallest next feature and the failing test that will establish correct behaviour. Flag IP/data/licensing blockers before any public repo or commercial deployment.
