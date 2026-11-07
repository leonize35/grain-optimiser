"""Load classes (gap G-D1): payload classes with their own share (optionally per hour) and payload range, and
unloading times per class at each hopper. Test inputs only.

- demand.<activity>.load_classes: [{id, share, payload [min, mode, max] t, hour_shares {hour: share}}]. A truck's
  class is drawn from its own stream (seed, "load_class", ...), so arrival times, commodity and grade draws are
  unchanged; within an hour, a class's weight is hour_shares[hour] if given, else share.
- hopper tip_by_class: {class: distribution}. A truck of a listed class takes that tipping time; others take the
  hopper's normal tipping time. The class time uses the same random number as the plain tipping time (CRN).
"""
import copy

import pytest

from silo_engine.config import load_site_config, validate
from silo_engine.inputs.generated import generate_arrivals
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.distributions import quantile
from silo_engine.sim.random_streams import Stream
from silo_engine.sim.service_times import FixedServiceTimes, StochasticServiceTimes
from silo_engine.sim.time import MS_PER_MINUTE, hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_partial_tipping import RAW as PARTIAL

CLASSES = [{"id": "small", "share": 1, "payload": [5, 10, 15], "hour_shares": {"7": 0}},
           {"id": "large", "share": 0, "payload": [30, 37, 45], "hour_shares": {"7": 1}}]


def site(**demand):
    r = copy.deepcopy(PARTIAL)  # one partial-tipping hopper H1 (30 t pit), tipping 10 min
    r["hours"] = {"open": 7, "close": 10}
    r["demand"] = {"unload": {"daily": 60, "mix": {"YM": 1}, **demand}}
    return r


def test_classes_are_drawn_per_hour_and_set_the_payload():
    """Small only, except in the 07:00 hour, which takes large only."""
    trucks = generate_arrivals(load_site_config(site(load_classes=CLASSES)), seed=4)
    assert trucks and all(t.load_class in ("small", "large") for t in trucks)
    for t in trucks:
        hour = t.arrive_ms // (60 * MS_PER_MINUTE)
        assert t.load_class == ("large" if hour == 7 else "small")
        lo, _, hi = next(c["payload"] for c in CLASSES if c["id"] == t.load_class)
        assert lo * 1000 <= t.kg <= hi * 1000


def test_classes_leave_arrival_times_and_commodities_unchanged():
    a = generate_arrivals(load_site_config(site(payload=[20, 25, 30])), seed=4)
    b = generate_arrivals(load_site_config(site(load_classes=CLASSES)), seed=4)
    assert [(t.id, t.arrive_ms, t.commodity) for t in a] == [(t.id, t.arrive_ms, t.commodity) for t in b]
    assert all(t.load_class is None for t in a)


def run(raw, trucks, times):
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": kg, **({"load_class": c} if c else {})}
        for t, at, kg, c in trucks]})
    r = TruckFlowModel(s, script, times, policy="feasible_first").run()
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    return r


def tip(r, t):
    s = next(s for x in r.records if x.truck_id == t for s in x.steps if s.step == "tip")
    return s.finished - s.started


def test_unloading_time_depends_on_the_class():
    """Hopper times: small 3 min, large 12 min; a truck without a class takes the hopper's normal time (10 min)."""
    raw = site(payload=[5, 10, 15])
    raw["equipment"][0]["tip_by_class"] = {"small": {"family": "fixed", "params": {"value": 3}},
                                           "large": {"family": "fixed", "params": {"value": 12}}}
    raw["demand"]["unload"]["load_classes"] = CLASSES
    times = FixedServiceTimes({"tip": 10, "tip|small": 3, "tip|large": 12})
    r = run(raw, [("T1", "07:00", 10, "small"), ("T2", "08:00", 20, "large"), ("T3", "09:00", 10, None)], times)
    assert (tip(r, "T1"), tip(r, "T2"), tip(r, "T3")) == (3 * MS_PER_MINUTE, 12 * MS_PER_MINUTE, 10 * MS_PER_MINUTE)


def test_class_times_use_the_same_random_number_as_the_plain_tipping_time():
    raw = site(load_classes=CLASSES)
    dist = {"family": "lognormal", "params": {"mu": 2.0823, "sigma": 0.8735}}
    raw["equipment"][0]["tip_by_class"] = {"large": dist}
    st = StochasticServiceTimes(load_site_config(raw), 7)
    u = Stream(7, "service", "T9", "tip").uniform()
    assert st.duration_ms("T9", "tip|large", "H1") == round(quantile(dist, u) * MS_PER_MINUTE)


def test_the_check_reads_payloads_from_the_classes():
    raw = site(load_classes=CLASSES)  # no single payload range
    raw["equipment"][0]["tip_admission"] = "full_load_space"
    msgs = [i.msg for i in validate(load_site_config(raw)).errors]
    assert not any("need a payload range" in m for m in msgs)
    assert any("largest unloading payload (45 t)" in m for m in msgs)  # large class above the 30 t pit


@pytest.mark.parametrize("change, words", [
    (lambda r: r["equipment"][0].update(tip_by_class={"huge": {"family": "fixed", "params": {"value": 1}}}), "unknown load class huge"),
    (lambda r: r["demand"]["unload"].update(load_classes=CLASSES + [CLASSES[0]]), "more than once"),
    (lambda r: r["demand"]["unload"].update(load_classes=[{**CLASSES[0], "payload": [15, 10, 5]}]), "min <= mode <= max"),
    (lambda r: r["demand"]["unload"].update(load_classes=[{**CLASSES[0], "share": 0, "hour_shares": {}}]), "share"),
])
def test_invalid_load_classes_are_refused(change, words):
    raw = site(load_classes=CLASSES)
    change(raw)
    with pytest.raises(ModelError) as err:
        run(raw, [("T1", "07:00", 10, None)], FixedServiceTimes({"tip": 10}))
    assert words in str(err.value)
