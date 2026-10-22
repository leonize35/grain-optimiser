"""Validation of the confirmed operating rules (R1–R7) that go beyond the prototype.

`config.validation.validate` reproduces the prototype exactly and must not change. Checks for the new rules live
here; the engine refuses to run a site with errors from either. Messages are in manager language and name the
equipment involved.

Currently checked:
- R3 changeovers: unknown commodities/equipment in rules; for every pair of commodities that can meet on the
  same conveyor or elevator (from the configured routes), a rule or a default must exist, and equally specific
  rules must agree. Sites in the prototype format get a warning saying where changeover times come from.
"""
from dataclasses import dataclass, field

from ..domain.changeover import SEGMENT_TYPES, AmbiguousRule, ChangeoverMatrix
from ..domain.storage import GradedCommodity
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


def validate_rules(site: SiteConfig) -> RulesResult:
    result = RulesResult()
    names = {c.id: c.name for c in site.commodities}
    equipment_names = {e.id: (e.name or e.id) for e in site.equipment}

    if site.changeovers is not None:
        for rule in site.changeovers.rules:
            for key in (rule.from_, rule.to):
                commodity = key.split(":", 1)[0]
                if key != "*" and commodity not in names:
                    result.errors.append(Issue(f"A changeover rule refers to unknown commodity {commodity}."))
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
