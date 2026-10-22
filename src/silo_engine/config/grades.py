"""How a site's configuration turns into commodity-and-grade identities (R4).

- Ungraded commodity (no `grades`): its grain carries the placeholder grade ``*`` everywhere.
- Graded commodity, segregation on (default): grain carries its real grade; bins accept the grades listed in
  their `accepts` entry for that commodity; pits and bins combine grades only through `grade_mixing` rules.
- Graded commodity with ``grade_segregation: "none"``: grades are recorded on trucks for reporting, but grain is
  handled as ``*`` (no restriction on pits or bins).
"""
from ..domain.storage import GradedCommodity, MixingRules
from .schema import Equipment, SiteConfig

UNGRADED = "*"


class GradePolicy:
    def __init__(self, site: SiteConfig):
        self.site = site
        self.grades = {c.id: list(c.grades) for c in site.commodities if c.grades}

    def is_graded(self, commodity: str) -> bool:
        return commodity in self.grades

    def segregated(self, commodity: str) -> bool:
        return self.is_graded(commodity) and self.site.grade_segregation != "none"

    def grain(self, commodity: str, grade: str | None) -> GradedCommodity:
        return GradedCommodity(commodity, grade if self.segregated(commodity) and grade is not None else UNGRADED)

    def bin_accepts(self, b: Equipment) -> frozenset[GradedCommodity]:
        listed = {a.commodity: a.grades for a in (b.accepts or [])}
        out = set()
        for c in b.commodities or []:
            if self.segregated(c):
                out |= {GradedCommodity(c, g) for g in listed.get(c, [])}
            else:
                out.add(GradedCommodity(c, UNGRADED))
        return frozenset(out)

    def mixing(self) -> MixingRules:
        return MixingRules([(r.commodity, set(r.grades), r.result) for r in self.site.grade_mixing
                            if self.segregated(r.commodity)])
