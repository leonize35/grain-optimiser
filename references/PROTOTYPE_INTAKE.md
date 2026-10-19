# Prototype intake — FIRST DEVELOPMENT TASK

**Not provided here:** the Claude prototype source, language/framework, package files, the actual 12 tests, test execution results, or revision history. Do not reverse-engineer from descriptions or claim to have reviewed them.

Request user to add to private repository or workspace:
- All engine source files and dependency manifest.
- The acceptance test suite and recent run output.
- Configuration/sample scenarios and expected results.
- Existing README/design notes and decisions.
- License and authorship information (including third-party snippets).
- Sanitised example data; no Senwes real identifying data without rights.

## Required audit outputs before changing code
1. `PROTOTYPE_AUDIT.md`: language, folder map, actual scheduler/dispatcher design, route reservation scope, queue policy, simulation clock, random sources, supported workflows and observed gaps.
2. `TEST_INVENTORY.md`: list of *all actual* tests, objective, input, assertion, pass/fail, source paths. Do not conflate 12 reported acceptance tests with formal coverage.
3. `GAP_MATRIX.md`: requirement vs implemented vs tested vs unsupported, with urgency and scope.
4. `PORT_DECISION.md`: whether Python port offers clear advantages; alternative to retain the original implementation if fit for production, with evidence and risk.
5. `BASELINE_RESULTS.md`: captured test commands, versions and outputs, benchmark scenarios and numerical tolerances.

## Port criteria
Port only when there is a defensible reason. Port incrementally with tests. No unreviewed 'one shot' rewrite. Keep old engine runnable until parity is demonstrated; quantify behaviour across multiple seeds and baseline topologies, not same-seed path identity.

## Clarifications to put to user/domain engineer
- Which exact prototype did Claude build? Supply archive/repo.
- Does the reservation span an entire lot's route or transferable segments?
- Which policies and bin selection rules does the prototype actually implement?
- What are the 12 test assertions and their observed outputs?
- What are the actual model version and reference input datasets?
