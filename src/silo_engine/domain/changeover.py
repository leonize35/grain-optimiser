"""Commodity-pair changeover matrix (R3 in docs/DOMAIN_DECISIONS.md).

`required_minutes(equipment, last grain, next grain)`:
- the same grain again: 0 (no changeover);
- a different commodity: the most specific matching rule, else the site default, else None (no rule: a
  configuration error, caught by `config.rules_validation` before any run);
- the same commodity, different grade: only a rule naming a grade on at least one side applies; otherwise 0.
  The site default covers commodity changes only.

Specificity: equipment id (3) > equipment type (2) > '*' (1); then grain keys, 'commodity:grade' (2) >
'commodity' (1) > '*' (0) on each side. Equally specific matching rules that disagree raise `AmbiguousRule`.

Prototype format (no `changeovers` section): each conveyor/elevator's single `changeover` value becomes a rule
'* -> *' for that equipment id, applied to any change of commodity, as the prototype does.
"""
from dataclasses import dataclass
from decimal import Decimal

from ..config.schema import SiteConfig
from .storage import GradedCommodity

SEGMENT_TYPES = ("conveyor", "elevator")


@dataclass(frozen=True)
class Rule:
    from_key: str
    to_key: str
    minutes: Decimal
    equipment: tuple[str, ...] | None  # None means '*'


class AmbiguousRule(ValueError):
    def __init__(self, rules: list[Rule]):
        self.rules = rules
        super().__init__("equally specific changeover rules disagree")


def _key_spec(key: str, grain: GradedCommodity) -> int | None:
    """Specificity of `key` if it matches `grain`, else None."""
    if key == "*":
        return 0
    if ":" in key:
        return 2 if key == f"{grain.commodity}:{grain.grade}" else None
    return 1 if key == grain.commodity else None


class ChangeoverMatrix:
    def __init__(self, rules: list[Rule], default_minutes: Decimal | None, equipment_types: dict[str, str],
                 prototype_format: bool):
        self.rules = rules
        self.default_minutes = default_minutes
        self.equipment_types = equipment_types
        self.prototype_format = prototype_format

    @classmethod
    def from_site(cls, site: SiteConfig) -> "ChangeoverMatrix":
        types = {e.id: e.type for e in site.equipment}
        if site.changeovers is None:
            rules = [Rule("*", "*", Decimal(str(e.changeover)), (e.id,))
                     for e in site.equipment if e.type in SEGMENT_TYPES and e.changeover is not None]
            return cls(rules, None, types, prototype_format=True)
        c = site.changeovers
        rules = [Rule(r.from_, r.to, Decimal(str(r.minutes)), None if r.equipment == "*" else tuple(r.equipment))
                 for r in c.rules]
        default = None if c.default_minutes is None else Decimal(str(c.default_minutes))
        return cls(rules, default, types, prototype_format=False)

    def _equipment_spec(self, rule: Rule, equipment_id: str) -> int | None:
        if rule.equipment is None:
            return 1
        if equipment_id in rule.equipment:
            return 3
        if self.equipment_types.get(equipment_id) in rule.equipment:
            return 2
        return None

    def required_minutes(self, equipment_id: str, last: GradedCommodity, nxt: GradedCommodity) -> Decimal | None:
        if last == nxt:
            return Decimal(0)
        grade_only = last.commodity == nxt.commodity
        ranked: list[tuple[tuple[int, int], Rule]] = []
        for rule in self.rules:
            eq = self._equipment_spec(rule, equipment_id)
            fs, ts = _key_spec(rule.from_key, last), _key_spec(rule.to_key, nxt)
            if eq is None or fs is None or ts is None:
                continue
            if grade_only and ":" not in rule.from_key and ":" not in rule.to_key:
                continue
            ranked.append(((eq, fs + ts), rule))
        if not ranked:
            return Decimal(0) if grade_only else self.default_minutes
        best = max(rank for rank, _ in ranked)
        winners = [r for rank, r in ranked if rank == best]
        if len({r.minutes for r in winners}) > 1:
            raise AmbiguousRule(winners)
        return winners[0].minutes
