# Silo Decision Platform

An independent, configuration-driven discrete-event simulation engine and decision tool for grain silos. Project rules: [CLAUDE.md](CLAUDE.md). Specifications: [references/](references/). Prototype audit: [docs/audit/](docs/audit/). Port progress: [docs/PORT_LOG.md](docs/PORT_LOG.md).

## Layout

| Path | Contents |
|---|---|
| `src/silo_engine/` | Python engine (being ported from the prototype, module by module) |
| `src/silo_engine/config/` | Site configuration schema, grain route compilation, manager-facing validation |
| `tests/` | pytest suite; `tests/golden/` holds outputs captured from the prototype engine |
| `reference/prototype_js/` | Unmodified prototype engine v0.2.0 (reference oracle) and its 12 acceptance tests |
| `tools/` | Prototype test runner and golden-file generator |

## Setup (Windows)

Use the full path to the python.org/Python install manager interpreter. The `python` Store alias runs sandboxed and cannot see some folders.

```bash
C:\Users\LeonizeMeiring\AppData\Local\Python\pythoncore-3.14-64\python.exe -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install "pydantic>=2.7" "pytest>=8"
```

## Running the tests

Python suite:

```bash
.venv\Scripts\python.exe -m pytest -q
```

Prototype's 12 acceptance tests (unmodified JS engine, headless Microsoft Edge):

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run_prototype_selftests.ps1
```

## Regenerating golden files

`tools/golden/generate_validation_golden.html` runs the prototype `validate()` on each case and posts the result to `tools/golden/serve.ps1`, which writes `tests/golden/validation_cases.json`. Start `serve.ps1`, open `http://localhost:8765/`, and the page saves the file. Regenerate only when the cases change; the oracle engine itself must not be edited.
