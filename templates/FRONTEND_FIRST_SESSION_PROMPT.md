# Ready-to-paste instruction for Claude Code

We are building an **independent, configuration-driven grain silo simulation and decision-support product**, not a FlexSim frontend. Read `CLAUDE.md`, `references/UI_UX_SCREENS.md`, `references/FRONTEND_BUILD_PLAN.md`, `references/COMPONENT_LIBRARY.md`, `references/ARCHITECTURE.md`, and `references/PROTOTYPE_INTAKE.md` before editing.

**Step 1 — Inspect, do not implement yet.** Inspect the repository, including its working engine prototype, actual tests, frontend (if any), API definitions and repository conventions. Run any existing tests that can be executed safely. Distinguish observed facts from reported features; the prototype is said to pass 12 tests, but you must verify this yourself. Assess readiness for frontend integration and enumerate missing contracts.

**Step 2 — Propose the smallest executable vertical slice.** Focus on an approved site configuration, one additional unloading hopper and +20% unloading arrivals. The interface must support My Silo → Test a Change → Validate → Run → Compare, but no claims of completed simulations unless actually returned by the engine. Preserve three experiment arms: baseline, demand-only, demand+hopper. Show topology warnings and blocking errors.

**Step 3 — Recommend frontend stack only after inspecting existing code.** State whether to extend the existing stack or start new, with trade-offs. Provide exact folder and component plan, typed API contracts, fake-data boundaries, accessible UX, and tests. Do not install dependencies, change engine files, or scaffold the app until I approve the proposal.

**Deliverables for this first response:** (a) observed project inventory, (b) test evidence, (c) missing engine/API capabilities, (d) recommended first screen and interaction, (e) planned files and milestones, (f) risks and questions requiring my domain confirmation.

Prioritise user experience: managers should not see simulation jargon, and model assurance/uncertainty must remain visible. Do not use Senwes operational records or proprietary data in any public repo or mock UI without permission.
