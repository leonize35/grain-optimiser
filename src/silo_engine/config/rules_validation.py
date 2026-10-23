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


def _validate_truck_paths(site: SiteConfig, result: RulesResult) -> None:
    """R5: waiting areas and truck paths."""
    area_ids = [a.id for a in site.truck_areas]
    for a in site.truck_areas:
        if a.id in TRUCK_STEPS:
            result.errors.append(Issue(f"Waiting area id {a.id} is also the name of a truck step; choose another id."))
    for dup in sorted({x for x in area_ids if area_ids.count(x) > 1}):
        result.errors.append(Issue(f"Two waiting areas share the id {dup}."))
    for act, label in PATH_LABEL.items():
        path = getattr(site.truck_paths, act)
        if not path:
            continue
        for x in path:
            if x not in TRUCK_STEPS and x not in area_ids:
                result.errors.append(Issue(f"The {label} truck path refers to unknown waiting area {x}."))
        steps = [x for x in path if x in TRUCK_STEPS]
        sequence = getattr(site.sequences, act)
        if steps != list(sequence):
            result.errors.append(Issue(f"The {label} truck path's steps ({', '.join(steps)}) do not match the "
                                       f"{label} sequence ({', '.join(sequence)})."))


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


def validate_rules(site: SiteConfig) -> RulesResult:
    result = RulesResult()
    names = {c.id: c.name for c in site.commodities}
    equipment_names = {e.id: (e.name or e.id) for e in site.equipment}
    policy = GradePolicy(site)
    _validate_hours(site, result)
    _validate_grades(site, result)
    _validate_truck_paths(site, result)

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
