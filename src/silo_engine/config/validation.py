"""Manager-facing configuration validation (port of prototype engine v0.2.0 `validate`).

The checks, wording and order of messages match the prototype exactly; tests/test_validation_parity.py holds
the evidence. Errors block a run, warnings need the manager's attention, info explains shared equipment.
The one intentional difference: a connection touching equipment of an unsupported type is skipped instead of
crashing, because the unsupported type is already reported as an error.
"""
from dataclasses import dataclass, field

from .jscompat import js_number, js_round, js_str
from .routes import RouteTable, build_routes, is_transfer
from .schema import ActivityDemand, Equipment, SiteConfig

EPS = 1e-6

EQUIPMENT_LABEL = {
    "sampler": "Sampling point",
    "grader": "Grading station",
    "weighbridge": "Weighbridge",
    "hopper": "Unloading hopper",
    "conveyor": "Conveyor",
    "elevator": "Bucket elevator",
    "bin": "Storage bin",
    "loadpoint": "Loading point",
}
# Which equipment types each type may discharge grain into.
ALLOWED_CONNECTIONS = {
    "hopper": ("conveyor", "elevator"),
    "conveyor": ("conveyor", "elevator", "bin", "loadpoint"),
    "elevator": ("conveyor", "bin", "loadpoint"),
    "bin": ("conveyor", "elevator", "loadpoint"),
    "loadpoint": (),
    "sampler": (),
    "grader": (),
    "weighbridge": (),
}
ACTIVITY_LABEL = {"unload": "Unloading", "load": "Loading", "weigh": "Weighbridge only"}
TRUCK_STATIONS = ("sampler", "grader", "weighbridge")


@dataclass
class Issue:
    msg: str
    ids: list[str] = field(default_factory=list)  # equipment to highlight


@dataclass
class ValidationResult:
    ok: bool
    errors: list[Issue]
    warnings: list[Issue]
    info: list[Issue]
    routes: RouteTable
    shared: list[str]  # equipment used by more than one grain stream
    users: dict[str, list[str]]  # equipment id -> hopper names (and 'loading') whose routes use it
    unreachable: list[str]  # bins no hopper can reach


def _list_names(names: list[str]) -> str:
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def _gt(a: float | None, b: float) -> bool:
    """JavaScript `a > b` where a missing value compares false."""
    return a is not None and a > b


def _third(values: list[float] | None) -> float | None:
    """values[2] of a triangular [min, mode, max] triple, or None when absent (JavaScript `undefined`)."""
    return values[2] if values is not None and len(values) > 2 else None


def _active(d: ActivityDemand | None) -> bool:
    return d is not None and d.daily > 0


def validate(cfg: SiteConfig) -> ValidationResult:
    errors: list[Issue] = []
    warnings: list[Issue] = []
    info: list[Issue] = []

    def err(msg: str, ids: list[str] | None = None) -> None:
        errors.append(Issue(msg, list(ids or [])))

    def warn(msg: str, ids: list[str] | None = None) -> None:
        warnings.append(Issue(msg, list(ids or [])))

    eqs = cfg.equipment
    commodity_names = {c.id: c.name for c in cfg.commodities}

    def cname(c: str | None) -> str:
        return commodity_names.get(c, js_str(c)) if c is not None else "undefined"

    def name(e: Equipment) -> str:
        return js_str(e.name)

    # identifiers and types
    seen_ids: set[str] = set()
    for e in eqs:
        if e.id in seen_ids:
            err("Two items share the identifier " + e.id + ". Each item needs its own identifier.", [e.id])
        seen_ids.add(e.id)
        if e.type not in EQUIPMENT_LABEL:
            err(name(e) + " has an unsupported equipment type (" + e.type + ").", [e.id])
    by_id = {e.id: e for e in eqs}  # with duplicate ids the last item wins, as in the prototype
    cids = set(commodity_names)

    # connections
    seen_edges: set[tuple[str, str]] = set()
    for a, b in cfg.edges:
        if a not in by_id or b not in by_id:
            err("A connection refers to equipment that no longer exists (" + a + " to " + b + ").")
            continue
        if (a, b) in seen_edges:
            warn("The connection from " + name(by_id[a]) + " to " + name(by_id[b]) + " is listed twice.", [a, b])
        seen_edges.add((a, b))
        ta, tb = by_id[a].type, by_id[b].type
        if ta not in EQUIPMENT_LABEL or tb not in EQUIPMENT_LABEL:
            continue  # unsupported type already reported (the prototype crashes here)
        if tb not in ALLOWED_CONNECTIONS[ta]:
            err(name(by_id[a]) + " cannot feed " + name(by_id[b]) + ". A " + EQUIPMENT_LABEL[ta].lower()
                + " cannot discharge into a " + EQUIPMENT_LABEL[tb].lower() + ".", [a, b])

    # capacities and opening stock
    for e in eqs:
        if e.type in TRUCK_STATIONS:
            if e.cap is None or not e.cap >= 1:
                err(name(e) + " needs a capacity of at least 1 truck at a time.", [e.id])
            if not e.time or not _gt(_third(e.time), 0):
                err(name(e) + " needs a processing time.", [e.id])
        if e.type == "hopper":
            if not _gt(e.cap_t, 0):
                err(name(e) + " needs a pit capacity in tonnes.", [e.id])
            if not _gt(e.rate, 0):
                err(name(e) + " needs a discharge rate in t/h.", [e.id])
            for c in e.commodities or []:
                if c not in cids:
                    err(name(e) + " is assigned to an unknown commodity (" + c + ").", [e.id])
            if not e.commodities:
                warn(name(e) + " accepts no commodity, so no truck will use it.", [e.id])
        if is_transfer(e.type) and not _gt(e.rate, 0):
            err(name(e) + " needs a transfer rate in t/h.", [e.id])
        if e.type == "loadpoint" and not _gt(e.rate, 0):
            err(name(e) + " needs a loading rate in t/h.", [e.id])
        if e.type == "bin":
            if not _gt(e.cap_t, 0):
                err(name(e) + " needs a capacity in tonnes.", [e.id])
            if (e.inv or 0) > (e.cap_t or 0) + EPS:
                err(name(e) + " holds " + js_number(e.inv) + " t at the start, more than its "
                    + js_number(e.cap_t) + " t capacity.", [e.id])
            if (e.inv or 0) > 0 and e.inv_commodity not in (e.commodities or []):
                err(name(e) + " starts with " + cname(e.inv_commodity) + ", which the bin is not allowed to store.", [e.id])

    routes = build_routes(cfg)

    # loops among conveyors and elevators (a bin legitimately breaks a loop: reclaim back into an elevator)
    colour: dict[str, int] = {}
    cycle_at: list[str] | None = None

    def visit(n: str) -> None:
        nonlocal cycle_at
        colour[n] = 1
        for m in routes.out.get(n, []):
            if m not in by_id or not is_transfer(by_id[m].type):
                continue
            if colour.get(m) == 1:
                cycle_at = cycle_at or [n, m]
                continue
            if not colour.get(m):
                visit(m)
        colour[n] = 2

    for n in [e.id for e in eqs if is_transfer(e.type) or e.type == "hopper"]:
        if not colour.get(n):
            visit(n)
    if cycle_at:
        err("Grain could circulate in a loop between " + name(by_id[cycle_at[0]]) + " and " + name(by_id[cycle_at[1]])
            + ". Remove one of the connections in that loop.", cycle_at)

    # truck activity sequences
    def has(equipment_type: str, pred=None) -> bool:
        return any(e.type == equipment_type and (pred is None or pred(e)) for e in eqs)

    demand = {"unload": cfg.demand.unload, "load": cfg.demand.load, "weigh": cfg.demand.weigh}
    for act, label in ACTIVITY_LABEL.items():
        if not _active(demand[act]):
            continue
        steps = getattr(cfg.sequences, act)
        if not steps:
            err(label + " trucks have no activity sequence.")
        for i, step in enumerate(steps):
            if step == "sample" and not has("sampler"):
                err(label + " trucks need a sampling point, but none is configured.")
            if step == "grade":
                if not has("grader"):
                    err(label + " trucks need a grading station, but none is configured.")
                if "sample" not in steps or steps.index("sample") > i:
                    err(label + " trucks are graded before a sample is taken. Put Sampling before Grading.")
            if step == "weigh_in" and not has("weighbridge", lambda e: e.moves != "out"):
                err(label + " trucks need a weighbridge that weighs in.")
            if step == "weigh_out" and not has("weighbridge", lambda e: e.moves != "in"):
                err(label + " trucks need a weighbridge that weighs out.")
            if step == "tip" and act != "unload":
                err("Only unloading trucks can tip into a hopper.")
            if step == "load" and act != "load":
                err("Only loading trucks can be loaded.")
        if act == "unload" and "tip" not in steps:
            err("Unloading trucks never reach a hopper. Add Unloading to their sequence.")
        if act == "load" and "load" not in steps:
            err("Loading trucks never reach a loading point. Add Loading to their sequence.")

    # hopper reachability and commodity routing
    hoppers = [e for e in eqs if e.type == "hopper"]
    bins = [e for e in eqs if e.type == "bin"]
    for h in hoppers:
        paths = routes.intake.get(h.id, [])
        if not routes.out.get(h.id):
            err(name(h) + " is not connected to any conveyor or elevator, so grain tipped there cannot leave the pit.", [h.id])
            continue
        if not paths:
            err(name(h) + " has no complete route to a storage bin. Follow its conveyors and elevators and connect"
                " the last one to a bin.", [h.id])
            continue
        reach = list(dict.fromkeys(p[-1] for p in paths))
        for c in h.commodities or []:
            if any(c in (by_id[b].commodities or []) for b in reach):
                continue
            accepting = [name(b) for b in bins if c in (b.commodities or [])]
            last_hops = list(dict.fromkeys(name(by_id[p[-2]]) for p in paths))
            if not accepting:
                err(name(h) + " accepts " + cname(c) + ", but no storage bin is allowed to hold " + cname(c) + ".", [h.id])
            else:
                err(name(h) + " cannot deliver " + cname(c) + " to any eligible storage bin because "
                    + _list_names(last_hops) + " " + ("are" if len(last_hops) > 1 else "is")
                    + " not connected to " + _list_names(accepting) + ".", [h.id])

    def reached_by_hopper(bin_id: str) -> bool:
        return any(any(p[-1] == bin_id for p in routes.intake.get(h.id, [])) for h in hoppers)

    for b in bins:
        if not reached_by_hopper(b.id):
            warn(name(b) + " cannot receive grain from any hopper.", [b.id])

    # unloading demand
    un = cfg.demand.unload
    if _active(un):
        mix = un.mix
        total = sum(mix.values())
        if abs(total - 1) > 0.01:
            warn("The unloading commodity mix adds up to " + str(js_round(total * 100)) + "%. It will be scaled to 100%.")
        for c, share in mix.items():
            if not share > 0:
                continue
            if c not in cids:
                err("Unloading demand includes an unknown commodity (" + c + ").")
                continue
            if not any(c in (h.commodities or []) for h in hoppers):
                err(cname(c) + " trucks arrive, but no hopper accepts " + cname(c) + ".")
        largest_payload = _third(un.payload)
        if un.payload is None or not _gt(largest_payload, 0):
            err("Unloading trucks need a payload range in tonnes.")
        max_hopper = max([0.0] + [h.cap_t or 0 for h in hoppers])
        if un.payload is not None and _gt(largest_payload, max_hopper + EPS):
            err("The largest unloading payload (" + js_number(largest_payload) + " t) exceeds every hopper capacity (largest "
                + js_number(max_hopper) + " t).")

    # loading demand
    ld = cfg.demand.load
    if _active(ld):
        threshold = _third(ld.payload) if ld.payload is not None else 30
        for c, share in ld.mix.items():
            if not share > 0:
                continue
            holding = [b for b in bins if c in (b.commodities or [])]
            connected = [b for b in holding if routes.load.get(b.id)]
            if not holding:
                err("Loading trucks collect " + cname(c) + ", but no bin stores it.")
            elif not connected:
                err("Loading trucks collect " + cname(c) + ", but no bin holding it is connected to a loading point.")
            else:
                stock = sum((b.inv or 0) if b.inv_commodity == c else 0 for b in connected)
                fed_by_intake = _active(un) and un.mix.get(c, 0) > 0
                short = threshold is not None and stock < threshold
                if short and not fed_by_intake:
                    err("Loading trucks collect " + cname(c) + ", but there is no opening stock and no intake of it.")
                elif short:
                    warn("There is little opening stock of " + cname(c) + ". Early loading trucks will wait for intake.")

    # shared equipment
    users: dict[str, list[str]] = {}

    def add_user(equipment_id: str, user: str) -> None:
        names = users.setdefault(equipment_id, [])
        if user not in names:
            names.append(user)

    for h in hoppers:
        for p in routes.intake.get(h.id, []):
            for m in p[1:-1]:
                add_user(m, name(h))
    for b in bins:
        for p in routes.load.get(b.id, []):
            for m in p[1:-1]:
                add_user(m, "loading")
    shared = [k for k, v in users.items() if len(v) > 1]
    for k in shared:
        info.append(Issue(name(by_id[k]) + " is shared by " + _list_names(users[k]) + ". Only one grain stream can use it at a time.", [k]))
    weighbridges = [e for e in eqs if e.type == "weighbridge"]
    active_acts = [a for a in ACTIVITY_LABEL if _active(demand[a])]
    if weighbridges and len(active_acts) > 1:
        info.append(Issue("Weighbridge capacity is shared by " + _list_names([ACTIVITY_LABEL[a].lower() for a in active_acts])
                          + " trucks.", [e.id for e in weighbridges]))
    unreachable = [b.id for b in bins if not reached_by_hopper(b.id)]

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings, info=info, routes=routes,
                            shared=shared, users=users, unreachable=unreachable)
