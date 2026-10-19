# Port log — prototype engine v0.2.0 (JavaScript) → silo_engine (Python)

Rule: each step ports one module behind tests. The JS engine in `reference/prototype_js/` stays unmodified and runnable as the oracle until parity is shown (see docs/audit/PORT_DECISION.md).

## Repository provenance (2026-10-19)

No original Git repository exists for the prototype. It was found only as the private claude.ai artifact "Silo Decision Lab" (artifact version `1792415835-5506`), which has no Git history. This repository was created new. The prototype is preserved byte-for-byte:

| File | SHA-256 |
|---|---|
| `reference/prototype_js/silo_engine_v0.2.0.js` (lines 243–1193 of the artifact) | `b46c2bc707adf27d60f405377a321366220c89fb3d7fc42dea16d960e08a1628` |
| `reference/prototype_js/silo_decision_lab_v0.2.0.html` (full artifact) | `35f39d4ef14ae4fd7af479afc9111f3d9cebff9fdf50a354eaa05749b491e5e9` |

## Step 1 — configuration schema and validation (branch `feat/config-validate-port`)

**Ported:** `buildRoutes` → `silo_engine.config.routes.build_routes`; `validate` → `silo_engine.config.validation.validate`. New: `silo_engine.config.schema` (typed pydantic model, `load_site_config`, `config_hash`).

**Behaviour proved (tests executed 2026-10-19, 44 passed):**
- For 17 configurations (prototype Site A and Site B, plus 15 broken or edge-case variants), the Python validator reproduces the prototype's output **exactly**: every error, warning and info message, their order, the equipment ids each one highlights, `ok`, hopper-to-bin and bin-to-load-point routes including tie-break order, shared-equipment users and unreachable bins.
- Route tie-breaking reproduces the browser's `localeCompare` order for letters, digits, space, `_`, `-`, `,` and `.`.
- Fault injection: replacing locale ordering with ASCII ordering, or allowing a hopper to feed a bin directly, each makes the parity tests fail.

**Intentional differences from the prototype (tested in tests/test_config_schema.py):**
1. Unknown fields are rejected, with their location reported (e.g. `equipment.3.capacity`).
2. Operating rules must be `tip ∈ {fifo, feasible, batch}`, `weigh ∈ {fifo, load_first, out_first}`, `transfer ∈ {fifo, batch, load_first}`.
3. Truck steps must be one of the six supported steps. The prototype accepts unknown steps, and a truck reaching one would never advance.
4. Weighbridge `moves` must be `in`, `out` or `both`.
5. A connection touching equipment of an unsupported type is skipped (the type itself is reported). The prototype throws a `TypeError` in this case.
6. `config_hash()`: SHA-256 of the canonical JSON, for run records (CLAUDE.md §9).

**Known limitations:**
- `locale_sort_key` approximates ICU collation. It is verified only for the characters listed above; other punctuation follows the ICU root order as documented, not as tested.
- JS objects order integer-like keys (e.g. an equipment id `"7"`) before other keys; the Python `users` dict does not. This is irrelevant for normal ids and not tested.
- Numbers in messages print like JavaScript for ordinary values. Exponent notation (below 1e-6 or at/above 1e21) differs.
- Validation semantics are inherited unchanged, including the prototype's simplifications (no truck path graph, no grade segregation, whole-route reservation assumed). Those are engine gaps (see docs/audit/GAP_MATRIX.md), not validator bugs.

**Commands run:**
- Before: `tools\run_prototype_selftests.ps1` → 12/12 passed; `pytest` → no tests.
- After: `tools\run_prototype_selftests.ps1` → 12/12 passed (twice, same engine hash); `pytest -v` → 44 passed.

**Next step:** port the event calendar with explicit tie-break tests, then a scripted-arrival fixture format, so hand-calculated trace tests become possible (GAP_MATRIX rows 2 and 41).
