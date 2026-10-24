"""Paper 2 extension: sampler access, physical queue blocking and sampler location (docs/SAMPLER_ACCESS_DESIGN.md §6).

  python tools/evidence_run.py build-sampling     write evidence/out/paper2-ext-sampling-v1
  python tools/evidence_run.py check-sampling     rebuild and compare deterministic files

A separately versioned package. The Paper 2 baseline (`paper2-v1`, commit 6345377) is referenced, never modified.
Synthetic configurations; software outputs, not observations of a real silo. Provisional assumptions O1-O11
(design document §8) apply.

Configurations: the grain systems of Site A and Site C, each with four truck-access layouts S1-S4 that change only
the layout (sampler location, single-file approach, holding space, declared bypass), never the number of sampling
units or weighbridge bays. Site A's weighbridge is given 2 bays in every layout so that a probe bay and a plain bay
exist (Site C keeps its three weighbridges; the probe is at WB1).
"""
import copy
import hashlib
import json
import math
import time
from collections import defaultdict
from pathlib import Path

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.config.rules_validation import validate_rules
from silo_engine.config.schema import config_hash
from silo_engine.experiments.runner import ci
from silo_engine.inputs.generated import generate_arrivals
from silo_engine.sim.random_streams import derived_seed
from silo_engine.sim.service_times import StochasticServiceTimes
from silo_engine.sim.time import MS_PER_MINUTE
from silo_engine.sim.truck_flow import TruckFlowModel

from .export import holm, t_two_sided_p
from .policies import describe, policy_for
from .runner import CONFIGS, ROOT, canonical, engine_source_sha, environment, sha_text, write, write_gz

PACKAGE_ID = "paper2-ext-sampling-v1"
BASE_SEED = 20261024
SITES = {"A": "site_a.json", "C": "site_c.json", "S": "site_s_controlled.json"}
LAYOUTS = ("S1", "S2", "S3", "S4")
SITE_LAYOUTS = {"A": LAYOUTS, "C": LAYOUTS, "S": LAYOUTS + ("S1-h0", "S1-h5")}  # S1-hN: holding capacity N (S1: 2)
SITE_TEXT = {"A": "Site A grain system (prototype demo), truck access varied",
             "C": "Site C grain system (synthetic), truck access varied",
             "S": "Site S controlled (synthetic): fast single-commodity grain handling, so downstream cannot confound"}
SHARES = (0.3, 0.7, 1.0)
SEEDS = range(20)
POLICY = "M-FF"
BASELINE = {"package": "paper2-v1", "commit": "6345377",
            "manifest": "evidence/out/paper2-v1/manifest.json"}
COMPARISONS = [("S1", "S2", "bypass, separate sampler"), ("S3", "S4", "bypass, sampler at weighbridge"),
               ("S1", "S3", "location, no bypass"), ("S2", "S4", "location, with bypass"),
               ("S1", "S1-h0", "holding: none vs 2"), ("S1", "S1-h5", "holding: 5 vs 2")]
ALLOWED_DIFFS = ("truck_areas", "truck_paths", "truck_bypasses", "id", "name", "sampler.located_at", "sampler.located_lanes")


def access_config(site: str, layout: str, share: float) -> dict:
    raw = json.loads((CONFIGS / SITES[site]).read_text(encoding="utf-8"))
    raw["id"] = f"{raw['id']}_access_{layout}"
    raw["name"] = f"{raw['name']} - truck access {layout} (synthetic)"
    sampler = next(e for e in raw["equipment"] if e["type"] == "sampler")
    weighbridges = [e for e in raw["equipment"] if e["type"] == "weighbridge"]
    if site == "A":
        weighbridges[0]["cap"] = 2  # a probe bay and a plain bay in every layout
    holding = 2
    if "-h" in layout:
        layout, holding = layout.split("-h")[0], int(layout.split("-h")[1])
    probe_wb = weighbridges[0]["id"]
    sampler["pass_through"] = [0.3, 0.5, 1.0]
    raw["sequences"]["unload"] = ["sample", "weigh_in", "grade", "tip", "weigh_out"]
    raw["demand"]["unload"]["sampling_share"] = share
    areas = [{"id": "gate", "name": "Gate", "capacity": None},
             {"id": "approach", "name": "Sampler approach", "capacity": None, "single_file": True},
             {"id": "holding", "name": "Holding space", "capacity": holding or 1},
             {"id": "yard", "name": "Yard", "capacity": None},
             {"id": "exit", "name": "Exit lane", "capacity": None}]
    tail = ["weigh_in", "yard", "grade", "tip", "exit", "weigh_out"]
    if layout in ("S1", "S2"):
        raw["truck_areas"] = areas if holding else [a for a in areas if a["id"] != "holding"]
        raw["truck_paths"] = {"unload": ["gate", "approach", "sample"] + (["holding"] if holding else []) + tail}
        if layout == "S2":
            raw["truck_bypasses"] = [{"activity": "unload", "from": "gate", "to": "weigh_in", "for": "not_sampled"}]
    else:
        sampler.update({"located_at": probe_wb, "located_lanes": [0]})
        raw["truck_areas"] = [a for a in areas if a["id"] != "holding"]
        raw["truck_paths"] = {"unload": ["gate", "approach", "sample"] + tail}
        if layout == "S4":
            raw["truck_bypasses"] = [{"activity": "unload", "from": "approach", "to": "weigh_in", "for": "not_sampled"}]
    return raw


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def run_cell(cell: dict, keep=False):
    raw = access_config(cell["site"], cell["layout"], cell["share"])
    site = load_site_config(copy.deepcopy(raw))
    seed = derived_seed(BASE_SEED, "replication", cell["seed_index"])
    trucks = generate_arrivals(site, seed, days=1, demand_factor=1.0)
    mapping = policy_for(POLICY, seed)
    model = TruckFlowModel(site, trucks, StochasticServiceTimes(site, seed), policy=mapping)
    r = model.run()
    audit = audit_flow(site, trucks, r)
    trace = "".join(json.dumps([e.time, e.priority, e.seq, e.label, e.cancelled]) + "\n" for e in r.trace)
    horizon = (site.hours.close + site.hours.overtime - site.hours.open) * 60  # minutes of service per day
    minutes = lambda a, b: None if a is None or b is None else (b - a) / MS_PER_MINUTE  # noqa: E731
    cls = defaultdict(lambda: defaultdict(list))
    weighbridge_ids = {e.id for e in site.equipment if e.type == "weighbridge"}
    sampler_busy = sampler_bay = wb_busy = wb_occupied = 0.0
    bays = sum(int(e.cap or 1) for e in site.equipment if e.type == "weighbridge")
    units = sum(int(e.cap or 1) for e in site.equipment if e.type == "sampler")
    for rec in r.records:
        steps = {s.step: s for s in rec.steps}
        for s in rec.steps:
            if s.step in ("sample", "pass") and s.started is not None:
                if s.step == "sample":
                    sampler_busy += minutes(s.started, s.finished) or 0
                if not site.equipment or not any(e.type == "sampler" and e.located_at for e in site.equipment):
                    sampler_bay += minutes(s.started, s.left if s.left is not None else s.finished) or 0
            if s.unit and s.unit.split("#")[0] in {e.id for e in site.equipment if e.type == "weighbridge"} and s.started is not None:
                wb_busy += minutes(s.started, s.finished) or 0
                wb_occupied += minutes(s.started, s.left if s.left is not None else s.finished) or 0
        if rec.activity != "unload":
            continue
        a = r.truck_access.get(rec.truck_id, {})
        c = cls["sampled" if a.get("requires_sampling") else "unsampled"]
        m = r.truck_metrics[rec.truck_id]
        c["trucks"].append(1)
        c["completed"].append(1 if rec.departed is not None else 0)
        c["turnaround_min"].append(minutes(rec.arrived, rec.departed))
        c["total_wait_min"].append(m.total_waiting_min)
        q = steps.get("sample") or steps.get("pass")
        w = steps.get("weigh_in")
        road = a.get("blocked_behind_ms", 0) / MS_PER_MINUTE  # behind another truck in the single-file approach
        # The approach request is the sampler step if the truck has one, otherwise weighing in (sampler at the bay, or
        # bypass); road blocking is subtracted from that request's waiting so that the parts do not overlap.
        separate_bay = q is not None and q.unit is not None and q.unit.split("#")[0] not in weighbridge_ids
        sq = minutes(q.entered, q.started) if q is not None and q.started is not None else None
        if sq is not None:
            sq = max(0.0, sq - road)
        hold = minutes(q.finished, q.left) if separate_bay and q.finished is not None and q.left is not None else 0.0
        ww = minutes(w.entered, w.started) if w is not None and w.started is not None else None
        if ww is not None and q is None:
            ww = max(0.0, ww - road)
        c["sampler_wait_min"].append(sq if q is not None else 0.0)
        c["weighbridge_wait_min"].append(ww)
        c["blocked_behind_min"].append(road)
        c["holding_block_min"].append(hold)
        tip = steps.get("tip")
        c["tip_wait_min"].append(minutes(tip.entered, tip.started) if tip is not None and tip.started is not None else None)
        c["pass_throughs"].append(a.get("pass_throughs", 0))
    per_class = {k: {"trucks": sum(v["trucks"]), "completed": sum(v["completed"]),
                     **{f"mean_{x}": _mean(v[x]) for x in ("turnaround_min", "total_wait_min", "sampler_wait_min",
                                                          "weighbridge_wait_min", "blocked_behind_min", "holding_block_min",
                                                          "tip_wait_min")},
                     "pass_throughs": sum(v["pass_throughs"])} for k, v in cls.items()}
    occ = r.area_occupancy
    record = {
        "cell": f"{cell['site']}/{cell['layout']}/share{cell['share']}/s{cell['seed_index']}", "settings": cell, "seed": seed,
        "config_hash": config_hash(site), "policy_mapping": describe(mapping),
        "physical": {"audit_problems": len(audit.problems), "material_balance_kg": r.material_balance_kg,
                     "engine_violations": len(r.violations)},
        "operational": {"stalled": r.stall is not None, "trucks": len(r.records),
                        "unload_completed": sum(1 for x in r.records if x.activity == "unload" and x.departed is not None),
                        "unload_unfinished": sum(1 for x in r.records if x.activity == "unload" and x.departed is None),
                        "unfinished_at_tip": sum(1 for u in r.unfinished if u.step == "tip"),
                        "received_t": r.received_kg / 1000},
        "by_class": per_class,
        "queues": {k: {"time_average": round(v["time_average"], 6), "peak": v["peak"]} for k, v in occ.items()},
        "utilisation": {"sampler_units_busy": sampler_busy / (units * horizon),
                        "sampler_bay_occupied": sampler_bay / (units * horizon),
                        "weighbridge_bays_busy": wb_busy / (bays * horizon),
                        "weighbridge_bays_occupied": wb_occupied / (bays * horizon)},
        "trace_sha256": sha_text(trace),
    }
    record["run_sha256"] = sha_text(canonical(record))
    out = (record, {"cell": record["cell"], "problems": audit.problems, "in_transit": audit.in_transit}, trace)
    return out + ((model, r) if keep else ())


METRICS = [  # (label, unit, extractor)
    ("Turnaround, sampled trucks", "min", lambda r: r["by_class"].get("sampled", {}).get("mean_turnaround_min")),
    ("Turnaround, unsampled trucks", "min", lambda r: r["by_class"].get("unsampled", {}).get("mean_turnaround_min")),
    ("Sampler waiting, sampled trucks", "min", lambda r: r["by_class"].get("sampled", {}).get("mean_sampler_wait_min")),
    ("Weighbridge waiting, sampled trucks", "min", lambda r: r["by_class"].get("sampled", {}).get("mean_weighbridge_wait_min")),
    ("Weighbridge waiting, unsampled trucks", "min", lambda r: r["by_class"].get("unsampled", {}).get("mean_weighbridge_wait_min")),
    ("Physically blocked behind another truck, unsampled", "min", lambda r: r["by_class"].get("unsampled", {}).get("mean_blocked_behind_min")),
    ("Physically blocked behind another truck, sampled", "min", lambda r: r["by_class"].get("sampled", {}).get("mean_blocked_behind_min")),
    ("Sampler queue (excl. road blocking), unsampled", "min", lambda r: r["by_class"].get("unsampled", {}).get("mean_sampler_wait_min")),
    ("Blocked in sampler bay by full holding, sampled", "min", lambda r: r["by_class"].get("sampled", {}).get("mean_holding_block_min")),
    ("Blocked in sampler bay by full holding, unsampled", "min", lambda r: r["by_class"].get("unsampled", {}).get("mean_holding_block_min")),
    ("Hopper waiting (tip), all unloading trucks", "min", lambda r: _mean([r["by_class"].get(k, {}).get("mean_tip_wait_min") for k in ("sampled", "unsampled")])),
    ("Unfinished at closing, waiting at a hopper", "trucks", lambda r: r["operational"]["unfinished_at_tip"]),
    ("Approach queue length (time-average)", "trucks", lambda r: r["queues"].get("approach", {}).get("time_average")),
    ("Completed unloading trucks", "trucks/day", lambda r: r["operational"]["unload_completed"]),
    ("Grain received", "t/day", lambda r: r["operational"]["received_t"]),
    ("Weighbridge bays busy", "fraction", lambda r: r["utilisation"]["weighbridge_bays_busy"]),
    ("Weighbridge bays occupied (incl. sampling at bay and blocking)", "fraction", lambda r: r["utilisation"]["weighbridge_bays_occupied"]),
]


def summarise(runs: list[dict]) -> tuple[list[dict], list[dict]]:
    idx = {(r["settings"]["site"], r["settings"]["layout"], r["settings"]["share"], r["settings"]["seed_index"]): r for r in runs}
    cells = []
    for site in SITES:
        for share in SHARES:
            for layout in SITE_LAYOUTS[site]:
                rs = [idx[(site, layout, share, i)] for i in SEEDS]
                for label, unit, fn in METRICS:
                    i = ci([fn(r) for r in rs])
                    cells.append({"site": site, "share": share, "layout": layout, "metric": label, "unit": unit, "n": i.n,
                                  "mean": i.mean, "sd": i.sd, "ci_low": i.low, "ci_high": i.high})
    comps = []
    for site in SITES:
        for share in SHARES:
            for a, b, what in COMPARISONS:
                if b not in SITE_LAYOUTS[site]:
                    continue
                for label, unit, fn in METRICS:
                    pairs = [(fn(idx[(site, a, share, i)]), fn(idx[(site, b, share, i)])) for i in SEEDS]
                    diffs = [y - x for x, y in pairs if x is not None and y is not None]
                    i = ci(diffs)
                    p = None
                    if i.n > 1 and i.sd:
                        p = t_two_sided_p(i.mean / (i.sd / math.sqrt(i.n)), i.n - 1)
                    comps.append({"site": site, "share": share, "comparison": f"{b} - {a}", "effect": what, "metric": label,
                                  "unit": unit, "n_pairs": i.n, "mean_difference": i.mean, "sd": i.sd, "ci_low": i.low,
                                  "ci_high": i.high, "p": p})
    for c, q in zip(comps, holm([c["p"] for c in comps])):
        c["p_holm"] = q
        if c["n_pairs"] == 0:
            c["support"] = "not applicable (no trucks of this class)"
        elif c["sd"] == 0:
            c["support"] = "no difference in any pair" if not c["mean_difference"] else "constant difference (SD 0)"
        elif q is not None and q < 0.05:
            c["support"] = "supported (Holm p < 0.05)"
        elif c["ci_low"] is not None and (c["ci_low"] > 0 or c["ci_high"] < 0):
            c["support"] = "nominal only (CI excludes 0; not after Holm)"
        else:
            c["support"] = "descriptive (CI includes 0)"
    return cells, comps


def build(out: Path, log=print) -> dict:
    t0 = time.time()
    if out.exists():
        for p in sorted(out.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
    files = {}

    def save(rel, text, gz=False):
        path = out / rel
        if gz:
            write_gz(path, text)
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            write(path, text)
            files[rel] = sha_text(text)

    hashes, diffs = {}, {}
    for site in SITES:
        base = access_config(site, "S1", 1.0)
        for layout in SITE_LAYOUTS[site]:
            raw = access_config(site, layout, 1.0)
            d = config_diff(base, raw)
            bad = [x for x in d if not x.startswith(ALLOWED_DIFFS)]
            assert not bad, (site, layout, bad)  # only layout fields may differ between scenarios
            diffs[f"{site}: S1 vs {layout}"] = d
            s = load_site_config(copy.deepcopy(raw))
            errors = [i.msg for i in validate_rules(s).errors]
            assert not errors, errors
            hashes[f"{site}/{layout}"] = config_hash(s)
            save(f"configs/{site}_{layout}.json", canonical(raw))
    save("layout_differences.json", canonical(diffs))
    save("configs/index.json", canonical({"note": "SYNTHETIC configurations; none describes a real silo.", **SITE_TEXT}))
    runs, audits = [], []
    for site in SITES:
        for layout in SITE_LAYOUTS[site]:
            for share in SHARES:
                for i in SEEDS:
                    cell = {"site": site, "layout": layout, "share": share, "seed_index": i}
                    rec, aud, trace = run_cell(cell)
                    runs.append(rec)
                    audits.append(aud)
                    if i == 0:
                        save(f"traces/{site}_{layout}_share{share}_s0.jsonl.gz", trace, gz=True)
                        save(f"audits/{site}_{layout}_share{share}_s0.json", canonical(aud))
        log(f"site {site}: {len(runs)} runs so far ({time.time() - t0:.0f} s)")
    cells, comps = summarise(runs)
    verification = {
        "runs": len(runs), "audit_problems_total": sum(r["physical"]["audit_problems"] for r in runs),
        "max_abs_balance_kg": max(abs(r["physical"]["material_balance_kg"]) for r in runs),
        "engine_violations": sum(r["physical"]["engine_violations"] for r in runs),
        "stalled_runs": sum(r["operational"]["stalled"] for r in runs),
        "accepted": all(r["physical"]["audit_problems"] == 0 and r["physical"]["material_balance_kg"] == 0
                        and r["physical"]["engine_violations"] == 0 for r in runs)}
    save("runs.json", canonical(runs))
    save("audit.json", canonical(audits))
    save("verification.json", canonical(verification))
    save("summary_cells.json", canonical(cells))
    save("paired_comparisons.json", canonical(comps))
    baseline_sha = hashlib.sha256((ROOT / BASELINE["manifest"]).read_bytes()).hexdigest()
    manifest = {"package": PACKAGE_ID, "extends_baseline": {**BASELINE, "manifest_sha256": baseline_sha},
                "engine_source_sha256": engine_source_sha(), "base_seed": BASE_SEED,
                "replication_seed_rule": "derived_seed(base_seed, 'replication', i)", "seeds": list(SEEDS),
                "sites": SITES, "site_text": SITE_TEXT, "layouts": {k: list(v) for k, v in SITE_LAYOUTS.items()},
                "sampling_shares": list(SHARES), "policy_mapping": POLICY, "allowed_layout_differences": list(ALLOWED_DIFFS),
                "policy_mapping_detail": describe(policy_for(POLICY, 0)), "config_hashes": hashes,
                "provisional_assumptions": "docs/SAMPLER_ACCESS_DESIGN.md section 8 (O1-O11)",
                "deterministic_files": dict(sorted(files.items())), "excluded_from_reproduction": ["environment/"],
                "statement": "Software outputs on synthetic configurations; not observations of a real silo."}
    write(out / "manifest.json", canonical(manifest))
    write(out / "environment" / "environment.json", canonical(environment({"total": round(time.time() - t0, 1)})))
    return verification


def check(out: Path, log=print) -> dict:
    import tempfile
    stored = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        fresh_dir = Path(tmp) / "pkg"
        build(fresh_dir, log=log)
        fresh = json.loads((fresh_dir / "manifest.json").read_text(encoding="utf-8"))
    a, b = stored["deterministic_files"], fresh["deterministic_files"]
    differing = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    same = {k: v for k, v in stored.items() if k != "deterministic_files"} == {k: v for k, v in fresh.items() if k != "deterministic_files"}
    return {"files_compared": len(set(a) | set(b)), "differing": differing, "manifest_settings_identical": same,
            "identical": not differing and same}


def config_diff(a, b, prefix=""):
    """Paths whose values differ between two configurations (equipment matched by id; the sampler named 'sampler')."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += config_diff(a.get(k), b.get(k), f"{prefix}.{k}" if prefix else k)
        return out
    if isinstance(a, list) and isinstance(b, list) and prefix == "equipment":
        ia, ib = {e["id"]: e for e in a}, {e["id"]: e for e in b}
        for k in sorted(set(ia) | set(ib)):
            ea, eb = ia.get(k), ib.get(k)
            name = "sampler" if (ea or eb or {}).get("type") == "sampler" else f"equipment.{k}"
            out += config_diff(ea, eb, name)
        return out
    return [] if a == b else [prefix]
