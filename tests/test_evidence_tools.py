"""Paper 2 evidence tools (tools/evidence): structural comparison, adversarial policies, runner determinism,
acceptance logic, and the site-constant scan. The full package is built by `python tools/evidence_run.py build`."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from silo_engine.config import load_site_config  # noqa: E402
from tools.evidence import runner  # noqa: E402
from tools.evidence.structure import structure  # noqa: E402


def site(name):
    return load_site_config(json.loads((ROOT / "evidence" / "configs" / name).read_text(encoding="utf-8")))


def test_engine_code_has_no_site_specific_constants():
    scan = runner.site_constant_scan()
    assert scan["equipment_ids_checked"] > 40 and scan["hits"] == []


def test_structural_comparison_of_the_evidence_sites():
    a, b, c, trap = (structure(site(f)) for f in ("site_a.json", "site_b.json", "site_c.json", "site_c_segregation_trap.json"))
    assert (a["intake_systems"], b["intake_systems"], c["intake_systems"]) == (1, 2, 1)
    assert (c["interconnects"], c["intake_systems_without_interconnects"]) == (["X1"], 2)
    assert [len(x["pairs_with_alternative_intermediate_routes"]) for x in (a, b, c)] == [0, 0, 4]
    assert (a["shared_intake_and_loadout"], b["shared_intake_and_loadout"], c["shared_intake_and_loadout"]) == (["E1"], [], ["EN2"])
    assert c["multi_feed_equipment"] == ["EN1"] and c["graded_commodities"] == ["YM"]
    assert trap["grain_compatibility"]["YM:1"]["reachable_bins_per_hopper"]["HS1"] == ["BS1"]
    assert c["config_hash"].startswith("56712a9a8716") and trap["config_hash"].startswith("37d5d3dd70dc")


def test_evidence_configurations_keep_their_hashes_and_labels():
    index = json.loads((ROOT / "evidence" / "configs" / "index.json").read_text(encoding="utf-8"))
    assert all(c["synthetic"] for c in index["configurations"]) and "SYNTHETIC" in index["note"]
    assert structure(site("site_a.json"))["config_hash"].startswith("e214e4680b9a")
    assert structure(site("site_b.json"))["config_hash"].startswith("f8a22f2f35f4")


def test_runs_are_deterministic_including_adversarial_policies():
    cell = {"exp": "T", "site": "A", "overlays": [], "policy": "ADV-RAND", "seed_index": 0, "demand": 1.0, "days": 1}
    first, audit, trace = runner.run_cell(cell)
    second, _, trace2 = runner.run_cell(cell)
    assert first["run_sha256"] == second["run_sha256"] and trace == trace2
    assert audit["problems"] == [] and first["physical"]["material_balance_kg"] == 0
    assert "time" not in json.dumps(first["settings"])  # no wall-clock data in deterministic outputs


def test_compressed_traces_are_byte_identical(tmp_path):
    runner.write_gz(tmp_path / "a.gz", "line\n")
    runner.write_gz(tmp_path / "b.gz", "line\n")
    assert (tmp_path / "a.gz").read_bytes() == (tmp_path / "b.gz").read_bytes()


def _run(stalled, problems=0):
    return {"physical": {"audit_problems": problems, "material_balance_kg": 0, "engine_violations": 0, "unexplained_kg": 0},
            "operational": {"stalled": stalled, "unfinished": 3 if stalled else 0, "trucks": 10, "completed": 7,
                            "stall_reason_codes": {"BIN_INCOMPATIBLE": 1} if stalled else {}},
            "settings": {"site": "C", "policy": "ADV-RHOL", "seed_index": 0}}


def test_an_operational_stall_is_reported_not_counted_as_a_verification_failure():
    ok = runner.evaluate("EV-P1", [_run(False), _run(True)], {})
    assert ok["accepted"] and ok["stalled_runs"] == 1 and ok["unfinished_trucks_total"] == 3
    bad = runner.evaluate("EV-P1", [_run(False), _run(True, problems=1)], {})
    assert not bad["accepted"]
