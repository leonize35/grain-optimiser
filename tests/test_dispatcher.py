"""Central dispatcher in isolation: ordering, strict FIFO vs feasible-first, reasons and overtake counting."""
from silo_engine.sim.dispatcher import Dispatcher, WaitReason


class Gate:
    """Test resource: a set of named 'free' tokens; a request needs one specific token."""

    def __init__(self, free):
        self.free = set(free)
        self.started = []

    def need(self, rid, token):
        def attempt(now):
            if token not in self.free:
                return [WaitReason("EQUIPMENT_BUSY", token, f"{token} is busy")]
            self.free.discard(token)
            self.started.append(rid)
            return []
        return attempt


def test_requests_are_considered_in_submission_order():
    gate = Gate({"x", "y"})
    d = Dispatcher({"g": "feasible_first"})
    d.submit("r1", "g", 0, gate.need("r1", "x"))
    d.submit("r2", "g", 0, gate.need("r2", "y"))
    d.reconsider(0)
    assert gate.started == ["r1", "r2"]
    assert d.pending_ids() == []


def test_feasible_first_skips_a_blocked_request_and_counts_the_overtake():
    gate = Gate({"y"})
    d = Dispatcher({"g": "feasible_first"})
    d.submit("r1", "g", 0, gate.need("r1", "x"))  # blocked: x busy
    d.submit("r2", "g", 0, gate.need("r2", "y"))
    d.reconsider(0)
    assert gate.started == ["r2"]
    assert d.overtaken() == {"r1": 1}
    assert [r.code for r in d.waiting_reasons()["r1"]] == ["EQUIPMENT_BUSY"]


def test_strict_fifo_blocks_later_requests_of_the_same_group_only():
    gate = Gate({"y", "z"})
    d = Dispatcher({"g": "strict_fifo", "h": "strict_fifo"})
    d.submit("r1", "g", 0, gate.need("r1", "x"))  # blocked
    d.submit("r2", "g", 0, gate.need("r2", "y"))  # must wait behind r1
    d.submit("r3", "h", 0, gate.need("r3", "z"))  # other group: unaffected
    d.reconsider(0)
    assert gate.started == ["r3"]
    assert [r.code for r in d.waiting_reasons()["r2"]] == ["QUEUE_ORDER"]
    gate.free.add("x")
    d.reconsider(1)
    assert gate.started == ["r3", "r1", "r2"]
    assert d.overtaken() == {}


def test_after_each_start_the_scan_restarts_from_the_earliest_request():
    # r2 starting frees a token r1 needs (a release triggered by a start). r1 must then get it before r3.
    log = []
    free = {"b"}

    def r1(now):
        if "a" not in free:
            return [WaitReason("EQUIPMENT_BUSY", "a", "a busy")]
        free.discard("a"); log.append("r1"); return []

    def r2(now):
        free.discard("b"); free.add("a"); log.append("r2"); return []

    def r3(now):
        if "a" not in free:
            return [WaitReason("EQUIPMENT_BUSY", "a", "a busy")]
        free.discard("a"); log.append("r3"); return []

    d = Dispatcher({"g": "feasible_first"})
    d.submit("r1", "g", 0, r1)
    d.submit("r2", "g", 0, r2)
    d.submit("r3", "g", 0, r3)
    d.reconsider(0)
    assert log == ["r2", "r1"]
    assert d.pending_ids() == ["r3"]
