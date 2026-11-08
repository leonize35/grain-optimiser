"""Route planner (docs/ENGINE_INTERFACES.md §2): physically possible routes, in preference order.

Routes come only from the configured equipment graph (`config.routes.build_routes`). The planner removes routes
that can never work (the destination bin is not assigned to this grain); whether a route is free right now is the
reservation ledger's job.

Preference order for intake (same as the prototype's default transfer rule): bins already holding this grain
first, then the rest; within each, the route table's order (shortest first, then identifiers).
"""
from ..config.routes import RouteTable
from ..domain.storage import GradedCommodity, StorageBin


class RoutePlanner:
    def __init__(self, routes: RouteTable, bins: dict[str, StorageBin]):
        self.routes = routes
        self.bins = bins

    def _cleans(self, path: list[str]) -> bool:
        return any(self.routes.by_id[s].type == "cleaner" for s in path[1:-1])

    def _dries(self, path: list[str]) -> bool:
        return any(self.routes.by_id[s].type == "grain_dryer" for s in path[1:-1])

    def _fits(self, path: list[str], grain: GradedCommodity, dirty: bool, wet: bool | None) -> bool:
        """G-D4: a dirty lot only through a cleaner, a clean lot only without one (the bypass). Drying: never through
        a dryer on intake; with moisture tracked for the commodity (wet not None), wet lots only to wet holding
        bins and dry lots only to other bins."""
        return (grain in self.bins[path[-1]].accepts and self._cleans(path) == dirty and not self._dries(path)
                and (wet is None or bool(self.routes.by_id[path[-1]].wet_holding) == wet))

    def intake_candidates(self, pit_id: str, grain: GradedCommodity, dirty: bool = False,
                          wet: bool | None = None) -> list[list[str]]:
        """Routes to bins that accept the grain (see `_fits`); bins already holding it first."""
        possible = [p for p in self.routes.intake.get(pit_id, []) if self._fits(p, grain, dirty, wet)]
        same = [p for p in possible if self.bins[p[-1]].identity == grain]
        return same + [p for p in possible if self.bins[p[-1]].identity != grain]

    def move_candidates(self, from_bin: str, to_bin: str, drying: bool = False) -> list[list[str]]:
        """Planned moves: routes from one bin to another (or back to itself) without a cleaner; through a dryer
        exactly when drying."""
        return [p for p in self.routes.moves.get(from_bin, []) if p[-1] == to_bin and not self._cleans(p)
                and any(self.routes.by_id[s].type == "grain_dryer" for s in p[1:-1]) == drying]

    def has_intake_route(self, pit_id: str, grain: GradedCommodity, dirty: bool = False,
                         wet: bool | None = None) -> bool:
        return any(self._fits(p, grain, dirty, wet) for p in self.routes.intake.get(pit_id, []))

    def load_candidates(self, commodity: str, grade: str | None) -> list[list[str]]:
        """Routes bin -> ... -> load point from bins whose contents are this commodity (and grade, when the order
        names one), in configuration and route-table order. Stock and equipment availability are the ledger's job."""
        out = []
        for bin_id, paths in self.routes.load.items():
            contents = self.bins[bin_id].identity
            if contents is None or contents.commodity != commodity or (grade is not None and contents.grade != grade):
                continue
            out.extend(p for p in paths if not self._cleans(p) and not self._dries(p))  # nor a cleaner or dryer
        return out

    def can_load(self, commodity: str) -> bool:
        """Static check: some bin assigned to this commodity has a route to a load point."""
        return any(paths and any(g.commodity == commodity for g in self.bins[b].accepts)
                   for b, paths in self.routes.load.items())
