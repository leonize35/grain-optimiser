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
