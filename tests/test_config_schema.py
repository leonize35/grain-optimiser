"""Behaviour of the configuration schema that goes beyond the prototype (documented, intentional differences)."""
import copy
import json
from pathlib import Path

import pytest

from silo_engine.config import ConfigSchemaError, config_hash, load_site_config, validate

CASES = {c["name"]: c for c in json.loads((Path(__file__).parent / "golden" / "validation_cases.json").read_text(encoding="utf-8"))["cases"]}


def site_a():
    return copy.deepcopy(CASES["site_a_valid"]["config"])


def test_every_golden_configuration_parses():
    for case in CASES.values():
        load_site_config(case["config"])


def test_misspelt_field_is_rejected_with_its_location():
    raw = site_a()
    raw["equipment"][3]["capacity"] = 60  # should be capT
    with pytest.raises(ConfigSchemaError) as err:
        load_site_config(raw)
    assert "equipment.3.capacity" in str(err.value)


def test_unknown_operating_rule_is_rejected():
    raw = site_a()
    raw["policies"]["tip"] = "random"
    with pytest.raises(ConfigSchemaError) as err:
        load_site_config(raw)
    assert "policies.tip" in str(err.value)


def test_unknown_truck_step_is_rejected():
    # The prototype accepts unknown step names silently; a truck reaching one would never advance.
    raw = site_a()
    raw["sequences"]["unload"].append("wash")
    with pytest.raises(ConfigSchemaError):
        load_site_config(raw)


def test_edge_to_unsupported_equipment_type_is_reported_not_crashing():
    # The prototype throws a TypeError here (CONNECT/TYPES lookup of an unknown type). We report the type instead.
    raw = site_a()
    raw["equipment"].append({"id": "D1", "type": "dryer", "name": "Dryer"})
    raw["edges"].append(["C1", "D1"])
    raw["edges"].append(["D1", "E1"])
    result = validate(load_site_config(raw))
    assert not result.ok
    assert result.errors[0].msg == "Dryer has an unsupported equipment type (dryer)."


def test_config_hash_ignores_key_order_and_tracks_content():
    raw = site_a()
    reordered = dict(reversed(list(raw.items())))
    assert config_hash(load_site_config(raw)) == config_hash(load_site_config(reordered))
    changed = site_a()
    changed["equipment"][3]["capT"] = 61
    assert config_hash(load_site_config(changed)) != config_hash(load_site_config(raw))
    assert len(config_hash(load_site_config(raw))) == 64
