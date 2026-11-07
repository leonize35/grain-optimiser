"""TLS slice T4 (docs/TLS_ANALYSIS_DESIGN.md §5): CTQs and capability. Hand-traced; test inputs. Analysis only.

A CTQ is set per silo or study (no default target): a measure per truck, an upper limit (USL, minutes) and optionally
a lower limit. Measures: turnaround (gate arrival to departure), weighbridge_interval (start of weigh-in to end of
weigh-out), hopper_wait (reaching the tipping step to starting to tip).
Unfinished trucks are censored: one whose value so far already exceeds the USL is a defect; otherwise its outcome
is unknown and it is reported apart, never dropped silently. Turned-away trucks are reported apart and count as
defects only if the study says so.
Trucks of tests/test_outcomes_clearance.py: turnaround T5 19, T1 14, T2 9, T3 9 (completed); T4 at the gate, 29 so far.
"""
import pytest

from silo_engine.analysis.capability import capability
from test_outcomes_clearance import run


def test_defects_yield_and_dpmo_with_censoring():
    c = capability([run()], {"measure": "turnaround", "usl": 10})
    assert (c["assessed"], c["defects"], c["unknown"], c["turned_away"]) == (5, 3, 0, 0)  # T5, T1, T4 (29 > 10)
    assert (c["defect_share"], c["yield"], c["dpmo"]) == (0.6, 0.4, 600000)
    c = capability([run()], {"measure": "turnaround", "usl": 30})
    assert (c["assessed"], c["defects"], c["unknown"]) == (4, 0, 1)  # T4: 29 so far, not yet past 30


def test_other_measures():
    """Weighbridge interval: weigh-in start to weigh-out end: T5 9 (07:00-07:09), T1 12 (07:02-07:14), T2 9, T3 9.
    Hopper wait: T1 3, others 0."""
    w = capability([run()], {"measure": "weighbridge_interval", "usl": 10})
    assert (w["assessed"], w["defects"], w["unknown"]) == (4, 1, 0)  # T4 never weighed in: no value, not assessed
    assert w["values"]["completed"] == [9, 9, 9, 12]
    h = capability([run()], {"measure": "hopper_wait", "usl": 2})
    assert (h["defects"], h["values"]["completed"]) == (1, [0, 0, 0, 3])


def test_performance_indices_by_percentiles_and_sigma_level():
    """Completed turnaround [9, 9, 14, 19] (percentiles by linear interpolation): median 11.5, P99.865 ~ 18.98,
    P0.135 ~ 9. With USL 20: Ppu = (20 - 11.5) / (P99.865 - 11.5). Too few trucks for a reliable index (below
    `min_n`), so the index is flagged; the sigma level is shown only when asked, with or without the 1.5 shift."""
    c = capability([run()], {"measure": "turnaround", "usl": 20}, min_n=3)
    p99 = 14 + (19 - 14) * (0.99865 * 3 - 2)
    assert c["percentiles"]["p99_865"] == pytest.approx(p99)
    assert c["ppk"] == pytest.approx((20 - 11.5) / (p99 - 11.5)) and c["pp"] is None  # no LSL: Pp undefined
    assert c["index_reliable"] is True
    assert capability([run()], {"measure": "turnaround", "usl": 20})["index_reliable"] is False  # min_n 30
    assert "sigma_level" not in c
    s = capability([run()], {"measure": "turnaround", "usl": 10}, sigma_level=True, shift=1.5)
    from statistics import NormalDist
    assert s["sigma_level"] == pytest.approx(NormalDist().inv_cdf(0.4) + 1.5)


def test_replications_give_an_interval():
    """Two identical replications: defect share 0.6 in both; the 95 % interval has zero width."""
    c = capability([run(), run()], {"measure": "turnaround", "usl": 10})
    assert c["by_replication"] == [0.6, 0.6]
    assert (c["defect_share_mean"], c["defect_share_low"], c["defect_share_high"]) == (0.6, 0.6, 0.6)


def test_turned_away_trucks_count_as_defects_only_if_chosen():
    """With send-away after the cut-off, T4 is turned away instead of held."""
    r = run(end_of_day={"late_arrivals": "turned_away"})
    assert r.outcomes["trucks"]["T4"]["status"] == "turned_away"
    c = capability([r], {"measure": "turnaround", "usl": 10})
    assert (c["assessed"], c["defects"], c["turned_away"]) == (4, 2, 1)
    c = capability([r], {"measure": "turnaround", "usl": 10, "turned_away_is_defect": True})
    assert (c["assessed"], c["defects"]) == (5, 3)


def test_a_ctq_needs_a_limit():
    with pytest.raises(ValueError, match="upper limit"):
        capability([run()], {"measure": "turnaround"})
    with pytest.raises(ValueError, match="measure"):
        capability([run()], {"measure": "speed", "usl": 1})
