# Frontend build plan — manager-facing silo decision platform

## Prerequisites and boundary
- First inspect the actual Claude prototype and its 12 reported tests; this package does not contain that code. Do not rewrite or assume an engine API exists.
- Frontend **must not depend on FlexSim**. Separate view state, API contracts and engine logic.
- Prefer existing frontend stack if code already exists. If starting clean, propose React + TypeScript with accessible components and a typed API client, then obtain approval before scaffolding.
- Mock data are allowed for design review but must be conspicuously labelled **DEMO DATA / NO SIMULATION RUN**. Never show invented results as actual analysis.
- Deliver small, testable vertical slices; do not implement all pages at once.

## Phase A — Product shell and navigation
Deliver: responsive desktop-first app shell, accessible sidebar, silo switcher, header, page titles, empty states, breadcrumbs or equivalent orientation. Routes: Dashboard, My Silo, Operating Rules, Data, Scenarios, Runs, Results, Reports. Define design tokens and reuse components rather than page-specific CSS.

Acceptance: keyboard navigation works; every route has usable loading, empty and error states; silo context remains clear; no fake operational status.

## Phase B — Configuration visualiser and editor
Deliver: equipment list and typed nodes (sampling, weighbridge, hopper, conveyor, elevator, bin), editable parameters, and directed grain/truck connections. Display the selected node and its properties; warn for disconnected components. Implement undo/revert and unsaved-change protection.

Acceptance: users can configure two materially different *supported* topologies from data; refreshing preserves server-saved config; invalid connections are rejected by backend validation. Canvas geometry must not determine routing: use graph IDs/edges.

## Phase C — Rules and input data
Deliver: manager-language rules form with progressive disclosure; CSV/Excel upload as provided by backend, mapping UI, unmatched-record preview, quality summary and clear distinctions between measured/assumed inputs.

Acceptance: manager can inspect the assumptions used by a scenario; no silent auto-correction of input data.

## Phase D — Scenario builder and pre-run validation
Deliver: select objective, create baseline and alternatives, choose equipment and demand changes, show a clear **diff**; +20% demand + hopper should generate the three-way comparison: current baseline, +20% demand unchanged equipment, +20% demand + hopper. Validate new hopper's truck access, discharge conveyor, elevator path, compatible bin, capacity and commodity rules.

Acceptance: impossible network cannot be run; warnings do not masquerade as errors; form shows a clear path to resolve each issue.

## Phase E — Asynchronous run tracking
Deliver: start run only after server READY; job ID and immutable revision, polling or event stream, completed/total replications, background continuation on page close, cancel request, failure details, retry policy.

Acceptance: reloading the browser resumes observing existing run; results link tied to exact scenario/config/engine version; UI never claims complete on partial failure.

## Phase F — Compare results and decision report
Deliver: paired scenario comparison, turnaround and queue distributions, throughput, utilisation, confidence intervals, constraints, reproducibility metadata, validation status, and report export. Label outcome assumptions and financial benefit explicitly.

Acceptance: equipment effect under demand growth is computed by comparing **demand-only** to **demand + hopper**, not current vs combined; incomplete or unvalidated analyses visibly communicate scope.

## Phase G — Usability and hardening
Test with a manager who has not used simulation software. Evaluate whether they can select a silo, configure an approved change, resolve setup errors, run and correctly interpret a comparison. Add accessibility checks, responsive layout and e2e regression tests.

## Engineering practices
- Keep typed request/response schemas and API mocking in one module. Prefer schema/code generation from OpenAPI if actual backend definitions exist.
- Unit test inputs, scenario-diff logic, permissions, metric formatting and error copy. E2E test happy path and blocked-invalid-route path.
- Display units explicitly (tonnes, t/h, minutes). Separate gate-to-exit turnaround from ERP weigh-in/out interval.
- Never encode site-specific operating constraints in frontend components; backend/engine remain authoritative.
- Users should not accidentally overwrite an approved baseline or active run input.
- For each phase: list changed files, screenshots, tests run, defects, limitations and next approval gate.
