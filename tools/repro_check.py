"""Check that the current engine reproduces the stored evidence packages (read-only; nothing is written to evidence/).

    python tools/repro_check.py              all three checks
    python tools/repro_check.py baseline     paper2-v1 simulation outputs
    python tools/repro_check.py sampling     paper2-ext-sampling-v1 (all deterministic files)
    python tools/repro_check.py hashes       stored configuration hashes

`tools/evidence_run.py check` also compares the files that record test-suite outcomes and the engine source hash,
which change whenever code or tests change, and writes its verdict into evidence/out. This tool compares the
simulation outputs only, rebuilding into a temporary folder. Expected: every compared file identical, no
configuration hash differing.
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

# Files of paper2-v1 that record test-suite outcomes or summarise them, not simulation outputs.
BASELINE_EXCLUDED = ("experiments/EV-T1/", "EVIDENCE_SUMMARY.md", "experiments/EV-X1/", "experiments/EV-R1/", "tests/")


def _stored(package: str) -> dict:
    return json.loads((ROOT / "evidence" / "out" / package / "manifest.json").read_text(encoding="utf-8"))


def baseline() -> dict:
    from tools.evidence.runner import build
    stored = _stored("paper2-v1")["deterministic_files"]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "pkg"
        build(out, with_tests=False, quick=False, log=lambda *a: None)
        fresh = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["deterministic_files"]
    keys = sorted(k for k in stored if not k.startswith(BASELINE_EXCLUDED))
    return {"package": "paper2-v1", "compared": len(keys), "differing": [k for k in keys if stored[k] != fresh.get(k)],
            "excluded": list(BASELINE_EXCLUDED)}


def sampling() -> dict:
    from tools.evidence import sampling_ext
    stored = _stored("paper2-ext-sampling-v1")["deterministic_files"]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "pkg"
        sampling_ext.build(out, log=lambda *a: None)
        fresh = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["deterministic_files"]
    keys = sorted(set(stored) | set(fresh))
    return {"package": "paper2-ext-sampling-v1", "compared": len(keys),
            "differing": [k for k in keys if stored.get(k) != fresh.get(k)]}


def hashes() -> dict:
    from silo_engine.config import load_site_config
    from silo_engine.config.schema import config_hash
    from tools.evidence.sampling_ext import access_config
    ext = _stored("paper2-ext-sampling-v1")["config_hashes"]
    base = _stored("paper2-v1")["configurations"]
    differing = [k for k, h in ext.items()
                 if config_hash(load_site_config(copy.deepcopy(access_config(*k.split("/"), 1.0)))) != h]
    for k, v in base.items():
        raw = json.loads((ROOT / "evidence" / "configs" / Path(v["file"]).name).read_text(encoding="utf-8"))
        if config_hash(load_site_config(raw)) != v["config_hash"]:
            differing.append(f"paper2-v1/{k}")
    return {"compared": len(ext) + len(base), "differing": differing}


CHECKS = {"baseline": baseline, "sampling": sampling, "hashes": hashes}

if __name__ == "__main__":
    chosen = sys.argv[1:] or list(CHECKS)
    results = {name: CHECKS[name]() for name in chosen}
    print(json.dumps(results, indent=1))
    sys.exit(0 if all(not r["differing"] for r in results.values()) else 1)
