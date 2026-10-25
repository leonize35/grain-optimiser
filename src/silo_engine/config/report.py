"""One pre-run report for a site configuration (docs/PLATFORM_GAP_ANALYSIS.md step 1, gap G9).

It merges the structural validator (`validation.validate`, prototype parity: wording unchanged) and the operating
rules validator (`rules_validation.validate_rules`), and adds platform checks the two did not make. Every finding has
a code, a severity (error blocks a run; warning needs attention; note explains), its source, a manager-language
message, the location (ids of equipment, areas, pools, commodities or fields) and, where useful, how to fix it.

Codes: messages of the two existing validators carry `structure.legacy` / `rules.legacy` (and `structure.note`) until
they are given individual codes; platform checks carry their own codes. The engine's own refusal to run is unchanged.
"""
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .rules_validation import validate_rules
from .schema import SiteConfig
from .validation import validate

STATION_OF_STEP = {"sample": "sampler", "grade": "grader", "weigh_in": "weighbridge", "weigh_out": "weighbridge"}
ACTIVITIES = ("unload", "load", "weigh")


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # error, warning, note
    source: str  # structure, rules, platform
    message: str
    location: list[str] = field(default_factory=list)
    fix: str | None = None


@dataclass
class PrerunReport:
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    def as_dict(self) -> dict:
        count = lambda s: sum(1 for f in self.findings if f.severity == s)  # noqa: E731
        return {"ok": self.ok, "errors": count("error"), "warnings": count("warning"), "notes": count("note"),
                "findings": [asdict(f) for f in self.findings]}


def prerun_report(site: SiteConfig) -> PrerunReport:
    out: list[Finding] = []
    s = validate(site)
    for sev, issues in (("error", s.errors), ("warning", s.warnings), ("note", s.info)):
        code = "structure.note" if sev == "note" else "structure.legacy"
        out += [Finding(code, sev, "structure", i.msg, list(i.ids)) for i in issues]
    r = validate_rules(site)
    for sev, issues in (("error", r.errors), ("warning", r.warnings)):
        out += [Finding("rules.legacy", sev, "rules", i.msg, list(getattr(i, "ids", []) or [])) for i in issues]
    for check in (_hold_without_path, _hours_representable, _storage_for_a_day, _workers_in_overtime,
                  _unused_places_and_stations):
        out += check(site)
    return PrerunReport(out)


def _clock(hours: float) -> str:
    total = round(hours * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _hold_without_path(site: SiteConfig) -> list[Finding]:
    """A grading wait directly after a station (e.g. weigh_in) holds that station only with an explicit truck path;
    without one the engine puts an unlimited waiting area before every step and the truck moves off."""
    out = []
    for act in ACTIVITIES:
        seq = list(getattr(site.sequences, act))
        if getattr(site.truck_paths, act):
            continue
        for i, step in enumerate(seq):
            if step == "grade" and i > 0 and seq[i - 1] != "sample":
                out.append(Finding(
                    "process.hold_without_path", "warning", "platform",
                    f"Trucks wait for their grading result after {seq[i - 1]}, but without a truck path they move off "
                    f"the {STATION_OF_STEP.get(seq[i - 1], seq[i - 1])} while waiting.",
                    [act, seq[i - 1]],
                    f"Give the {act} truck path explicitly with no waiting area between {seq[i - 1]} and grade, so "
                    f"the truck holds its place until the result is available."))
    return out


def _hours_representable(site: SiteConfig) -> list[Finding]:
    out = []
    h = site.hours
    for name in ("open", "close", "admission_cutoff", "overtime"):
        v = getattr(h, name)
        if v is None:
            continue
        ms = Decimal(str(v)) * 60 * 60000
        if ms != ms.to_integral_value():
            out.append(Finding(
                "hours.not_representable", "error", "platform",
                f"The {name.replace('_', ' ')} ({v}) is not a whole number of milliseconds, so the run would fail.",
                ["hours", name],
                f"It is about {_clock(v)}, which decimal hours cannot express exactly. Use a time that can be written "
                f"exactly in decimal hours, e.g. a multiple of 6 minutes (7.3 = 07:18)."))
    return out


def _storage_for_a_day(site: SiteConfig) -> list[Finding]:
    d = site.demand.unload
    if d is None or not d.daily > 0 or not d.payload or not d.mix:
        return []
    mean_t = sum(d.payload[:3]) / 3
    total = sum(v for v in d.mix.values() if v > 0)
    names = {c.id: c.name for c in site.commodities}
    out = []
    for c, share in d.mix.items():
        if share <= 0:
            continue
        tonnes = d.daily * mean_t * share / total
        free = sum((e.cap_t or 0) - (e.inv or 0) for e in site.equipment
                   if e.type == "bin" and c in (e.commodities or []))
        if tonnes > free:
            out.append(Finding(
                "storage.daily_receipts_exceed_space", "warning", "platform",
                f"Expected receipts of {names.get(c, c)} in one day ({tonnes:g} t) exceed the free space in bins that "
                f"may hold it ({free:g} t). Trucks may wait for bin space unless grain is loaded out.",
                [c], "Check the demand, the bin capacities and commodities, or the opening stock."))
    return out


def _workers_in_overtime(site: SiteConfig) -> list[Finding]:
    """Services may start until closing + overtime; a pool the process needs may have no shift then."""
    steps = {s for act in ACTIVITIES for s in getattr(site.sequences, act)}
    needed = {r.pool for r in site.labour if r.step in steps}
    if site.unloading_labour is not None and "tip" in steps:
        needed.add(site.unloading_labour.pool)
    stop = site.hours.close + site.hours.overtime
    out = []
    for p in site.operator_pools:
        if p.id not in needed or not p.schedule:
            continue
        last = max(int(w.to[:2]) * 60 + int(w.to[3:5]) for w in p.schedule if w.count > 0) / 60 \
            if any(w.count > 0 for w in p.schedule) else 0
        if last < stop:
            out.append(Finding(
                "labour.no_workers_in_overtime", "warning", "platform",
                f"Services may start until {_clock(stop)}, but operator pool {p.id} has no shift after {_clock(last)}. "
                f"Admitted trucks needing these workers may not clear.",
                [p.id], "Add an overtime shift to the pool (or a staffing scenario), or shorten the overtime."))
    return out


def _unused_places_and_stations(site: SiteConfig) -> list[Finding]:
    out = []
    used_areas = {x for act in ACTIVITIES for x in (getattr(site.truck_paths, act) or [])}
    for a in site.truck_areas:
        if a.id not in used_areas:
            out.append(Finding("places.unused_area", "warning", "platform",
                               f"Waiting area {a.name or a.id} is on no truck path, so no truck will use it.", [a.id],
                               "Add it to a truck path or remove it."))
    for e in site.equipment:
        if e.type not in STATION_OF_STEP.values():
            continue
        moves = e.moves or "both"
        served = False
        for act in ACTIVITIES:
            if e.activities is not None and act not in e.activities:
                continue
            for step in getattr(site.sequences, act):
                if STATION_OF_STEP.get(step) != e.type:
                    continue
                if (step == "weigh_in" and moves == "out") or (step == "weigh_out" and moves == "in"):
                    continue
                served = True
        if not served:
            out.append(Finding("stations.unused", "warning", "platform",
                               f"{e.name or e.id} serves no step of any truck process, so no truck will use it.",
                               [e.id], "Check its activities and direction, or the truck processes."))
    return out
