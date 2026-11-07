"""Endpoints behind the silo-builder app (UI slice 9a): the equipment catalogue (types, fields, allowed connections),
synthetic example sites, and the static app itself. The app reads these instead of carrying engine rules."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from silo_engine.api import create_app  # noqa: E402
from silo_engine.config import load_site_config  # noqa: E402
from silo_engine.config.catalogue import catalogue  # noqa: E402
from silo_engine.config.schema import Equipment  # noqa: E402
from silo_engine.config.validation import ALLOWED_CONNECTIONS, EQUIPMENT_LABEL  # noqa: E402


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path))


def test_catalogue_lists_every_equipment_type_with_the_engine_connection_rules(client):
    meta = client.get("/meta").json()
    types = meta["equipment_types"]
    assert set(types) == set(EQUIPMENT_LABEL)
    for t, info in types.items():
        assert info["label"] == EQUIPMENT_LABEL[t]
        assert info["connects_to"] == list(ALLOWED_CONNECTIONS[t])
    hopper = {f["name"]: f for f in types["hopper"]["fields"]}
    assert all(hopper[k]["required"] for k in ("capT", "rate", "tip"))
    assert hopper["rate"]["unit"] == "t/h"
    assert {a["id"] for a in meta["activities"]} == {"unload", "load", "weigh"}


def test_every_catalogue_field_is_a_real_configuration_field():
    names = {f.alias or n for n, f in Equipment.model_fields.items()}
    for t, info in catalogue()["equipment_types"].items():
        for f in info["fields"]:
            assert f["name"] in names, (t, f["name"])


def test_examples_are_labelled_synthetic_and_load(client):
    ex = client.get("/examples").json()
    files = {e["file"] for e in ex}
    assert {"site_a.json", "site_b.json", "site_c.json"} <= files
    assert all("synthetic" in e["note"].lower() for e in ex)
    load_site_config(client.get("/examples/site_a.json").json())
    assert client.get("/examples/../pyproject.toml").status_code == 404
    assert client.get("/examples/nope.json").status_code == 404


def test_the_app_is_served(client):
    r = client.get("/app/")
    assert r.status_code == 200 and "Silo Optimiser" in r.text
    assert client.get("/", follow_redirects=False).headers["location"] == "/app/"
    assert client.get("/app/app.js").status_code == 200


def test_catalogue_describes_truck_processes_from_the_engine_vocabulary(client):
    """Slice 9b: steps, release conditions, steps that hold a place, and deadlock options come from the engine."""
    import typing

    from silo_engine.config.rules_validation import CONDITIONS, PLACE_STEPS
    from silo_engine.config.schema import SiteConfig, TruckStep
    meta = client.get("/meta").json()
    assert [s["id"] for s in meta["truck_steps"]] == list(typing.get_args(TruckStep))
    assert all(s["label"] for s in meta["truck_steps"])
    assert {c["id"] for c in meta["release_conditions"]} == set(CONDITIONS) - {"service_done"}
    assert meta["place_steps"] == list(PLACE_STEPS)
    steps = meta["activity_steps"]
    assert "tip" in steps["unload"] and "tip" not in steps["load"] and "load" in steps["load"]
    assert "load" not in steps["unload"] and "tip" not in steps["weigh"] and "load" not in steps["weigh"]
    deadlock = typing.get_args(SiteConfig.model_fields["deadlock_prevention"].annotation)
    assert [d["id"] for d in meta["deadlock_prevention"]] == list(deadlock)


def test_catalogue_describes_labour_rules_and_demand_from_the_engine(client):
    """Slice 9c: the vocabulary of the labour, operating-rules and demand screens comes from the engine's literals."""
    import typing

    from silo_engine.config.schema import EndOfDay, LabourRequirement, QueueGroupName, QueuePolicyName, UnloadingLabour
    meta = client.get("/meta").json()
    lit = lambda model, name: list(typing.get_args(model.model_fields[name].annotation))  # noqa: E731
    assert [g["id"] for g in meta["queue_groups"]] == list(typing.get_args(QueueGroupName))
    assert [p["id"] for p in meta["queue_policies"]] == list(typing.get_args(QueuePolicyName))
    assert [o["id"] for o in meta["end_of_day"]["unfinished_trucks"]] == lit(EndOfDay, "unfinished_trucks")
    assert [o["id"] for o in meta["end_of_day"]["late_arrivals"]] == lit(EndOfDay, "late_arrivals")
    assert meta["labour"]["steps"] == lit(LabourRequirement, "step")
    assert [o["id"] for o in meta["labour"]["held"]] == lit(LabourRequirement, "held")
    assert [o["id"] for o in meta["labour"]["allocation"]] == lit(UnloadingLabour, "allocation")
    assert all(o["label"] for group in (meta["queue_policies"], meta["labour"]["held"]) for o in group)


def test_catalogue_describes_steps_tasks_and_phases_from_the_engine(client):
    """Screens for custom steps, background tasks and worker phases read the engine's own constants."""
    from silo_engine.config.rules_validation import BACKGROUND_STATION_TYPES, PHASE_STEPS
    meta = client.get("/meta").json()
    assert meta["background_task_station_types"] == list(BACKGROUND_STATION_TYPES)
    assert meta["phase_steps"] == list(PHASE_STEPS)
    assert "station" in meta["equipment_types"] and meta["equipment_types"]["station"]["connects_to"] == []
