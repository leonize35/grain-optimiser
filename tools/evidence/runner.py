"""Reproducible evidence runner for Paper 2 (docs/evidence/EVIDENCE_READINESS.md §6).

Writes one evidence package. Its files fall into three groups:

- deterministic model outputs (compared by reproduction checks): saved configurations, experiment settings,
  per-run results, audit results, event traces (replication 0 of each cell, gzip without timestamps), digests,
  test outcomes, structural comparison, summary;
- environment metadata (never compared): `environment/` (time, platform, versions, git state, raw JUnit report with
  timings, raw prototype self-test output);
- `manifest.json`: the deterministic inputs and the sha256 of every deterministic output file.

Verification only. All configurations are synthetic; no output is an observation of a real silo.
The engine is used through its public API and is not modified.
"""
import copy
import dataclasses
import gzip
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from importlib import metadata
from pathlib import Path

from silo_engine import VERSION
from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config, validate
from silo_engine.config.rules_validation import validate_rules
from silo_engine.config.schema import config_hash
from silo_engine.experiments.runner import kpis_of
from silo_engine.inputs.generated import generate_arrivals
from silo_engine.sim.random_streams import derived_seed
from silo_engine.sim.service_times import StochasticServiceTimes
from silo_engine.sim.truck_flow import TruckFlowModel

from .policies import MAPPINGS, describe, policy_for
from .structure import markdown, structure

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ID = "paper2-v1"
BASE_SEED = 20261023
CONFIGS = ROOT / "evidence" / "configs"
OVERLAYS = ROOT / "evidence" / "overlays"
SITES = {"A": "site_a.json", "B": "site_b.json", "C": "site_c.json", "C-trap": "site_c_segregation_trap.json"}
SEEDS = range(5)


# ---------------------------------------------------------------- helpers
def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False, default=_plain) + "\n"


def _plain(x):
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return dataclasses.asdict(x)
    if isinstance(x, (set, frozenset)):
        return sorted(x)
    return repr(x)


def sha_text(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))  # LF line ends on every platform


def write_gz(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0) as gz:  # no timestamp, no name: deterministic
        gz.write(text.encode("utf-8"))
    path.write_bytes(buf.getvalue())


def engine_source_sha() -> str:
    h = hashlib.sha256()
    for p in sorted((ROOT / "src").rglob("*.py")):
        h.update(p.relative_to(ROOT).as_posix().encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def load_raw(site: str, overlays: tuple[str, ...] = ()) -> dict:
    raw = json.loads((CONFIGS / SITES[site]).read_text(encoding="utf-8"))
    for name in overlays:
        extra = json.loads((OVERLAYS / f"{name}.json").read_text(encoding="utf-8"))
        for k, v in extra.items():
            if not k.startswith("_"):
                raw[k] = copy.deepcopy(v)
    return raw


# ---------------------------------------------------------------- one run
def run_cell(cell: dict, keep_model: bool = False):
    """Run one replication. `cell`: exp, site, overlays, policy, seed_index, demand, days."""
    raw = load_raw(cell["site"], tuple(cell.get("overlays", ())))
    site = load_site_config(copy.deepcopy(raw))
    seed = derived_seed(BASE_SEED, "replication", cell["seed_index"])
    trucks = generate_arrivals(site, seed, days=cell.get("days", 1), demand_factor=cell.get("demand", 1.0))
    mapping = policy_for(cell["policy"], seed)
    model = TruckFlowModel(site, trucks, StochasticServiceTimes(site, seed), policy=mapping, days=cell.get("days", 1))
    r = model.run()
    audit = audit_flow(site, trucks, r)
    trace = "".join(json.dumps([e.time, e.priority, e.seq, e.label, e.cancelled]) + "\n" for e in r.trace)
    decisions = canonical({"trace_sha256": sha_text(trace), "transfers": r.transfers, "loads": r.loads,
                           "records": r.records})
    waiting_end = model.waiting_reasons()
    stall_codes = Counter(w.code for ws in r.stall.waiting.values() for w in ws) if r.stall else Counter()
    end_codes = Counter(w.code for ws in waiting_end.values() for w in ws)
    rec = r.reconciliation.get("site")
    record = {
        "cell": cell_id(cell), "settings": cell, "seed": seed, "config_hash": config_hash(site),
        "policy_mapping": describe(mapping), "policy_source": r.policy_source,
        "physical": {  # verification: must hold in every run
            "audit_problems": len(audit.problems), "material_balance_kg": r.material_balance_kg,
            "engine_violations": len(r.violations), "unexplained_kg": rec.unexplained_kg if rec else 0,
            "in_transit_at_end": len(audit.in_transit)},
        "operational": {  # reported separately: a stall is an operational outcome, not a verification failure
            "stalled": r.stall is not None, "stall_time_ms": r.stall.time if r.stall else None,
            "stall_reason_codes": dict(sorted(stall_codes.items())),
            "trucks": len(r.records), "completed": sum(1 for x in r.records if x.departed is not None),
            "unfinished": len(r.unfinished), "turned_away": sum(1 for x in r.records if x.turned_away),
            "waiting_at_end_reason_codes": dict(sorted(end_codes.items())),
            "suspensions": sum(len(x.interruptions) for x in [*r.transfers, *r.loads]),
            "stock_events_refused": sum(1 for e in r.stock_log if not e.applied)},
        "kpis": kpis_of(r),
        "trace_sha256": sha_text(trace), "decisions_sha256": sha_text(decisions),
    }
    record["run_sha256"] = sha_text(canonical(record))
    out = (record, {"cell": record["cell"], "problems": audit.problems, "in_transit": audit.in_transit,
                    "checked": audit.checked}, trace)
    return out + ((model, r, site, trucks) if keep_model else ())


def cell_id(cell: dict) -> str:
    ov = "+".join(cell.get("overlays", ())) or "base"
    return f"{cell['exp']}/{cell['site']}/{ov}/{cell['policy']}/d{cell.get('demand', 1.0)}/s{cell['seed_index']}"


# ---------------------------------------------------------------- experiment plan
def plan() -> dict[str, dict]:
    cells = lambda exp, sites, policies, demands=(1.0,), overlays=lambda s: (), seeds=SEEDS: [  # noqa: E731
        {"exp": exp, "site": s, "overlays": list(overlays(s)), "policy": p, "seed_index": i, "demand": d, "days": 1}
        for s in sites for p in policies for d in demands for i in seeds]
    disturbance = lambda s: (f"disturbance_{SITES[s][:-5]}",)  # noqa: E731
    return {
        "EV-C1": {"claim": "Physical grain conservation", "cells": cells("EV-C1", ["A", "B", "C"], ["M-FF", "M-PT", "M-SF"], (1.0, 1.2))},
        "EV-C2": {"claim": "Conservation under scheduled outages and stock events",
                  "cells": cells("EV-C2", ["A", "B", "C"], ["M-FF", "M-PT"], overlays=disturbance)},
        "EV-F2": {"claim": "Route feasibility: alternative route used while equipment is unavailable",
                  "cells": [c for ov in ("site_c_en1_outage_from_start", "site_c_en1_outage")
                            for c in cells("EV-F2", ["C"], ["M-FF"], overlays=lambda s, ov=ov: (ov,))]},
        "EV-S2": {"claim": "Segregation risk is reported, physics preserved (trap variant)",
                  "cells": cells("EV-S2", ["C-trap"], ["M-FF", "M-PT", "M-SF"])},
        "EV-P1": {"claim": "Physical invariants independent of the queue policy (adversarial policies)",
                  "cells": cells("EV-P1", ["A", "B", "C"], ["ADV-REV", "ADV-RAND", "ADV-RHOL"])},
        "EV-P2": {"claim": "Reporting threshold does not change decisions",
                  "cells": [c for t in (0, 120, 10000) for c in cells("EV-P2", ["A", "B", "C"], ["M-FF"], seeds=range(3),
                                                                      overlays=lambda s, t=t: (f"starvation_threshold_{t}",))]},
    }


# ---------------------------------------------------------------- evaluations
def evaluate(exp: str, runs: list[dict], extra: dict) -> dict:
    phys_ok = all(r["physical"]["audit_problems"] == 0 and r["physical"]["material_balance_kg"] == 0
                  and r["physical"]["engine_violations"] == 0 and r["physical"]["unexplained_kg"] == 0 for r in runs)
    stalls = sum(r["operational"]["stalled"] for r in runs)
    base = {"runs": len(runs), "physical_invariants_hold": phys_ok,
            "audit_problems_total": sum(r["physical"]["audit_problems"] for r in runs),
            "max_abs_balance_kg": max(abs(r["physical"]["material_balance_kg"]) for r in runs),
            "stalled_runs": stalls, "unfinished_trucks_total": sum(r["operational"]["unfinished"] for r in runs),
            "trucks_total": sum(r["operational"]["trucks"] for r in runs)}
    if exp == "EV-C2":
        base["suspensions_total"] = sum(r["operational"]["suspensions"] for r in runs)
        base["stock_events_refused_total"] = sum(r["operational"]["stock_events_refused"] for r in runs)
        base["accepted"] = phys_ok
    elif exp == "EV-F2":
        by = {}
        for r, n in zip(runs, extra["alt_counts"]):
            by.setdefault(r["settings"]["overlays"][0], []).append(n)
        base["alternative_route_transfers_during_outage_per_run"] = by
        base["observation_mid_day_outage"] = (
            "With EN1 stopping at 08:00 a transfer running on CN1->EN1 is suspended and, under the provisional hold "
            "rule I1, keeps CN1 reserved; the alternative CN1->EN2 route then cannot be used during the outage.")
        base["accepted"] = phys_ok and all(n >= 1 for n in by.get("site_c_en1_outage_from_start", [0]))
    elif exp == "EV-S2":
        by = {}
        for r in runs:
            b = by.setdefault(r["settings"]["policy"], {"runs": 0, "stalled": 0, "stall_reason_codes": Counter()})
            b["runs"] += 1
            b["stalled"] += r["operational"]["stalled"]
            b["stall_reason_codes"].update(r["operational"]["stall_reason_codes"])
        base["by_policy"] = {k: {**v, "stall_reason_codes": dict(sorted(v["stall_reason_codes"].items()))} for k, v in by.items()}
        base["accepted"] = phys_ok and all(not r["operational"]["stalled"] or r["operational"]["stall_reason_codes"] for r in runs)
    elif exp == "EV-P1":
        by = {}
        for r in runs:
            b = by.setdefault(f"{r['settings']['site']}/{r['settings']['policy']}", {"runs": 0, "stalled": 0, "unfinished": 0, "completed": 0})
            b["runs"] += 1
            b["stalled"] += r["operational"]["stalled"]
            b["unfinished"] += r["operational"]["unfinished"]
            b["completed"] += r["operational"]["completed"]
        base["operational_by_site_policy"] = by
        base["accepted"] = phys_ok  # stalls are reported, not failures
    elif exp == "EV-P2":
        groups = {}
        for r in runs:
            key = (r["settings"]["site"], r["settings"]["seed_index"])
            groups.setdefault(key, set()).add(r["decisions_sha256"])
        base["cells_with_identical_decisions"] = sum(1 for v in groups.values() if len(v) == 1)
        base["cells"] = len(groups)
        base["accepted"] = phys_ok and all(len(v) == 1 for v in groups.values())
    else:
        base["accepted"] = phys_ok
    return base


def alt_route_counts(cells: list[dict]) -> list[int]:
    out = []
    for cell in cells:
        _, _, _, model, r, _, _ = run_cell(cell, keep_model=True)
        o = json.loads((OVERLAYS / f"{cell['overlays'][0]}.json").read_text(encoding="utf-8"))["outages"][0]
        start, end = (int(o[k][:2]) * 3_600_000 + int(o[k][3:]) * 60_000 for k in ("start", "end"))
        out.append(sum(1 for x in r.transfers if x.path[1:3] == ["CN1", "EN2"] and start <= x.started < end))
    return out


def corruption_sensitivity() -> dict:
    """EV-C3: corrupt the records of a valid run in known ways; the audit must detect every one."""
    cell = {"exp": "EV-C3", "site": "C", "overlays": ["disturbance_site_c"], "policy": "M-FF", "seed_index": 0,
            "demand": 1.0, "days": 1}
    record, audit, _, model, r, site, trucks = run_cell(cell, keep_model=True)
    assert not audit["problems"]

    def first(xs, pred):
        return next((i for i, x in enumerate(xs) if pred(x)), None)

    corruptions = {
        "bin closing +1 kg": lambda b: b.bins.__setitem__(next(iter(b.bins)), (next(iter(b.bins.values()))[0] + 1, next(iter(b.bins.values()))[1])),
        "pit closing set to 1 kg": lambda b: b.pits.__setitem__(next(iter(b.pits)), 1),
        "duplicate transfer record": lambda b: b.transfers.append(dataclasses.replace(b.transfers[0], id="dup")),
        "transfer moves 5 t more": lambda b: b.transfers.__setitem__(0, dataclasses.replace(b.transfers[0], kg=b.transfers[0].kg + 5000)),
        "transfer starts before its lot was tipped": lambda b: (lambda i: b.transfers.__setitem__(
            i, dataclasses.replace(b.transfers[i], started=0)))(first(b.transfers, lambda x: x.truck_id is not None)),
        "route released before the grain finished": lambda b: (lambda i: b.transfers.__setitem__(
            i, dataclasses.replace(b.transfers[i], released=b.transfers[i].finished - 1)))(first(b.transfers, lambda x: x.finished is not None)),
        "received counter +1 kg": lambda b: setattr(b, "received_kg", b.received_kg + 1),
        "process losses dropped": lambda b: b.losses.clear(),
        "book +1 kg": lambda b: b.book.__setitem__(next(iter(b.book)), next(iter(b.book.values())) + 1),
        "reconciliation component altered": lambda b: b.reconciliation.__setitem__(
            b.losses[0].bin, dataclasses.replace(b.reconciliation[b.losses[0].bin], unposted_loss_kg=0)),
        "observation altered": lambda b: b.observations.__setitem__(0, dataclasses.replace(b.observations[0], physical_kg=1)),
        "suspension removed (flow through unavailable equipment)": lambda b: b.transfers[first(b.transfers, lambda x: x.interruptions)].interruptions.clear(),
    }
    outcome = {}
    for name, fn in corruptions.items():
        bad = copy.deepcopy(r)
        try:
            fn(bad)
        except (IndexError, StopIteration, TypeError):
            outcome[name] = "not applicable"
            continue
        outcome[name] = "detected" if audit_flow(site, trucks, bad).problems else "MISSED"
    applicable = [v for v in outcome.values() if v != "not applicable"]
    return {"base_run": record["cell"], "base_run_sha256": record["run_sha256"], "corruptions": outcome,
            "detected": sum(v == "detected" for v in applicable), "applicable": len(applicable),
            "accepted": bool(applicable) and all(v == "detected" for v in applicable)}


SITE_NAME_WORDS = ("ventersdorp", "senwes", "site a", "site b", "site c", "siteA", "siteB")


def site_constant_scan() -> dict:
    """EV-T2: no equipment id of any evidence configuration and no site name appears as a string constant or a name
    in the engine's code (docstrings and comments are excluded: they may cite examples)."""
    import ast
    ids = set()
    for f in SITES.values():
        ids |= {e["id"] for e in json.loads((CONFIGS / f).read_text(encoding="utf-8"))["equipment"]}
    hits = []
    for p in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
                if n.value in ids or any(re.search(rf"{re.escape(w)}", n.value, re.IGNORECASE) for w in SITE_NAME_WORDS):
                    hits.append(f"{p.relative_to(ROOT).as_posix()}:{n.lineno}: {n.value!r}")
            elif isinstance(n, ast.Name) and n.id in ids:
                hits.append(f"{p.relative_to(ROOT).as_posix()}:{n.lineno}: name {n.id}")
    return {"equipment_ids_checked": len(ids), "site_name_words": list(SITE_NAME_WORDS), "hits": hits,
            "accepted": not hits}


def feasibility_checks() -> dict:
    """EV-F1 (part) and EV-T1: every evidence configuration passes both validators with the same engine."""
    out = {}
    for label, f in SITES.items():
        site = load_site_config(json.loads((CONFIGS / f).read_text(encoding="utf-8")))
        v, rules = validate(site), validate_rules(site)
        out[label] = {"file": f"evidence/configs/{f}", "config_hash": config_hash(site), "prototype_validate_ok": v.ok,
                      "prototype_validate_errors": len(v.errors), "rules_errors": [i.msg for i in rules.errors]}
    return {"configs": out, "accepted": all(x["prototype_validate_ok"] and not x["rules_errors"] for x in out.values())}


def run_pytest(env_dir: Path) -> dict:
    junit = env_dir / "pytest-junit.xml"
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"],
                          cwd=ROOT, capture_output=True, text=True)
    write(env_dir / "pytest-output.txt", proc.stdout[-20000:])
    outcomes = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        nodeid = f"{case.get('classname')}::{case.get('name')}"
        kinds = {c.tag for c in case}
        skipped = case.find("skipped")
        if "failure" in kinds:
            outcomes[nodeid] = "failed"
        elif "error" in kinds:
            outcomes[nodeid] = "error"
        elif skipped is not None:
            outcomes[nodeid] = "xfailed" if (skipped.get("type") or "").endswith("xfail") else "skipped"
        else:
            outcomes[nodeid] = "passed"
    counts = Counter(outcomes.values())
    return {"outcomes": dict(sorted(outcomes.items())), "counts": dict(sorted(counts.items()))}


def run_prototype_selftests(env_dir: Path) -> dict:
    script = ROOT / "tools" / "run_prototype_selftests.ps1"
    proc = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                          capture_output=True, text=True)
    write(env_dir / "prototype-selftests.txt", proc.stdout)
    m = re.search(r"(\d+)/(\d+) passed", proc.stdout)
    sha = re.search(r"engine file sha256: ([0-9a-f]{64})", proc.stdout)
    return {"passed": int(m[1]) if m else None, "total": int(m[2]) if m else None, "engine_sha256": sha[1] if sha else None}


def cross_implementation(tests: dict, prototype: dict) -> dict:
    """EV-X1: Python versus the JavaScript prototype, on the features both can represent."""
    golden = json.loads((ROOT / "tests" / "golden" / "policy_equivalence.json").read_text(encoding="utf-8"))
    eq = {k: v for k, v in tests["outcomes"].items() if "test_policy_equivalence" in k}
    parity = {k: v for k, v in tests["outcomes"].items() if "test_validation_parity" in k}
    supported = [s["name"] for s in golden["scenarios"] if s["supported"]]
    same = [n for n in supported if eq.get(f"tests.test_policy_equivalence::test_same_admission_decisions_as_the_prototype[{n}]") == "passed"]
    tie = [n for n in supported if eq.get(f"tests.test_policy_equivalence::test_same_admission_decisions_as_the_prototype[{n}]") == "xfailed"]
    return {
        "validation_parity_cases": Counter(parity.values()), "admission_scenarios_compared": len(supported),
        "identical_admission_decisions": same, "differ_only_by_equal_age_tie_break": tie,
        "tie_break_substitution_diagnostics": {k.split("[")[-1].rstrip("]"): v for k, v in eq.items()
                                               if "only_difference_is_the_equal_age" in k},
        "prototype_rules_refused_not_approximated": [s["name"] for s in golden["scenarios"] if not s["supported"]],
        "prototype_selftests": prototype,
        "not_representable_in_prototype": ["grades and grade-specific bins", "waiting areas and blocking",
                                           "scheduled outages", "stock events and reconciliation",
                                           "concurrent feeds on one segment", "commodity-pair changeover matrix",
                                           "continuous hopper drain (prototype: stepwise)"],
        "accepted": len(same) == 8 and len(tie) == 2 and prototype.get("passed") == prototype.get("total"),
    }


def reproduction(records: dict[str, dict]) -> dict:
    """EV-R1: selected runs repeated in fresh interpreters with different hash seeds must give identical results."""
    picks = [r for r in records.values() if r["settings"]["seed_index"] == 0 and (
        (r["settings"]["exp"] == "EV-C1" and r["settings"]["policy"] == "M-FF" and r["settings"]["demand"] == 1.0)
        or (r["settings"]["exp"] in ("EV-C2", "EV-P1") and r["settings"]["site"] == "C"))]
    checks = []
    for rec in picks:
        for hashseed in ("0", "12345"):
            env = {**os.environ, "PYTHONHASHSEED": hashseed, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)])}
            proc = subprocess.run([sys.executable, str(ROOT / "tools" / "evidence_run.py"), "digest", json.dumps(rec["settings"])],
                                  capture_output=True, text=True, env=env, cwd=ROOT)
            checks.append({"cell": rec["cell"], "PYTHONHASHSEED": hashseed, "expected": rec["run_sha256"],
                           "got": proc.stdout.strip(), "identical": proc.stdout.strip() == rec["run_sha256"]})
    return {"checks": checks, "identical": sum(c["identical"] for c in checks), "total": len(checks),
            "accepted": bool(checks) and all(c["identical"] for c in checks)}


def environment(durations: dict) -> dict:
    def ver(pkg):
        try:
            return metadata.version(pkg)
        except metadata.PackageNotFoundError:
            return None
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa: E731
    return {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "platform": platform.platform(),
            "python": sys.version, "implementation": platform.python_implementation(),
            "packages": {p: ver(p) for p in ("pydantic", "pydantic_core", "pytest")},
            "git_commit": git("rev-parse", "HEAD"), "git_dirty_files": git("status", "--porcelain").splitlines(),
            "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED"), "cpu_count": os.cpu_count(),
            "durations_s": durations, "command": " ".join(sys.argv)}


# ---------------------------------------------------------------- build
def build(out: Path, with_tests: bool = True, quick: bool = False, log=print) -> dict:
    t_all = time.time()
    durations = {}
    if out.exists():
        for p in sorted(out.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
    env_dir = out / "environment"
    files: dict[str, str] = {}

    def save(rel: str, text: str, gz: bool = False):
        path = out / rel
        if gz:
            write_gz(path, text)
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            write(path, text)
            files[rel] = sha_text(text)

    # configurations and overlays, as used
    for f in [*SITES.values(), "index.json"]:
        save(f"configs/{f}", (CONFIGS / f).read_text(encoding="utf-8").replace("\r\n", "\n"))
    for p in sorted(OVERLAYS.glob("*.json")):
        save(f"overlays/{p.name}", p.read_text(encoding="utf-8").replace("\r\n", "\n"))

    # structure
    rows = {k: structure(load_site_config(json.loads((CONFIGS / f).read_text(encoding="utf-8")))) for k, f in SITES.items()}
    save("structure/structure.json", canonical(rows))
    save("structure/structure.md", "# Structural comparison (generated)\n\n" + markdown(rows))

    results: dict[str, dict] = {}
    all_records: dict[str, dict] = {}
    for exp, spec in plan().items():
        t0 = time.time()
        cells = spec["cells"][:4] if quick else spec["cells"]
        recs, audits = [], []
        for cell in cells:
            record, audit, trace = run_cell(cell)
            recs.append(record)
            audits.append(audit)
            all_records[record["cell"]] = record
            if cell["seed_index"] == 0:
                save(f"experiments/{exp}/traces/{record['cell'].split('/', 1)[1].replace('/', '__')}.jsonl.gz", trace, gz=True)
        extra = {"alt_counts": alt_route_counts(cells)} if exp == "EV-F2" else {}
        evaluation = evaluate(exp, recs, extra)
        save(f"experiments/{exp}/runs.json", canonical(recs))
        save(f"experiments/{exp}/audit.json", canonical(audits))
        save(f"experiments/{exp}/evaluation.json", canonical({"claim": spec["claim"], **evaluation}))
        results[exp] = {"claim": spec["claim"], **evaluation}
        durations[exp] = round(time.time() - t0, 1)
        log(f"{exp}: {len(recs)} runs, accepted={evaluation['accepted']} ({durations[exp]} s)")

    graded = [r for r in all_records.values() if r["settings"]["site"] in ("C", "C-trap")]
    results["EV-S1"] = {"claim": "Grain segregation holds (graded Site C and trap variant)", "runs": len(graded),
                        "audit_problems_total": sum(r["physical"]["audit_problems"] for r in graded),
                        "accepted": bool(graded) and all(r["physical"]["audit_problems"] == 0 for r in graded)}
    save("experiments/EV-S1/evaluation.json", canonical(results["EV-S1"]))
    t0 = time.time()
    results["EV-C3"] = {"claim": "The independent audit detects corrupted records", **corruption_sensitivity()}
    save("experiments/EV-C3/evaluation.json", canonical(results["EV-C3"]))
    results["EV-F1"] = {"claim": "Every evidence configuration passes the validators", **feasibility_checks()}
    save("experiments/EV-F1/evaluation.json", canonical(results["EV-F1"]))
    results["EV-T2"] = {"claim": "No site-specific constants in the engine", **site_constant_scan()}
    save("experiments/EV-T2/evaluation.json", canonical(results["EV-T2"]))
    durations["checks"] = round(time.time() - t0, 1)

    if with_tests:
        t0 = time.time()
        tests = run_pytest(env_dir)
        save("tests/test_outcomes.json", canonical(tests))
        prototype = run_prototype_selftests(env_dir)
        save("tests/prototype_selftests.json", canonical(prototype))
        results["EV-X1"] = {"claim": "Same admission decisions as the JavaScript prototype on the common subset",
                            **cross_implementation(tests, prototype)}
        save("experiments/EV-X1/evaluation.json", canonical(results["EV-X1"]))
        durations["tests"] = round(time.time() - t0, 1)
        t0 = time.time()
        results["EV-R1"] = {"claim": "Identical results in fresh interpreters with different hash seeds", **reproduction(all_records)}
        save("experiments/EV-R1/evaluation.json", canonical(results["EV-R1"]))
        durations["reproduction"] = round(time.time() - t0, 1)

    results["EV-T1"] = {"claim": "Transferability: one unchanged engine runs every configuration",
                        "engine_source_sha256": engine_source_sha(),
                        "configs_run": sorted({r["settings"]["site"] for r in all_records.values()}),
                        "runs_total": len(all_records),
                        "accepted": results["EV-F1"]["accepted"] and results["EV-T2"]["accepted"]
                        and all(results[e]["physical_invariants_hold"] for e in plan())}
    save("experiments/EV-T1/evaluation.json", canonical(results["EV-T1"]))

    from .summary import summary_markdown
    save("EVIDENCE_SUMMARY.md", summary_markdown(results, rows))
    manifest = {
        "package": PACKAGE_ID, "engine_version": VERSION, "engine_source_sha256": engine_source_sha(),
        "prototype_engine_sha256": hashlib.sha256((ROOT / "reference/prototype_js/silo_engine_v0.2.0.js").read_bytes()).hexdigest(),
        "base_seed": BASE_SEED, "replication_seed_rule": "derived_seed(base_seed, 'replication', i)",
        "policy_mappings": MAPPINGS,
        "policy_mapping_detail": {k: describe(policy_for(k, 0)) for k in MAPPINGS},
        "configurations": {k: {"file": f"configs/{f}", "config_hash": rows[k]["config_hash"]} for k, f in SITES.items()},
        "experiments": {e: {"claim": s["claim"], "cells": len(s["cells"])} for e, s in plan().items()},
        "deterministic_files": dict(sorted(files.items())),
        "excluded_from_reproduction": ["environment/"],
        "statement": "Software verification outputs on synthetic configurations; not observations of a real silo.",
        "quick": quick,
    }
    write(out / "manifest.json", canonical(manifest))
    durations["total"] = round(time.time() - t_all, 1)
    write(env_dir / "environment.json", canonical(environment(durations)))
    return results


def check(package: Path, log=print) -> dict:
    """Rebuild into a temporary folder and compare every deterministic file's sha256 with the stored manifest."""
    import tempfile
    stored = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        fresh_dir = Path(tmp) / "pkg"
        build(fresh_dir, with_tests=True, quick=stored.get("quick", False), log=log)
        fresh = json.loads((fresh_dir / "manifest.json").read_text(encoding="utf-8"))
    a, b = stored["deterministic_files"], fresh["deterministic_files"]
    differing = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    same_manifest = {k: v for k, v in stored.items() if k != "deterministic_files"} == \
                    {k: v for k, v in fresh.items() if k != "deterministic_files"}
    return {"files_compared": len(set(a) | set(b)), "differing": differing, "manifest_settings_identical": same_manifest,
            "identical": not differing and same_manifest}
