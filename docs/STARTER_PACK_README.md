# Silo Decision Platform — Claude coding starter

This is a **source-independent instruction and specification pack**, not a completed engine or verified assessment of the earlier Claude prototype.

## Use
1. Keep the prototype in a private Git repository. Confirm rights to source and data first.
2. Place these files at repository root (merge rather than overwrite existing docs).
3. Point Claude Code or Claude project at `CLAUDE.md` and paste `templates/NEXT_SESSION_PROMPT.md` for the first session.
4. Add actual source and test files; ask Claude to audit and run them before changing implementation.
5. Only after the audit, decide whether to port to Python and how to extend architecture.

## Contents
- `CLAUDE.md`: persistent coding rules.
- `references/ARCHITECTURE.md`: dispatcher and independent engine design.
- `references/DOMAIN_RULES.md`: silo behaviour and decisions requiring confirmation.
- `references/VERIFICATION_PLAN.md`: behavioural tests, differential validation.
- `references/PROTOTYPE_INTAKE.md`: prototype code intake and audit requirements.
- `references/DELIVERY_PLAN.md`: gated bootstrap programme, commercial safeguards.
- `references/UI_UX_SCREENS.md`: manager-facing screen design and UX rules.
- `references/FRONTEND_BUILD_PLAN.md`: phased, testable frontend implementation plan.
- `references/COMPONENT_LIBRARY.md`: UI component definitions and interaction contracts.
- `templates/FRONTEND_FIRST_SESSION_PROMPT.md`: prompt for Claude to audit before frontend development.
- `templates/ENGINE_CONTRACT.json`: illustrative config schema, intentionally incomplete.
- `templates/NEXT_SESSION_PROMPT.md`: first Claude session prompt.

The reported 12 tests are not included because the original code and test suite have not been provided.
