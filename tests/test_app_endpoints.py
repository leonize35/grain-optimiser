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
