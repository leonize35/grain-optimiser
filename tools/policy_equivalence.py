"""Capture the prototype's admission decisions for the policy-equivalence scenarios (docs/QUEUE_POLICY_DESIGN.md §9).

Writes tools/policy_equivalence/scenarios.js, runs the UNMODIFIED prototype engine on every scenario in headless
Microsoft Edge (tools/policy_equivalence/run.html), and stores the scenarios with the prototype's trucks and trace in
tests/golden/policy_equivalence.json. tests/test_policy_equivalence.py then runs the Python engine on the same
trucks, equipment states and (translated) policies and compares the admission decisions.

Usage:  python tools/policy_equivalence.py
"""
import copy
import hashlib
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "reference" / "prototype_js" / "silo_engine_v0.2.0.js"
PAGE = ROOT / "tools" / "policy_equivalence" / "run.html"
GOLDEN = ROOT / "tests" / "golden" / "policy_equivalence.json"

ZEROS = [0] * 24  # no generated arrivals: only the opening backlog


def demand(mix, daily=1):
    return {"daily": daily, "mix": mix, "payload": [30, 30, 30], "profile": ZEROS}


def hopper(hid, tip, commodities=("YM", "WM"), **extra):
    return {"id": hid, "type": "hopper", "name": f"Hopper {hid}", "capT": 1000, "rate": 400, "tip": [tip, tip, tip],
            "commodities": list(commodities), **extra}


def line(n):
    return [{"id": f"C{n}", "type": "conveyor", "name": f"Conveyor {n}", "rate": 300, "changeover": 0},
            {"id": f"E{n}", "type": "elevator", "name": f"Elevator {n}", "rate": 200, "changeover": 0}]


BINS = [{"id": "B1", "type": "bin", "name": "Bin 1", "capT": 5000, "commodities": ["YM"]},
        {"id": "B2", "type": "bin", "name": "Bin 2", "capT": 5000, "commodities": ["WM"]}]
COMMODITIES = [{"id": "YM", "name": "Yellow maize"}, {"id": "WM", "name": "White maize"}]


def site(name, equipment, edges, sequences, queue, demand_, policies):
    """Prototype-format configuration. Large hoppers (1000 t) keep pit space out of the comparison, because the
    prototype frees hopper space only when a transfer ends while the Python engine drains continuously (A3)."""
    return {"id": name, "name": name, "version": 1, "hours": {"open": 7, "close": 18, "overtime": 0},
            "commodities": COMMODITIES, "equipment": equipment, "edges": edges, "sequences": sequences,
            "demand": demand_, "policies": policies, "initial": {"queue": queue}}


MIX = {"YM": 0.5, "WM": 0.5}
LAYOUTS = {
    # One hopper; mixed commodities queue for it.
    "one_hopper": dict(
        equipment=[hopper("H1", 1)] + line(1) + BINS,
        edges=[["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"]],
        sequences={"unload": ["tip"]}, queue={"unload": 8}, demand_={"unload": demand(MIX)}),
    # Two independent lines; H2 takes yellow maize only; H1 tips slowly.
    "two_independent": dict(
        equipment=[hopper("H1", 10), hopper("H2", 1, ["YM"])] + line(1) + line(2) + BINS,
        edges=[["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"], ["H2", "C2"], ["C2", "E2"], ["E2", "B1"]],
        sequences={"unload": ["tip"]}, queue={"unload": 8}, demand_={"unload": demand(MIX)}),
    # Two hoppers share one conveyor and elevator; H2 opens with 20 t of white maize.
    "two_shared_opening_grain": dict(
        equipment=[hopper("H1", 1), hopper("H2", 2, level0=20, levelCommodity="WM")] + line(1) + BINS,
        edges=[["H1", "C1"], ["H2", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"]],
        sequences={"unload": ["tip"]}, queue={"unload": 8}, demand_={"unload": demand(MIX)}),
    # Two-lane weighbridge before and after tipping.
    "weighbridge": dict(
        equipment=[{"id": "WB1", "type": "weighbridge", "name": "Weighbridge", "cap": 2, "time": [2, 2, 2]},
                   hopper("H1", 3)] + line(1) + BINS,
        edges=[["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"]],
        sequences={"unload": ["weigh_in", "tip", "weigh_out"]}, queue={"unload": 8}, demand_={"unload": demand(MIX)}),
    # Loading and intake share elevator E1; Bin 1 opens with 100 t of yellow maize.
    "loading_shared_elevator": dict(
        equipment=[hopper("H1", 1, ["YM"])] + line(1) + [
            {"id": "B1", "type": "bin", "name": "Bin 1", "capT": 5000, "commodities": ["YM"], "inv": 100, "invCommodity": "YM"},
            {"id": "R1", "type": "conveyor", "name": "Reclaim", "rate": 300, "changeover": 0},
            {"id": "L1", "type": "loadpoint", "name": "Load-out", "rate": 250, "setup": [5, 5, 5]}],
        edges=[["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["B1", "R1"], ["R1", "E1"], ["E1", "L1"]],
        sequences={"unload": ["tip"], "load": ["load"]}, queue={"unload": 4, "load": 4},
        demand_={"unload": demand({"YM": 1}), "load": demand({"YM": 1})}),
}
SUPPORTED = [{"tip": "fifo", "weigh": "fifo", "transfer": "fifo"},
             {"tip": "feasible", "weigh": "fifo", "transfer": "fifo"}]
# Prototype rules without a Python equivalent: captured so the difference is on record, not compared.
UNSUPPORTED = [("one_hopper", {"tip": "batch", "weigh": "fifo", "transfer": "fifo"}),
               ("two_shared_opening_grain", {"tip": "feasible", "weigh": "fifo", "transfer": "batch"}),
               ("weighbridge", {"tip": "feasible", "weigh": "out_first", "transfer": "fifo"}),
               ("loading_shared_elevator", {"tip": "feasible", "weigh": "fifo", "transfer": "load_first"})]
SEED = 11


def scenarios() -> list[dict]:
    out = []
    for layout, spec in LAYOUTS.items():
        for pol in SUPPORTED:
            out.append({"name": f"{layout}/tip={pol['tip']}", "layout": layout, "seed": SEED, "supported": True,
                        "config": site(layout, policies=pol, **copy.deepcopy(spec))})
    for layout, pol in UNSUPPORTED:
        tag = ",".join(f"{k}={v}" for k, v in pol.items() if v not in ("fifo",) or k == "tip")
        out.append({"name": f"{layout}/{tag}", "layout": layout, "seed": SEED, "supported": False,
                    "config": site(layout, policies=pol, **copy.deepcopy(LAYOUTS[layout]))})
    return out


def edge_path() -> str:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    sys.exit("Microsoft Edge not found.")


def main() -> None:
    scs = scenarios()
    (PAGE.parent / "scenarios.js").write_text(
        "// Generated by tools/policy_equivalence.py. Do not edit.\nconst SCENARIOS = " + json.dumps(scs, indent=1) + ";\n",
        encoding="utf-8")
    profile = Path(os.environ.get("TEMP", ".")) / "silo-policy-equivalence-edge-profile"
    # Edge's --dump-dom output reaches a PowerShell pipeline but not a plain subprocess pipe on this machine
    # (the same route as tools/run_prototype_selftests.ps1).
    command = (f"[Console]::OutputEncoding = [Text.Encoding]::UTF8; & '{edge_path()}' --headless=new --disable-gpu "
               f"--no-first-run --user-data-dir='{profile}' --virtual-time-budget=60000 --dump-dom '{PAGE.as_uri()}' "
               "2>$null | Out-String")
    dom = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                         capture_output=True, text=True, encoding="utf-8").stdout
    m = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    if not m or m.group(1) == "running":
        sys.exit("Could not read the prototype output.")
    captured = json.loads(html.unescape(m.group(1)))
    golden = {"engine_sha256": hashlib.sha256(ENGINE.read_bytes()).hexdigest(), "prototype_version": captured["version"],
              "scenarios": [{**s, "prototype": captured["scenarios"][s["name"]]} for s in scs]}
    GOLDEN.write_text(json.dumps(golden, indent=1), encoding="utf-8")
    for s in golden["scenarios"]:
        p = s["prototype"]
        print(f"{s['name']:55s} {'ERROR ' + p['error'] if 'error' in p else str(len(p['trace'])) + ' trace lines'}")
    print(f"wrote {GOLDEN}")


if __name__ == "__main__":
    main()
