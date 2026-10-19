# Silo Decision Platform — persistent Claude project instructions

## Product and outcome
Build an **independent, configuration-driven discrete-event simulation (DES) engine** and manager-facing decision tool for commercial grain silos. The production runtime must not depend on FlexSim. First potential commercial customer: Senwes (not yet committed). The product is independently owned subject to verified IP rights.

**Acceptance target:** A non-programmer can configure *two materially different supported silo networks* and run reliable baseline and alternative scenarios **without a developer editing code or constructing a model**.

## Current starting point (verify, don't assume)
The user reports an existing prototype that handles whole-route reservation and feasible-first dispatch and passes **12 acceptance tests**. Its code and tests have NOT been supplied to this project package. **First inspect the actual repository and run tests**. Never imply the prototype is verified merely from the report. Preserve functionality already working, port only if technically justified, and identify coverage gaps explicitly.

## Non-negotiable architecture
1. Explicit discrete-event calendar / scheduler with reproducible tie-break rules. A plain Python heap-based event calendar is an acceptable starting point. SimPy is optional; do NOT allow SimPy FIFO Resource semantics to determine silo-specific truck dispatch or multi-resource grain-routing decisions.
2. **Central dispatchers** manage pending requests against availability, commodity compatibility, topology and policy. Feasible-first dispatch must be able to select a later eligible truck if the earliest cannot proceed. FIFO is a separate selectable policy with clearly documented meaning.
3. **Atomic whole-route reservation** for required exclusive/finite-capacity resources: validate all required capacities and commodity states and reserve as one logical transaction before movement starts, else reserve none. Document and test exception cases, partial transfers and release/cleanup.
4. Typed directed graph(s) for physical grain connectivity and truck paths. No implicit fully-connected hopppers-to-bins assumption. A route is feasible only if physical connectivity, bin compatibility, capacity, equipment state, and commodity-changeover rules all permit it.
5. Grain as quantity-aware lots (tonnes, precise numeric representation); maintain conservation through receive, transfer, storage, dispatch and explicit authorised adjustments.
6. Independent operational checks/invariants for grain conservation, no incompatible overlap, sample-to-truck identity, no double-reservation, no negative inventories, no phantom capacity, and completion consistency.
7. All site-specific parameters in **versioned configuration**, not conditional branches tied to a silo name. Support changes in layout, resource capacities, connections, demand, schedules, opening queues and inventories.
8. Separate engine, domain models, configuration validation, experiments, API/job worker, database and UI. No UI dependency in simulation core.
9. Every scenario result is associated with engine version, configuration hash, input data, policy, random seeds, replication count, model-assurance scope and limitations.
10. Never claim validation merely because tests pass. Verification checks software/rules; validation compares outputs to observations under the specific site/version/conditions.

## AI coding workflow
- **Inspect before editing.** Read code, tests, README and recent diffs. Describe discovered architecture and actual test evidence before suggesting changes.
- Work one feature at a time: failing behavioural test -> minimal implementation -> tests -> invariants -> targeted review -> commit/document.
- State assumptions, unresolved domain decisions and potential unintended interactions; do not invent rules or silently simplify them.
- Preserve and extend existing prototype tests. Do not replace working dispatch logic with a new framework because it is fashionable.
- Prefer simple, typed, testable Python; minimal dependencies. Use `pytest`, type checking and linting. Give readable diffs. Never put secrets, customer SAP data, registrations, or personally identifiable records into prompts or public repositories.
- In each completed coding response provide: changed files, behaviour proved, commands/tests actually run and their outputs, known limitations, and next small task. Don't claim tests ran without executing them.
- Avoid 'AI built it, therefore correct' reasoning. External silo operational review, empirical calibration, and independent technical/security review remain required.

## Decision-support requirements
Manager-facing workflow: My Silo -> Configure Silo -> Operating Rules -> Import Data -> Test a Change -> Validate Configuration -> Run Scenarios -> Compare Results -> Reports. Default manager mode hides code, simulation objects and scheduler settings. Advanced mode exposes assumptions, validation and diagnostics. Follow `references/UI_UX_SCREENS.md`, `references/FRONTEND_BUILD_PLAN.md` and `references/COMPONENT_LIBRARY.md` for frontend development; the first frontend Claude instruction is `templates/FRONTEND_FIRST_SESSION_PROMPT.md`. Do NOT infer revenue uplift from lower queues automatically; lost demand is unknown unless supported.

## Commercial safeguards
Before commercial use, investigate university/NWU, Senwes/research data, any employment IP claims, open-source licences and relevant insurance (including professional indemnity). Secure a proper legal opinion where needed. Do not publish customer-specific configurations or records without permission.

## Files to read in this package
- `references/ARCHITECTURE.md`
- `references/DOMAIN_RULES.md`
- `references/VERIFICATION_PLAN.md`
- `references/PROTOTYPE_INTAKE.md`
- `references/DELIVERY_PLAN.md`
- `references/UI_UX_SCREENS.md`
- `references/FRONTEND_BUILD_PLAN.md`
- `references/COMPONENT_LIBRARY.md`
- `templates/FRONTEND_FIRST_SESSION_PROMPT.md`
- `templates/ENGINE_CONTRACT.json`
- `templates/NEXT_SESSION_PROMPT.md`

When those references disagree with implementation, **flag the discrepancy**; neither the text nor the code wins without domain confirmation and tests.
