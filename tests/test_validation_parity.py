"""Parity of the Python configuration validator with the prototype engine v0.2.0 (the reference oracle).

tests/golden/validation_cases.json is produced by tools/golden/generate_validation_golden.html, which runs the
unmodified prototype `validate()` in a browser. Each case holds the input configuration and the oracle's output.
Messages, issue order, highlighted equipment ids, shared-equipment users and route ordering must all match exactly.
"""
import json
from pathlib import Path

import pytest

from silo_engine.config import load_site_config, validate

GOLDEN = json.loads((Path(__file__).parent / "golden" / "validation_cases.json").read_text(encoding="utf-8"))
CASES = GOLDEN["cases"]


def issues(items):
    return [{"msg": i.msg, "ids": list(i.ids)} for i in items]


def test_golden_file_comes_from_prototype_engine():
    assert GOLDEN["oracle_engine_version"] == "0.2.0"
    assert len(CASES) >= 12
    assert any(c["expected"]["ok"] for c in CASES) and any(not c["expected"]["ok"] for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_validation_matches_prototype(case):
    expected = case["expected"]
    result = validate(load_site_config(case["config"]))
    assert issues(result.errors) == expected["errors"]
    assert issues(result.warnings) == expected["warnings"]
    assert issues(result.info) == expected["info"]
    assert result.ok == expected["ok"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_routes_and_sharing_match_prototype(case):
    expected = case["expected"]
    result = validate(load_site_config(case["config"]))
    assert result.routes.intake == expected["intake"]
    assert result.routes.load == expected["load"]
    assert result.shared == expected["shared"]
    assert result.users == expected["users"]
    assert result.unreachable == expected["unreachable"]
