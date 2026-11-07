"""Validation of the confirmed operating rules (R1–R7) that go beyond the prototype.

`config.validation.validate` reproduces the prototype exactly and must not change. Checks for the new rules live
here; the engine refuses to run a site with errors from either. Messages are in manager language and name the
equipment involved.

Currently checked:
- R4 grades: mixing rules, bin grade lists and opening stock refer to real grades; every bin holding a graded
  commodity lists its grades (unless segregation is 'none'); every grade can reach a bin that accepts it;
  grading happens before tipping where bins keep grades apart.
- R3 changeovers: unknown commodities/grades/equipment in rules; for every pair of commodities that can meet on
  the same conveyor or elevator (from the configured routes), a rule or a default must exist, and equally
  specific rules must agree. Sites in the prototype format get a warning saying where changeover times come from.
"""
from dataclasses import dataclass, field

from ..domain.changeover import SEGMENT_TYPES, AmbiguousRule, ChangeoverMatrix
from ..domain.storage import GradedCommodity
from .grades import GradePolicy
from .routes import build_routes
from .schema import SiteConfig
from .validation import Issue

UNGRADED = "*"


@dataclass
class RulesResult:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _minutes(value) -> str:
    return format(value.normalize(), "f")


def segment_commodities(site: SiteConfig) -> dict[str, list[str]]:
    """Commodities each conveyor/elevator can carry, from the configured routes, in site commodity order."""
    by_id = {e.id: e for e in site.equipment}
    order = [c.id for c in site.commodities]
    carried: dict[str, set[str]] = {e.id: set() for e in site.equipment if e.type in SEGMENT_TYPES}
    routes = build_routes(site)
    for hopper_id, paths in routes.intake.items():
        for p in paths:
            grain = set(by_id[hopper_id].commodities or []) & set(by_id[p[-1]].commodities or [])
            for seg in p[1:-1]:
                carried[seg] |= grain
    for bin_id, paths in routes.load.items():
        for p in paths:
            for seg in p[1:-1]:
                if seg in carried:
                    carried[seg] |= set(by_id[bin_id].commodities or [])
    return {seg: [c for c in order if c in cs] for seg, cs in carried.items()}


def _validate_grades(site: SiteConfig, result: RulesResult) -> None:
    policy = GradePolicy(site)
    names = {c.id: c.name for c in site.commodities}

    def err(msg: str, ids: list[str] | None = None) -> None:
        result.errors.append(Issue(msg, ids or []))

    for rule in site.grade_mixing:
        name = names.get(rule.commodity, rule.commodity)
        if not policy.is_graded(rule.commodity):
            err(f"Grade mixing refers to {name}, which has no grades.")
            continue
        for g in dict.fromkeys(rule.grades + [rule.result]):
            if g not in policy.grades[rule.commodity]:
                err(f"Grade mixing for {name} refers to grade {g}, which is not one of its grades.")

    for e in site.equipment:
        label = e.name or e.id
        if e.type == "bin":
            if site.grade_segregation == "none":
                if e.accepts:
                    err(f"{label} lists grades, but grade segregation is set to none.", [e.id])
            else:
                for entry in e.accepts or []:
                    name = names.get(entry.commodity, entry.commodity)
                    if entry.commodity not in (e.commodities or []):
                        err(f"{label} lists grades for {name}, which it does not store.", [e.id])
                    elif not policy.is_graded(entry.commodity):
                        err(f"{label} lists grades for {name}, which has no grades.", [e.id])
                    else:
                        for g in entry.grades:
                            if g not in policy.grades[entry.commodity]:
                                err(f"{label} accepts {name} grade {g}, which is not one of its grades.", [e.id])
                listed = {a.commodity for a in e.accepts or []}
                for c in e.commodities or []:
                    if policy.segregated(c) and c not in listed:
                        err(f"{label} stores {names.get(c, c)}, which has grades, but does not say which grades it "
                            "accepts. List them, or set grade segregation to none.", [e.id])
        opening = (e.inv, e.inv_commodity, e.inv_grade) if e.type == "bin" else (e.level0, e.level_commodity, e.level_grade)
        if e.type in ("bin", "hopper") and opening[0] and opening[1] and policy.segregated(opening[1]):
            name = names.get(opening[1], opening[1])
            if opening[2] is None:
                err(f"{label} starts with {name} but no grade; give the grade of the opening stock.", [e.id])
            elif opening[2] not in policy.grades[opening[1]]:
                err(f"{label} starts with {name} grade {opening[2]}, which is not one of its grades.", [e.id])
            elif e.type == "bin" and GradedCommodity(opening[1], opening[2]) not in policy.bin_accepts(e):
                err(f"{label} starts with {name} grade {opening[2]}, which it does not accept.", [e.id])

    by_id = {e.id: e for e in site.equipment}
    routes = build_routes(site)
    unload_steps = site.sequences.unload
    graded_before_tip = "tip" not in unload_steps or "grade" in unload_steps[:unload_steps.index("tip")]
    for c in policy.grades:
        if not policy.segregated(c):
            continue
        hoppers = [e.id for e in site.equipment if e.type == "hopper" and c in (e.commodities or [])]
        reachable = [by_id[p[-1]] for h in hoppers for p in routes.intake.get(h, [])]
        if not hoppers or any(c in (b.commodities or []) and c not in {a.commodity for a in b.accepts or []}
                              for b in reachable):
            continue  # a bin without a grade list is already reported; avoid knock-on messages
        for g in policy.grades[c]:
            if not any(GradedCommodity(c, g) in policy.bin_accepts(b) for b in reachable):
                err(f"No storage bin reachable from a hopper accepts {names[c]} grade {g}.")
        restricted = any(not all(GradedCommodity(c, g) in policy.bin_accepts(b) for g in policy.grades[c])
                         for b in reachable if c in (b.commodities or []))
        if restricted and not graded_before_tip:
            err(f"Bins keep {names[c]} grades apart, but unloading trucks tip before they are graded. "
                "Put Grading before Unloading, or set grade segregation to none.")


TRUCK_STEPS = ("sample", "grade", "weigh_in", "tip", "load", "weigh_out")
PATH_LABEL = {"unload": "unloading", "load": "loading", "weigh": "weighbridge-only"}


def step_names(site: SiteConfig) -> tuple[str, ...]:
    """Built-in truck steps and the site's custom steps."""
    return TRUCK_STEPS + tuple(c.id for c in site.custom_steps)


def _validate_custom_steps(site: SiteConfig, result: RulesResult) -> None:
    """G2: site-defined steps, and every sequence step known."""
    err = lambda msg: result.errors.append(Issue(msg))  # noqa: E731
    by_id = {e.id: e for e in site.equipment}
    ids = [c.id for c in site.custom_steps]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        err(f"The step {dup} is defined more than once.")
    for c in site.custom_steps:
        if c.id in TRUCK_STEPS or c.id == "pass":
            err(f"The step {c.id} is a built-in step; give the site's own step another id.")
        if not c.equipment:
            err(f"The step {c.label} needs at least one station where it is done.")
        for eq in c.equipment:
            e = by_id.get(eq)
            if e is None:
                err(f"The step {c.label} uses unknown equipment {eq}.")
            elif e.type != "station":
                err(f"The step {c.label} must be done at equipment of type station, not {eq} ({e.type}).")
    known = step_names(site)
    for act, label in PATH_LABEL.items():
        for s in getattr(site.sequences, act):
            if s not in known:
                err(f"The {label} sequence has unknown step {s}; add it as a custom step or remove it.")


def _validate_truck_paths(site: SiteConfig, result: RulesResult) -> None:
    """R5: waiting areas and truck paths."""
    _validate_custom_steps(site, result)
    steps_known = step_names(site)
    area_ids = [a.id for a in site.truck_areas]
    for a in site.truck_areas:
        if a.id in steps_known:
            result.errors.append(Issue(f"Waiting area id {a.id} is also the name of a truck step; choose another id."))
    for dup in sorted({x for x in area_ids if area_ids.count(x) > 1}):
        result.errors.append(Issue(f"Two waiting areas share the id {dup}."))
    for act, label in PATH_LABEL.items():
        path = getattr(site.truck_paths, act)
        if not path:
            continue
        for x in path:
            if x not in steps_known and x not in area_ids:
                result.errors.append(Issue(f"The {label} truck path refers to unknown waiting area {x}."))
        steps = [x for x in path if x in steps_known]
        sequence = getattr(site.sequences, act)
        if steps != list(sequence):
            result.errors.append(Issue(f"The {label} truck path's steps ({', '.join(steps)}) do not match the "
                                       f"{label} sequence ({', '.join(sequence)})."))
    _validate_access(site, result, area_ids)


def _validate_access(site: SiteConfig, result: RulesResult, area_ids: list[str]) -> None:
    """Sampler access: declared bypasses run forward along a configured path from an area; a sampler at a
    weighbridge names an existing weighbridge and bays, and sampling is immediately followed by weighing in."""
    by_id = {e.id: e for e in site.equipment}
    for b in site.truck_bypasses:
        path = getattr(site.truck_paths, b.activity) or []
        if b.from_ not in area_ids or b.from_ not in path or b.to not in path:
            result.errors.append(Issue(f"The {b.activity} bypass from {b.from_} to {b.to} must start at a waiting area "
                                       "on the configured truck path and end at an element of it."))
        elif path.index(b.to) <= path.index(b.from_):
            result.errors.append(Issue(f"The {b.activity} bypass from {b.from_} to {b.to} must lead forward along the path."))
    located = [e for e in site.equipment if e.type == "sampler" and e.located_at is not None]
    for e in located:
        wb = by_id.get(e.located_at)
        if wb is None or wb.type != "weighbridge":
            result.errors.append(Issue(f"Sampler {e.name or e.id}: located_at {e.located_at} is not a weighbridge."))
            continue
        lanes = e.located_lanes if e.located_lanes is not None else list(range(int(wb.cap or 1)))
        if not lanes or any(not 0 <= n < int(wb.cap or 1) for n in lanes):
            result.errors.append(Issue(f"Sampler {e.name or e.id}: probe lane(s) {lanes} do not exist on {wb.name or wb.id} "
                                       f"({int(wb.cap or 1)} lane(s))."))
        for act, label in PATH_LABEL.items():
            seq = list(getattr(site.sequences, act))
            path = getattr(site.truck_paths, act) or seq
            if "sample" in path and (path.index("sample") + 1 >= len(path) or path[path.index("sample") + 1] != "weigh_in"):
                result.errors.append(Issue(f"Sampling at the weighbridge: the {label} path must weigh in directly after sampling."))
    if located and len(located) != len([e for e in site.equipment if e.type == "sampler"]):
        result.errors.append(Issue("Either every sampler is located at a weighbridge or none is."))


def _clock(hours: float) -> str:
    total = round(hours * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _validate_hours(site: SiteConfig, result: RulesResult) -> None:
    """R6: opening, admission cut-off and closing must be in order."""
    h = site.hours
    if h.open >= h.close:
        result.errors.append(Issue(f"Opening time ({_clock(h.open)}) must be before closing time ({_clock(h.close)})."))
    elif h.admission_cutoff is not None and not h.open <= h.admission_cutoff <= h.close:
        result.errors.append(Issue(f"The admission cut-off ({_clock(h.admission_cutoff)}) must be between opening "
                                   f"({_clock(h.open)}) and closing ({_clock(h.close)})."))


def _validate_demand(site: SiteConfig, result: RulesResult) -> None:
    """Demand used to generate arrivals: 24-value profiles, grade mixes for graded commodities."""
    policy = GradePolicy(site)
    names = {c.id: c.name for c in site.commodities}
    for act, label in (("unload", "unloading"), ("load", "loading"), ("weigh", "weighbridge-only")):
        d = getattr(site.demand, act)
        if d is None or not d.daily > 0:
            continue
        if d.profile is not None and len(d.profile) != 24:
            result.errors.append(Issue(f"The {label} arrival profile needs 24 hourly values (it has {len(d.profile)})."))
        if act != "unload":
            continue
        for c, share in d.mix.items():
            if share > 0 and policy.is_graded(c):
                mix = d.grade_mix.get(c)
                if not mix:
                    result.errors.append(Issue(f"Unloading trucks bring {names.get(c, c)}, which has grades, but the "
                                               "demand has no grade mix for it."))
                    continue
                for g in mix:
                    if g not in policy.grades[c]:
                        result.errors.append(Issue(f"The grade mix for {names.get(c, c)} refers to grade {g}, which "
                                                   "is not one of its grades."))


NOT_ROUTE_EQUIPMENT = ("hopper", "bin", "loadpoint", "weighbridge", "sampler", "grader")


def _validate_outages(site: SiteConfig, result: RulesResult) -> None:
    """Step 17: outages name route equipment, use clock times, end after they start, and do not overlap."""
    from ..sim.time import MS_PER_DAY, TimeFormatError, hm
    by_id = {e.id: e for e in site.equipment}
    spans: dict[str, list[tuple[int, float, int]]] = {}
    for i, o in enumerate(site.outages, start=1):
        e = by_id.get(o.equipment)
        if e is None:
            result.errors.append(Issue(f"Outage {i} refers to unknown equipment {o.equipment}."))
            continue
        name = e.name or e.id
        if e.type in NOT_ROUTE_EQUIPMENT:
            result.errors.append(Issue(f"Outage {i}: {name} is a {e.type} and cannot be scheduled as unavailable; "
                                       "only route equipment between hoppers, bins and load points (conveyors, "
                                       "elevators, ...) can be.", [e.id]))
            continue
        try:
            start = (o.day - 1) * MS_PER_DAY + hm(o.start)
            end = float("inf") if o.end is None else (o.day - 1) * MS_PER_DAY + hm(o.end)
        except TimeFormatError:
            result.errors.append(Issue(f"Outage {i} of {name}: times must be clock times like HH:MM "
                                       f"(got '{o.start}', '{o.end}')."))
            continue
        if end <= start:
            result.errors.append(Issue(f"Outage {i} of {name} must end after it starts ({o.start} to {o.end}).", [e.id]))
            continue
        spans.setdefault(e.id, []).append((start, end, i))
    for eid, items in spans.items():
        items.sort()
        for (s1, e1, i1), (s2, _, i2) in zip(items, items[1:]):
            if s2 < e1:
                result.errors.append(Issue(f"Outages {i1} and {i2} of {by_id[eid].name or eid} overlap.", [eid]))


def _validate_stock(site: SiteConfig, result: RulesResult) -> None:
    """Step 18: stock events and opening book refer to bins, carry what their kind needs, and book corrections
    carry a reason and an authority (from `authorised_by` when the site lists them)."""
    from ..sim.time import TimeFormatError, hm
    bins = {e.id for e in site.equipment if e.type == "bin"}
    commodities = {c.id for c in site.commodities}
    err = lambda msg: result.errors.append(Issue(msg))  # noqa: E731
    seen_obs: set[str] = set()
    for o in site.opening_book:
        if o.bin not in bins:
            err(f"The opening book refers to unknown bin {o.bin}.")
    if len({o.bin for o in site.opening_book}) != len(site.opening_book):
        err("The opening book lists a bin more than once.")
    measurement_ids = [ev.id for ev in site.stock_events if ev.kind == "stock_measurement"]
    for i, ev in enumerate(site.stock_events, start=1):
        label = f"Stock event {i} ({ev.kind})"
        if ev.bin not in bins:
            err(f"{label} refers to unknown bin {ev.bin}.")
        try:
            hm(ev.time)
        except TimeFormatError:
            err(f"{label}: time must be a clock time like HH:MM (got '{ev.time}').")
        if ev.kind == "process_loss":
            if ev.tonnes is None or ev.tonnes <= 0:
                err(f"{label}: the loss must be a positive number of tonnes.")
            if ev.cause is None:
                err(f"{label} needs a cause (moisture, cleaning, handling or other).")
            if ev.commodity is not None and ev.commodity not in commodities:
                err(f"{label} refers to unknown commodity {ev.commodity}.")
        elif ev.kind == "stock_measurement":
            if not ev.id:
                err(f"{label} needs an id.")
            elif ev.id in seen_obs:
                err(f"{label}: observation id {ev.id} is used twice.")
            seen_obs.add(ev.id or "")
            if ev.observed_tonnes is None or ev.observed_tonnes < 0:
                err(f"{label}: the observed quantity must be zero or more tonnes.")
        else:
            if not (ev.reason or "").strip():
                err(f"{label} needs a reason.")
            if not (ev.authority or "").strip():
                err(f"{label} needs an authority.")
            elif site.authorised_by is not None and ev.authority not in site.authorised_by:
                err(f"{label}: '{ev.authority}' is not authorised for book corrections ({', '.join(site.authorised_by)}).")
            if ev.basis == "administrative":
                if not ev.tonnes:
                    err(f"{label}: an administrative correction needs a non-zero number of tonnes.")
            elif ev.basis == "measurement":
                if ev.observation not in measurement_ids:
                    err(f"{label} refers to unknown observation {ev.observation}.")
            else:
                err(f"{label} needs a basis (administrative or measurement).")


def staffing_schedules(site: SiteConfig, scenario: str | None) -> tuple[dict, dict]:
    """(pool -> schedule windows, step -> operators) for the baseline or a staffing scenario."""
    schedules = {p.id: list(p.schedule) for p in site.operator_pools}
    operators = {r.step: r.operators for r in site.labour}
    if scenario is not None:
        sc = site.staffing_scenarios[scenario]
        schedules.update(sc.pools)
        operators.update(sc.labour)
    return schedules, operators


def _validate_staffing(site: SiteConfig, result: RulesResult) -> None:
    from ..sim.time import TimeFormatError, hm
    err = lambda msg: result.errors.append(Issue(msg))  # noqa: E731
    pools = {p.id: p for p in site.operator_pools}
    if len(pools) != len(site.operator_pools):
        err("Two operator pools share an id.")

    def check_windows(label, windows):
        for w in windows:
            try:
                if hm(w.to) <= hm(w.from_):
                    err(f"{label}: a shift must end after it starts ({w.from_}-{w.to}).")
            except TimeFormatError:
                err(f"{label}: shift times must be clock times like HH:MM ({w.from_}-{w.to}).")

    def most(windows):
        return max((w.count for w in windows), default=0)

    for p in site.operator_pools:
        check_windows(f"Operator pool {p.id}", p.schedule)
    steps = [r.step for r in site.labour]
    if len(set(steps)) != len(steps):
        err("A task step has more than one labour requirement.")
    for r in site.labour:
        p = pools.get(r.pool)
        if p is None:
            err(f"The labour for {r.step} refers to unknown operator pool {r.pool}.")
        elif r.step not in p.skills:
            err(f"Operator pool {r.pool} does not have the skill {r.step}.")
    for name, sc in site.staffing_scenarios.items():
        for pid, windows in sc.pools.items():
            if pid not in pools:
                err(f"Staffing scenario {name} refers to unknown operator pool {pid}.")
            check_windows(f"Staffing scenario {name}, pool {pid}", windows)
        tasks = {f"tip:{t.id}" for t in site.unloading_labour.tasks} if site.unloading_labour else set()
        for step in sc.labour:
            if step not in steps and step not in tasks:
                err(f"Staffing scenario {name} sets operators for {step}, which has no labour requirement.")
    for scenario in [None, *site.staffing_scenarios]:
        if any(pid not in pools for pid in (site.staffing_scenarios[scenario].pools if scenario else {})):
            continue
        schedules, operators = staffing_schedules(site, scenario)
        for r in site.labour:
            if r.pool in schedules and operators.get(r.step, r.operators) > most(schedules[r.pool]):
                err(f"{r.step} needs {operators.get(r.step, r.operators)} operator(s) from {r.pool}"
                    f"{' in scenario ' + scenario if scenario else ''}, which never has that many; the task could never start.")
    if site.unloading_labour is not None:
        _validate_unloading(site, pools, err, most)
    for step, table in site.crew_time.items():
        if step not in ("sample", "grade", "weigh_in", "weigh_out", "tip"):
            err(f"Crew-time factors are supported for sample, grade, weigh_in, weigh_out and tip, not {step}.")
        if any(not v > 0 for v in table.values()):
            err(f"Crew-time factors for {step} must be positive.")


def _validate_unloading(site: SiteConfig, pools: dict, err, most) -> None:
    """Shared unloading workers (docs/OPERATOR_STAFFING_DESIGN.md §11)."""
    ul = site.unloading_labour
    p = pools.get(ul.pool)
    if p is None:
        err(f"Unloading labour refers to unknown operator pool {ul.pool}.")
    elif "tip" not in p.skills:
        err(f"Operator pool {ul.pool} does not have the skill tip, so it cannot do the unloading tasks.")
    if any(r.step == "tip" for r in site.labour):
        err("Give the labour for unloading either as unloading tasks or as a labour requirement for tip, not both.")
    ids = [t.id for t in ul.tasks]
    if not ids or len(set(ids)) != len(ids):
        err("Unloading tasks need at least one task, each with its own id.")
    discharge = [t for t in ul.tasks if t.time == "tip"]
    if len(discharge) != 1 or not discharge[0].truck_present:
        err("Exactly one unloading task takes the hopper's tipping time (time \"tip\"), with the truck present.")
    present = [t.truck_present for t in ul.tasks]
    if present != sorted(present, reverse=True):
        err("Unloading tasks with the truck present come first; tasks after the truck has unloaded come last.")
    for t in ul.tasks:
        if t.time != "tip" and (len(t.time) != 3 or not 0 <= t.time[0] <= t.time[1] <= t.time[2]):
            err(f"Unloading task {t.id}: give its time as [min, most likely, max] minutes, in that order.")
    if p is None:
        return
    for scenario in [None, *site.staffing_scenarios]:
        if any(pid not in pools for pid in (site.staffing_scenarios[scenario].pools if scenario else {})):
            continue
        schedules, operators = staffing_schedules(site, scenario)
        for t in ul.tasks:
            need = operators.get(f"tip:{t.id}", t.operators)
            if need > most(schedules[ul.pool]):
                err(f"Unloading task {t.id} needs {need} worker(s) from {ul.pool}"
                    f"{' in scenario ' + scenario if scenario else ''}, which never has that many; it could never start.")


STEPS_OF_TYPE = {"sampler": ("sample", "pass"), "grader": ("grade",), "weighbridge": ("weigh_in", "weigh_out"),
                 "hopper": ("tip",), "loadpoint": ("load",)}


STATION_OF_STEP = {"sample": "sampler", "grade": "grader", "weigh_in": "weighbridge", "weigh_out": "weighbridge"}
ACTIVITY_NAME = {"unload": "receiving", "load": "loading", "weigh": "weigh-only"}


def _validate_station_activities(site: SiteConfig, result: RulesResult) -> None:
    """Every step of an activity's sequence needs a station that serves that activity (and direction)."""
    for act in ("unload", "load", "weigh"):
        for step in getattr(site.sequences, act):
            kind = STATION_OF_STEP.get(step)
            if kind is None:
                continue
            units = [e for e in site.equipment if e.type == kind and (e.cap or 0) > 0
                     and (e.activities is None or act in e.activities)
                     and (step != "weigh_in" or (e.moves or "both") in ("in", "both"))
                     and (step != "weigh_out" or (e.moves or "both") in ("out", "both"))]
            if not units and any(e.type == kind and e.activities is not None for e in site.equipment):
                result.errors.append(Issue(f"No {kind} serves {ACTIVITY_NAME[act]} trucks for {step}."))


CONDITIONS = ("service_done", "graded")  # P2: conditions a release rule may wait for
PLACE_STEPS = ("sample", "weigh_in", "weigh_out", "tip", "load")  # steps where the truck holds a place


def _validate_release_rules(site: SiteConfig, result: RulesResult) -> None:
    err = lambda msg: result.errors.append(Issue(msg))  # noqa: E731
    seen = set()
    for r in site.release_rules:
        label = ACTIVITY_NAME[r.activity]
        seq = list(getattr(site.sequences, r.activity))
        if (r.activity, r.step) in seen:
            err(f"There is more than one release rule for {r.step} of {label} trucks.")
        seen.add((r.activity, r.step))
        produced = {t.produces: t for t in site.background_tasks}
        for c in r.when:
            if c in produced:
                t = produced[c]
                applies = t.activities is None or r.activity in t.activities
                if not applies or t.started_by not in seq or (r.step in seq and seq.index(t.started_by) > seq.index(r.step)):
                    err(f"The release rule for {r.step} of {label} trucks waits for {c}, which background task {t.id} "
                        f"produces only after {t.started_by}: the truck would wait for ever.")
            elif c not in CONDITIONS:
                err(f"The release rule for {r.step} of {label} trucks uses unknown condition {c}; "
                    f"known conditions: {', '.join(CONDITIONS)}.")
        if r.step not in PLACE_STEPS + tuple(c.id for c in site.custom_steps):
            err(f"A release rule needs a step where the truck holds a place ({', '.join(PLACE_STEPS)}), not {r.step}.")
        if r.step not in seq:
            err(f"The release rule for {r.step} applies to a step that is not in the {label} sequence.")
            continue
        if "graded" in r.when:
            if "grade" not in seq:
                err(f"The release rule for {r.step} of {label} trucks waits for grading, but the {label} sequence "
                    "has no grading.")
            elif "sample" not in seq or seq.index(r.step) < seq.index("sample"):
                err(f"The release rule for {r.step} of {label} trucks waits for grading, which starts only after "
                    f"sampling, but {r.step} comes before sampling: the truck would wait for ever.")


def _validate_task_phases(site: SiteConfig, result: RulesResult) -> None:
    """P4 for station steps (tip phases are read as unloading_labour by the schema and validated there)."""
    from ..sim.time import TimeFormatError, hm
    err = lambda msg: result.errors.append(Issue(msg))  # noqa: E731
    pools = {p.id: p for p in site.operator_pools}
    steps = [p.step for p in site.task_phases]
    for s in sorted({s for s in steps if steps.count(s) > 1}):
        err(f"Worker phases for {s} are given more than once.")
    located = any(e.type == "sampler" and e.located_at for e in site.equipment)
    for sp in site.task_phases:
        label = f"Worker phases for {sp.step}"
        if sp.step not in ("sample", "weigh_in", "weigh_out", "load") and sp.step not in {c.id for c in site.custom_steps}:
            err(f"{label}: {sp.step} is not a station step (sample, weigh_in, weigh_out, tip or a custom step).")
            continue
        if sp.step == "load":
            err(f"{label}: worker phases are not supported for load yet; use a labour requirement.")
            continue
        if any(r.step == sp.step for r in site.labour):
            err(f"{label}: give the workers for {sp.step} either as phases or as a labour requirement, not both.")
        if located and sp.step in ("sample", "weigh_in"):
            err(f"{label} are not supported with samplers located at the weighbridge.")
        if sum(1 for p in sp.phases if p.time == "service") != 1:
            err(f'{label}: exactly one phase takes the station\'s own time (time "service").')
        for p in sp.phases:
            if not p.truck_present:
                err(f"{label}: every phase of a station step has the truck present ({p.id}).")
            if p.time != "service" and (len(p.time) != 3 or not 0 <= p.time[0] <= p.time[1] <= p.time[2]):
                err(f"{label}, phase {p.id}: give its time as [min, most likely, max] minutes, in that order.")
        pool = pools.get(sp.pool)
        if pool is None:
            err(f"{label} refer to unknown operator pool {sp.pool}.")
            continue
        if sp.step not in pool.skills:
            err(f"Operator pool {sp.pool} does not have the skill {sp.step}.")
        try:
            most = max((w.count for w in pool.schedule if hm(w.to) > hm(w.from_)), default=0)
        except TimeFormatError:
            continue
        for p in sp.phases:
            if p.workers > most:
                err(f"{label}, phase {p.id} needs {p.workers} worker(s) from {sp.pool}, which never has that many.")


def _validate_background_tasks(site: SiteConfig, result: RulesResult) -> None:
    from ..sim.time import TimeFormatError, hm
    err = lambda msg: result.errors.append(Issue(msg))  # noqa: E731
    by_id = {e.id: e for e in site.equipment}
    pools = {p.id: p for p in site.operator_pools}
    ids = [t.id for t in site.background_tasks]
    if len(set(ids)) != len(ids):
        err("Two background tasks share an id.")
    seen: set[str] = set()
    for t in site.background_tasks:
        label = f"Background task {t.id}"
        if t.produces in CONDITIONS:
            err(f"{label}: the condition name {t.produces} is reserved; choose another name.")
        if t.produces in seen:
            err(f"There is more than one background task produces {t.produces}; each condition needs one producer.")
        seen.add(t.produces)
        acts = [a for a in ("unload", "load", "weigh") if (t.activities is None or a in t.activities)
                and t.started_by in getattr(site.sequences, a)]
        if not acts:
            err(f"{label} starts after {t.started_by}, but no truck process has {t.started_by}.")
        for eq in t.equipment:
            e = by_id.get(eq)
            if e is None:
                err(f"{label} uses unknown equipment {eq}.")
            elif e.type not in ("sampler", "grader", "weighbridge") or not (e.cap or 0) >= 1:
                err(f"{label} can only use a station with lanes (sampler, grader or weighbridge), not {eq}.")
        if len(t.time) != 3 or not 0 <= t.time[0] <= t.time[1] <= t.time[2]:
            err(f"{label}: give its time as [min, most likely, max] minutes, in that order.")
        if t.pool is not None:
            p = pools.get(t.pool)
            if p is None:
                err(f"{label} refers to unknown operator pool {t.pool}.")
                continue
            if t.id not in p.skills:
                err(f"Operator pool {t.pool} does not have the skill {t.id}, so it cannot do background task {t.id}.")
            for scenario in [None, *site.staffing_scenarios]:
                windows = (site.staffing_scenarios[scenario].pools.get(t.pool) if scenario else None) or p.schedule
                try:
                    most = max((w.count for w in windows if hm(w.to) > hm(w.from_)), default=0)
                except TimeFormatError:
                    continue
                if t.workers > most:
                    err(f"{label} needs {t.workers} worker(s) from {t.pool}"
                        f"{' in scenario ' + scenario if scenario else ''}, which never has that many; it could never start.")


def _validate_systems(site: SiteConfig, result: RulesResult) -> None:
    ids = [s.id for s in site.systems]
    if len(set(ids)) != len(ids):
        result.errors.append(Issue("Two systems share the id " + next(i for i in ids if ids.count(i) > 1) + "."))
    known = {e.id for e in site.equipment}
    owner: dict[str, str] = {}
    for s in site.systems:
        for eq in s.equipment:
            if eq not in known:
                result.errors.append(Issue(f"System {s.name} lists unknown equipment {eq}."))
            elif eq in owner and owner[eq] != s.id:
                result.errors.append(Issue(f"{eq} is in two systems ({owner[eq]} and {s.id}); equipment shared by "
                                           "systems belongs to none of them."))
            owner.setdefault(eq, s.id)


def _validate_distributions(site: SiteConfig, result: RulesResult) -> None:
    from ..sim.distributions import problems
    for e in site.equipment:
        for step, d in (e.distributions or {}).items():
            label = e.name or e.id
            if step not in STEPS_OF_TYPE.get(e.type, ()):
                result.errors.append(Issue(f"{label} does not do {step}, so it cannot have a time distribution for it."))
            for msg in problems(d.model_dump()):
                result.errors.append(Issue(f"{label}, {step} time: {msg}."))


def validate_rules(site: SiteConfig) -> RulesResult:
    result = RulesResult()
    names = {c.id: c.name for c in site.commodities}
    equipment_names = {e.id: (e.name or e.id) for e in site.equipment}
    policy = GradePolicy(site)
    _validate_hours(site, result)
    _validate_demand(site, result)
    _validate_grades(site, result)
    _validate_truck_paths(site, result)
    _validate_outages(site, result)
    _validate_stock(site, result)
    _validate_staffing(site, result)
    _validate_distributions(site, result)
    _validate_station_activities(site, result)
    _validate_systems(site, result)
    _validate_release_rules(site, result)
    _validate_background_tasks(site, result)
    _validate_task_phases(site, result)

    if site.changeovers is not None:
        for rule in site.changeovers.rules:
            for key in (rule.from_, rule.to):
                commodity, _, grade = key.partition(":")
                if key != "*" and commodity not in names:
                    result.errors.append(Issue(f"A changeover rule refers to unknown commodity {commodity}."))
                elif grade and grade not in policy.grades.get(commodity, []):
                    result.errors.append(Issue(f"A changeover rule refers to unknown grade {grade} of "
                                               f"{names[commodity]}."))
            if rule.equipment != "*":
                for ref in rule.equipment:
                    if ref not in equipment_names and ref not in SEGMENT_TYPES:
                        result.errors.append(Issue(f"A changeover rule refers to unknown equipment {ref}."))

    matrix = ChangeoverMatrix.from_site(site)
    carried = segment_commodities(site)
    shared = any(len(cs) > 1 for cs in carried.values())
    if matrix.prototype_format and shared:
        result.warnings.append(Issue(
            "Changeover times come from each conveyor's and elevator's single changeover value (prototype format) "
            "and apply to any change of commodity. Commodity-pair changeover rules are not configured."))
    for seg, commodities in carried.items():
        for a in commodities:
            for b in commodities:
                if a == b:
                    continue
                pair = f"{names.get(a, a)} → {names.get(b, b)} on {equipment_names[seg]}"
                try:
                    minutes = matrix.required_minutes(seg, GradedCommodity(a, UNGRADED), GradedCommodity(b, UNGRADED))
                except AmbiguousRule as e:
                    values = " and ".join(_minutes(r.minutes) for r in e.rules)
                    result.errors.append(Issue(f"Changeover rules for {pair} disagree ({values} min).", [seg]))
                    continue
                if minutes is None:
                    result.errors.append(Issue(f"No changeover rule for {pair}.", [seg]))
    return result
