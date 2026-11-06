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

For the app and its API (optional; the engine needs only pydantic):

```bash
.venv\Scripts\python.exe -m pip install "fastapi>=0.162" "uvicorn>=0.54" "httpx>=0.28"
```

## Running the app (local only)

```bash
.venv\Scripts\python.exe tools\run_app.py
```

Then open http://127.0.0.1:8000/ in a browser. API documentation is at http://127.0.0.1:8000/docs.

- **Where silos are saved:** in `%USERPROFILE%\.silo-optimiser\store`, outside this repository. Pass `--store PATH` or set `SILO_STORE` to use another folder.
- **What the screens cover:** site and silo systems, commodities, equipment, grain connections, truck processes (with release rules), truck movement (waiting areas, paths, bypasses), the pre-run check, saving and comparing versions, and running simulations.
- **What they don't cover yet:** labour, operating rules and demand. Those are kept as loaded and can be inspected under Advanced.
- **Results:** they are simulation outputs for the configuration as entered, not validated observations.

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

`tools/golden/generate_validation_golden.html` runs the prototype `validate()` on each case and posts the result to `tools/golden/serve.ps1`, which writes `tests/golden/validation_cases.json`. Start `serve.ps1 -AllowSave`, open `http://localhost:8765/`, check the computed cases and click **Save golden file**. Without `-AllowSave` the server is read-only (it refuses saves), and the page never saves on its own. Regenerate only when the cases change; the oracle engine itself must not be edited.
