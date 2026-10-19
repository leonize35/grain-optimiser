"""Grain route enumeration over the typed directed equipment graph (port of prototype `buildRoutes`)."""
from dataclasses import dataclass

from .jscompat import locale_sort_key
from .schema import Equipment, SiteConfig

# Paths enumerated per hopper or bin before the search stops (same limit as the prototype).
ROUTE_LIMIT = 400


def is_transfer(equipment_type: str) -> bool:
    """Conveyors and elevators carry grain between a source and a destination."""
    return equipment_type in ("conveyor", "elevator")


@dataclass
class RouteTable:
    intake: dict[str, list[list[str]]]  # hopper id -> paths [hopper, ..., bin]
    load: dict[str, list[list[str]]]  # bin id -> paths [bin, ..., load point]
    out: dict[str, list[str]]  # equipment id -> downstream ids, in configuration order
    by_id: dict[str, Equipment]


def _enumerate(start: str, target_type: str, out: dict[str, list[str]], by_id: dict[str, Equipment]) -> list[list[str]]:
    # Depth-first with an explicit stack, popped from the end, exactly as the prototype does. The order of
    # discovery does not matter for the result because paths are sorted afterwards, but the ROUTE_LIMIT cut-off
    # does, so the traversal order is kept identical.
    paths: list[list[str]] = []
    stack: list[tuple[str, list[str]]] = [(start, [start])]
    while stack and len(paths) < ROUTE_LIMIT:
        node, path = stack.pop()
        for nxt in out[node]:
            if nxt in path:
                continue
            t = by_id[nxt].type
            if t == target_type:
                paths.append(path + [nxt])
            elif is_transfer(t):
                stack.append((nxt, path + [nxt]))
    # Shortest first; ties broken by the comma-joined ids in browser locale order.
    paths.sort(key=lambda p: (len(p), locale_sort_key(",".join(p))))
    return paths


def build_routes(cfg: SiteConfig) -> RouteTable:
    by_id = {e.id: e for e in cfg.equipment}
    out: dict[str, list[str]] = {}
    for e in cfg.equipment:
        out[e.id] = []
    for a, b in cfg.edges:
        if a in out and b in by_id:
            out[a].append(b)
    intake = {h.id: _enumerate(h.id, "bin", out, by_id) for h in cfg.equipment if h.type == "hopper"}
    load = {b.id: _enumerate(b.id, "loadpoint", out, by_id) for b in cfg.equipment if b.type == "bin"}
    return RouteTable(intake=intake, load=load, out=out, by_id=by_id)
