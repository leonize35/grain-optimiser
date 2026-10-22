"""Build the developer scenario viewer: run an illustrative demo day through the engine and write an HTML page.

Usage (from the project root):
    .venv\\Scripts\\python.exe tools\\scenario_viewer\\build_viewer.py

The site, trucks and times below are ILLUSTRATIVE (not customer data). The same day runs twice: once with
unlimited waiting space in the hopper yard, once with the yard limited to one truck, to show blocking.
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from silo_engine import VERSION  # noqa: E402
from silo_engine.config import config_hash, load_site_config  # noqa: E402
from silo_engine.inputs.scripted import load_arrival_script  # noqa: E402
from silo_engine.sim.service_times import FixedServiceTimes  # noqa: E402
from silo_engine.sim.time import MS_PER_MINUTE, format_clock  # noqa: E402
from silo_engine.sim.truck_flow import TruckFlowModel  # noqa: E402

SITE = {
    "id": "demo", "name": "Demo silo (illustrative)", "version": 1, "hours": {"open": 7, "close": 18},
    "commodities": [{"id": "YM", "name": "Yellow maize", "grades": ["1", "2"]},
                    {"id": "WM", "name": "White maize"}],
    "equipment": [
        {"id": "S1", "type": "sampler", "name": "Sampling point", "cap": 1, "time": [2, 2, 2]},
        {"id": "G1", "type": "grader", "name": "Grading lab", "cap": 2, "time": [4, 4, 4]},
        {"id": "WB1", "type": "weighbridge", "name": "Weighbridge", "cap": 1, "time": [2, 2, 2]},
        {"id": "H1", "type": "hopper", "name": "Hopper 1", "capT": 60, "rate": 400, "tip": [6, 6, 6],
         "commodities": ["YM", "WM"]},
        {"id": "H2", "type": "hopper", "name": "Hopper 2", "capT": 60, "rate": 400, "tip": [6, 6, 6],
         "commodities": ["YM"]},
        {"id": "C1", "type": "conveyor", "name": "Bottom conveyor", "rate": 300, "max_concurrent_feeds": 2},
        {"id": "E1", "type": "elevator", "name": "Elevator", "rate": 200, "max_concurrent_feeds": 2},
        {"id": "B1", "type": "bin", "name": "Bin 1", "capT": 3000, "commodities": ["YM"],
         "accepts": [{"commodity": "YM", "grades": ["1"]}]},
        {"id": "B2", "type": "bin", "name": "Bin 2", "capT": 3000, "commodities": ["YM"],
         "accepts": [{"commodity": "YM", "grades": ["2"]}]},
        {"id": "B3", "type": "bin", "name": "Bin 3", "capT": 3000, "commodities": ["WM"]},
    ],
    "edges": [["H1", "C1"], ["H2", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"], ["E1", "B3"]],
    "sequences": {"unload": ["sample", "grade", "weigh_in", "tip", "weigh_out"]},
    "demand": {},
    "changeovers": {"rules": [{"from": "YM", "to": "WM", "minutes": 8}, {"from": "WM", "to": "YM", "minutes": 5}]},
    "truck_areas": [{"id": "gate", "name": "Road queue", "capacity": None},
                    {"id": "lab", "name": "Lab waiting bay", "capacity": None},
                    {"id": "yard", "name": "Hopper yard", "capacity": None}],
    "truck_paths": {"unload": ["gate", "sample", "lab", "grade", "weigh_in", "yard", "tip", "weigh_out"]},
    "deadlock_prevention": "reserve_next_space",
}

TRUCKS = [  # id, arrival, commodity, grade, tonnes
    ("T01", "07:00", "YM", "1", 32), ("T02", "07:03", "YM", "1", 30), ("T03", "07:06", "WM", None, 31),
    ("T04", "07:08", "YM", "2", 28), ("T05", "07:12", "YM", "1", 33), ("T06", "07:15", "WM", None, 30),
    ("T07", "07:18", "YM", "1", 29), ("T08", "07:22", "YM", "2", 34), ("T09", "07:25", "YM", "1", 31),
    ("T10", "07:30", "WM", None, 30), ("T11", "07:34", "YM", "1", 32), ("T12", "07:38", "YM", "2", 30),
]
TIMES = FixedServiceTimes({"sample": 2, "grade": 4, "weigh_in": 2, "tip": 6, "weigh_out": 2})
STATION_NAMES = {e["id"]: e["name"] for e in SITE["equipment"]}
COMMODITY_NAMES = {c["id"]: c["name"] for c in SITE["commodities"]}


def scenario(key, label, note, yard_capacity):
    raw = copy.deepcopy(SITE)
    next(a for a in raw["truck_areas"] if a["id"] == "yard")["capacity"] = yard_capacity
    site = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": tid, "activity": "unload", "arrive": at, "commodity": c, "tonnes": t, **({"grade": g} if g else {})}
        for tid, at, c, g, t in TRUCKS]})
    result = TruckFlowModel(site, script, TIMES, policy="feasible_first").run()
    mins = lambda ms: None if ms is None else ms / MS_PER_MINUTE  # noqa: E731

    trucks = []
    for rec in result.records:
        src = next(t for t in script if t.id == rec.truck_id)
        segments = []
        for s in rec.steps:
            if s.step == "grade":
                segments.append({"kind": "grade", "step": "grade", "start": mins(s.entered), "end": mins(s.finished)})
                continue
            if s.started is None:
                segments.append({"kind": "wait", "step": s.step, "start": mins(s.entered), "end": None})
                continue
            if s.started > s.entered:
                segments.append({"kind": "wait", "step": s.step, "start": mins(s.entered), "end": mins(s.started)})
            station = s.unit.split("#")[0] if s.unit else ""
            segments.append({"kind": "service", "step": s.step, "start": mins(s.started), "end": mins(s.finished),
                             "where": STATION_NAMES.get(station, station)})
            if s.left is not None and s.finished is not None and s.left > s.finished:
                segments.append({"kind": "blocked", "step": s.step, "start": mins(s.finished), "end": mins(s.left),
                                 "where": STATION_NAMES.get(station, station)})
        trucks.append({"id": rec.truck_id, "commodity": COMMODITY_NAMES[src.commodity], "grade": src.grade,
                       "tonnes": src.kg / 1000, "arrived": mins(rec.arrived), "departed": mins(rec.departed),
                       "segments": segments})

    transfers = [{"pit": STATION_NAMES[x.pit], "bin": STATION_NAMES[x.bin], "truck": x.truck_id, "tonnes": x.kg / 1000,
                  "reserved": mins(x.started), "flow": mins(x.flow_started), "finished": mins(x.finished),
                  "changeover": max(x.changeover_segments.values(), default=0) / MS_PER_MINUTE}
                 for x in result.transfers]
    done = [t for t in trucks if t["departed"] is not None]
    turnaround = [t["departed"] - t["arrived"] for t in done]
    blocked_wb = sum(s["end"] - s["start"] for t in trucks for s in t["segments"]
                     if s["kind"] == "blocked" and s["step"].startswith("weigh"))
    def waits(step):
        return [s["end"] - s["start"] for t in trucks for s in t["segments"]
                if s["kind"] == "wait" and s["step"] == step and s["end"] is not None] or [0]
    tip_wait, weigh_wait = waits("tip"), waits("weigh_in")
    bins = []
    for e in SITE["equipment"]:
        if e["type"] == "bin":
            kg, ident = result.bins[e["id"]]
            grade = f" grade {ident.grade}" if ident and ident.grade != "*" else ""
            bins.append({"name": e["name"], "tonnes": kg / 1000, "capacity": e["capT"],
                         "holds": (COMMODITY_NAMES[ident.commodity] + grade) if ident else "empty"})
    return {
        "key": key, "label": label, "note": note,
        "trucks": trucks, "transfers": transfers, "bins": bins,
        "kpi": {"mean_turnaround": sum(turnaround) / len(turnaround), "max_turnaround": max(turnaround),
                "last_departure": format_clock(max(r.departed for r in result.records if r.departed is not None)),
                "completed": len(done), "unfinished": len(result.unfinished),
                "weighbridge_blocked": blocked_wb, "mean_tip_wait": sum(tip_wait) / len(tip_wait),
                "mean_weigh_wait": sum(weigh_wait) / len(weigh_wait),
                "changeovers": sum(1 for x in transfers if x["changeover"] > 0),
                "yard_peak": result.area_peak.get("yard", 0)},
        "checks": {"material_balance_kg": result.material_balance_kg, "violations": len(result.violations),
                   "stall": None if result.stall is None else format_clock(result.stall.time)},
        "assumptions": result.assumptions,
        "config_hash": config_hash(site)[:12],
    }


def main() -> None:
    data = {
        "engine": VERSION,
        "scenarios": [
            scenario("open", "Yard unlimited", "Trucks that have weighed in can always wait in the hopper yard.", None),
            scenario("tight", "Yard holds 1", "Only one truck fits between the weighbridge and the hoppers. A truck "
                     "may only weigh in when a yard place is reserved for it.", 1),
        ],
    }
    here = Path(__file__).parent
    page = (here / "template.html").read_text(encoding="utf-8").replace("/*DATA*/null", json.dumps(data))
    out = here / "scenario_viewer.html"
    out.write_text(page, encoding="utf-8")
    for s in data["scenarios"]:
        print(s["label"], s["kpi"], s["checks"])
    print("written", out)


if __name__ == "__main__":
    main()
