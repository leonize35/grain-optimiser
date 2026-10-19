"""Event calendar: chronological order, deterministic tie-breaks, cancellation and clock safety.

Expected results are written out by hand so each test can be checked without running code.
Times are integer milliseconds; helpers m() / hm() convert minutes and clock times for readability.
"""
import pytest

from silo_engine.sim.calendar import ARRIVAL, CONTROL, RELEASE, Calendar, SchedulingError
from silo_engine.sim.time import hm, m


def run_labels(cal: Calendar) -> list[str]:
    cal.run()
    return [e.label for e in cal.log]


def test_events_run_in_time_order_regardless_of_scheduling_order():
    cal = Calendar()
    cal.schedule(m(30), ARRIVAL, None, "c@30")
    cal.schedule(m(10), ARRIVAL, None, "a@10")
    cal.schedule(m(20), ARRIVAL, None, "b@20")
    assert run_labels(cal) == ["a@10", "b@20", "c@30"]
    assert cal.now == m(30)


def test_simultaneous_events_run_release_then_control_then_arrival():
    # All at 07:00. Scheduled deliberately in the "wrong" order.
    cal = Calendar()
    cal.schedule(hm("07:00"), ARRIVAL, None, "truck arrives")
    cal.schedule(hm("07:00"), CONTROL, None, "end of day check")
    cal.schedule(hm("07:00"), RELEASE, None, "weighbridge released")
    assert run_labels(cal) == ["weighbridge released", "end of day check", "truck arrives"]


def test_simultaneous_events_of_equal_priority_run_in_scheduling_order():
    cal = Calendar()
    for name in ["T1", "T2", "T3", "T4"]:
        cal.schedule(hm("07:00"), ARRIVAL, None, name)
    assert run_labels(cal) == ["T1", "T2", "T3", "T4"]


def test_event_scheduled_during_execution_at_same_time_follows_priority_then_sequence():
    # At 08:00 two arrivals are queued (A1, A2). When A1 runs it schedules, for the same instant,
    # a release R and another arrival A3. Hand-derived order: A1, then R (release beats arrival),
    # then A2 (queued before A3), then A3.
    cal = Calendar()

    def a1(c: Calendar) -> None:
        c.schedule(c.now, ARRIVAL, None, "A3")
        c.schedule(c.now, RELEASE, None, "R")

    cal.schedule(hm("08:00"), ARRIVAL, a1, "A1")
    cal.schedule(hm("08:00"), ARRIVAL, None, "A2")
    assert run_labels(cal) == ["A1", "R", "A2", "A3"]


def test_scheduling_in_the_past_is_refused_but_now_is_allowed():
    cal = Calendar()
    cal.schedule(m(10), ARRIVAL, None, "first")
    cal.run()
    assert cal.now == m(10)
    cal.schedule(m(10), RELEASE, None, "zero-duration follow-up")  # allowed: same instant
    with pytest.raises(SchedulingError):
        cal.schedule(m(10) - 1, RELEASE, None, "one millisecond in the past")


def test_non_integer_time_and_unknown_priority_are_refused():
    cal = Calendar()
    with pytest.raises(SchedulingError):
        cal.schedule(1.5, ARRIVAL, None, "float time")  # type: ignore[arg-type]
    with pytest.raises(SchedulingError):
        cal.schedule(m(1), 7, None, "bad priority")


def test_cancelled_event_does_not_run_and_does_not_move_the_clock():
    cal = Calendar()
    keep = cal.schedule(m(5), ARRIVAL, None, "keep")
    drop = cal.schedule(m(9), RELEASE, None, "drop")
    cal.cancel(drop)
    cal.run()
    assert [e.label for e in cal.log] == ["keep"]
    assert cal.now == m(5)
    assert keep.done and drop.cancelled and not drop.done


def test_run_until_executes_events_at_the_limit_and_leaves_later_ones():
    cal = Calendar()
    for t, name in [(m(10), "a"), (m(20), "b-at-limit"), (m(21), "c-after")]:
        cal.schedule(t, ARRIVAL, None, name)
    cal.run(until=m(20))
    assert [e.label for e in cal.log] == ["a", "b-at-limit"]
    assert cal.now == m(20)
    assert cal.pending == 1
    assert cal.peek_time() == m(21)


def test_run_until_advances_clock_to_limit_when_calendar_empties_earlier():
    cal = Calendar()
    cal.schedule(m(10), ARRIVAL, None, "a")
    cal.run(until=hm("18:00"))
    assert cal.now == hm("18:00")


def test_identical_schedules_give_identical_logs():
    def build() -> list[tuple[int, int, int, str]]:
        cal = Calendar()
        for i, t in enumerate([m(3), m(1), m(3), m(2), m(1)]):
            cal.schedule(t, ARRIVAL if i % 2 else RELEASE, None, f"e{i}")
        cal.run()
        return [(e.time, e.priority, e.seq, e.label) for e in cal.log]

    assert build() == build()
    # Hand-derived: t=1: e1 (ARRIVAL, seq1) vs e4 (RELEASE, seq4) -> e4 first; t=2: e3; t=3: e0 (RELEASE) then e2.
    assert [x[3] for x in build()] == ["e4", "e1", "e3", "e0", "e2"]


def test_worked_example_single_weighbridge_trace():
    """Hand-checkable trace with a test-only model: one weighbridge, fixed 2-minute weighing, strict order.

    Arrivals: T1 07:00, T2 07:01, T3 07:01.
      T1 starts 07:00, finishes 07:02.
      At 07:02 the release runs before anything else at 07:02; T2 starts 07:02, finishes 07:04.
      T3 starts 07:04, finishes 07:06.
    Waits: T1 0 min, T2 1 min, T3 3 min.
    """
    cal = Calendar()
    queue: list[str] = []
    busy = {"wb": None}
    arrived: dict[str, int] = {}
    started: dict[str, int] = {}
    finished: dict[str, int] = {}

    def try_start(c: Calendar) -> None:
        if busy["wb"] is None and queue:
            truck = queue.pop(0)
            busy["wb"] = truck
            started[truck] = c.now
            c.schedule(c.now + m(2), RELEASE, finish, f"{truck} weighed")

    def finish(c: Calendar) -> None:
        truck = busy["wb"]
        finished[truck] = c.now
        busy["wb"] = None
        try_start(c)

    def arrive(truck: str):
        def action(c: Calendar) -> None:
            arrived[truck] = c.now
            queue.append(truck)
            try_start(c)
        return action

    for truck, t in [("T1", "07:00"), ("T2", "07:01"), ("T3", "07:01")]:
        cal.schedule(hm(t), ARRIVAL, arrive(truck), f"{truck} arrives")
    cal.run()

    assert started == {"T1": hm("07:00"), "T2": hm("07:02"), "T3": hm("07:04")}
    assert finished == {"T1": hm("07:02"), "T2": hm("07:04"), "T3": hm("07:06")}
    assert {t: (started[t] - arrived[t]) // m(1) for t in started} == {"T1": 0, "T2": 1, "T3": 3}
    assert [e.label for e in cal.log] == [
        "T1 arrives", "T2 arrives", "T3 arrives", "T1 weighed", "T2 weighed", "T3 weighed"]
