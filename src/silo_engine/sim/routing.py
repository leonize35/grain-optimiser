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

    def intake_candidates(self, pit_id: str, grain: GradedCommodity) -> list[list[str]]:
        possible = [p for p in self.routes.intake.get(pit_id, []) if grain in self.bins[p[-1]].accepts]
        same = [p for p in possible if self.bins[p[-1]].identity == grain]
        return same + [p for p in possible if self.bins[p[-1]].identity != grain]

    def has_intake_route(self, pit_id: str, grain: GradedCommodity) -> bool:
        return any(grain in self.bins[p[-1]].accepts for p in self.routes.intake.get(pit_id, []))

    def load_candidates(self, commodity: str, grade: str | None) -> list[list[str]]:
        """Routes bin -> ... -> load point from bins whose contents are this commodity (and grade, when the order
        names one), in configuration and route-table order. Stock and equipment availability are the ledger's job."""
        out = []
        for bin_id, paths in self.routes.load.items():
            contents = self.bins[bin_id].identity
            if contents is None or contents.commodity != commodity or (grade is not None and contents.grade != grade):
                continue
            out.extend(paths)
        return out

    def can_load(self, commodity: str) -> bool:
        """Static check: some bin assigned to this commodity has a route to a load point."""
        return any(paths and any(g.commodity == commodity for g in self.bins[b].accepts)
                   for b, paths in self.routes.load.items())
