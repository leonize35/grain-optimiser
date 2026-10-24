"""Structural comparison of silo configurations (Paper 2 evidence, EV-T1).

Computed from the configuration only, using the engine's own route enumeration (`config.routes.build_routes`), so
the figures describe exactly what the engine will consider. Definitions:

- intake system: a connected group of hoppers, transfer equipment and bins joined by intake connections
  (hopper/transfer -> transfer/bin). Load-out connections (from bins, to load points) are not part of it.
- interconnect: transfer equipment whose removal splits an intake system into more systems while every hopper keeps
  at least one route to a bin (equipment whose removal cuts a hopper off is a bottleneck, not an interconnect).
- alternative intermediate route: a hopper-bin pair reachable through more than one distinct sequence of
  intermediate equipment (routes that differ only in the destination bin do not count).
- shared equipment: transfer equipment on intake routes of more than one hopper; equipment used by both intake and
  load-out routes; equipment allowing more than one concurrent feed.
- grain compatibility: per grain identity (commodity, or commodity:grade for graded commodities), the hoppers that
  accept it, the bins that accept it, and the bins reachable from each accepting hopper.
"""
from collections import defaultdict

from silo_engine.config.grades import GradePolicy
from silo_engine.config.routes import build_routes, is_transfer
from silo_engine.config.schema import SiteConfig, config_hash
from silo_engine.domain.storage import GradedCommodity


def _components(nodes: set[str], edges: list[tuple[str, str]]) -> list[set[str]]:
    adj = defaultdict(set)
    for a, b in edges:
        if a in nodes and b in nodes:
            adj[a].add(b)
            adj[b].add(a)
    seen, comps = set(), []
    for n in sorted(nodes):
        if n in seen:
            continue
        comp, stack = set(), [n]
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x)
            stack.extend(adj[x] - comp)
        seen |= comp
        comps.append(comp)
    return comps


def structure(site: SiteConfig) -> dict:
    eq = {e.id: e for e in site.equipment}
    routes = build_routes(site)
    types = defaultdict(int)
    for e in site.equipment:
        types[e.type] += 1
    flow_nodes = {e.id for e in site.equipment if e.type == "hopper" or e.type == "bin" or is_transfer(e.type)}
    intake_edges = [(a, b) for a, b in site.edges if a in eq and b in eq
                    and (eq[a].type == "hopper" or is_transfer(eq[a].type)) and (is_transfer(eq[b].type) or eq[b].type == "bin")]
    # Only equipment on some intake route belongs to an intake system (reclaim conveyors do not).
    on_intake = {x for ps in routes.intake.values() for p in ps for x in p}
    systems = [c for c in _components(flow_nodes & on_intake, intake_edges) if any(eq[x].type == "hopper" for x in c)]

    def systems_without(x: str) -> list[set[str]]:
        rest = (flow_nodes & on_intake) - {x}
        edges = [(a, b) for a, b in intake_edges if x not in (a, b)]
        return [c for c in _components(rest, edges)
                if any(eq[n].type == "hopper" for n in c) and any(eq[n].type == "bin" for n in c)]

    def all_hoppers_served_without(xs: set[str]) -> bool:
        return all(any(not (set(p) & xs) for p in ps) for ps in routes.intake.values() if ps)

    interconnects = sorted(x for x in on_intake if is_transfer(eq[x].type)
                           and len(systems_without(x)) > len(systems) and all_hoppers_served_without({x}))
    rest = (flow_nodes & on_intake) - set(interconnects)
    separated = [c for c in _components(rest, [(a, b) for a, b in intake_edges if a in rest and b in rest])
                 if any(eq[n].type == "hopper" for n in c)]
    users = defaultdict(set)
    alt_pairs, pairs = [], 0
    for h, ps in routes.intake.items():
        by_bin = defaultdict(set)
        for p in ps:
            by_bin[p[-1]].add(tuple(p[1:-1]))
            for x in p[1:-1]:
                users[x].add(h)
        pairs += len(by_bin)
        alt_pairs += [f"{h}->{b}" for b, mids in sorted(by_bin.items()) if len(mids) > 1]
    intake_segments = {x for ps in routes.intake.values() for p in ps for x in p[1:-1]}
    load_segments = {x for ps in routes.load.values() for p in ps for x in p[1:-1]}

    policy = GradePolicy(site)
    identities = []
    for c in site.commodities:
        grades = policy.grades.get(c.id) if policy.is_graded(c.id) and policy.segregated(c.id) else None
        identities += [(c.id, g) for g in grades] if grades else [(c.id, None)]
    compat = {}
    for commodity, grade in identities:
        grain = policy.grain(commodity, grade) if grade is not None else GradedCommodity(commodity, "*")
        bins = sorted(e.id for e in site.equipment if e.type == "bin" and _accepts(policy, e, grain))
        hoppers = sorted(e.id for e in site.equipment if e.type == "hopper" and commodity in (e.commodities or []))
        reach = {h: sorted({p[-1] for p in routes.intake.get(h, []) if p[-1] in bins}) for h in hoppers}
        compat[f"{commodity}:{grade}" if grade else commodity] = {
            "bins": bins, "hoppers": hoppers, "reachable_bins_per_hopper": reach,
            "min_reachable_bins": min((len(v) for v in reach.values()), default=0)}
    return {
        "id": site.id, "config_hash": config_hash(site),
        "equipment_total": len(site.equipment), "equipment_by_type": dict(sorted(types.items())),
        "connections": len(site.edges),
        "intake_systems": len(systems), "intake_system_hoppers": [sorted(x for x in c if eq[x].type == "hopper") for c in systems],
        "interconnects": interconnects,
        "intake_systems_without_interconnects": len(separated),
        "intake_routes": sum(len(v) for v in routes.intake.values()),
        "load_routes": sum(len(v) for v in routes.load.values()),
        "hopper_bin_pairs": pairs, "pairs_with_alternative_intermediate_routes": alt_pairs,
        "shared_by_several_hoppers": sorted(x for x, u in users.items() if len(u) > 1),
        "shared_intake_and_loadout": sorted(intake_segments & load_segments),
        "multi_feed_equipment": sorted(e.id for e in site.equipment if e.max_concurrent_feeds > 1),
        "graded_commodities": sorted(c.id for c in site.commodities if policy.is_graded(c.id)),
        "grain_compatibility": compat,
        "load_points": types.get("loadpoint", 0), "weighbridges": types.get("weighbridge", 0),
        "truck_sequences": site.sequences.model_dump(),
    }


def _accepts(policy: GradePolicy, e, grain: GradedCommodity) -> bool:
    if grain.grade == "*":
        return grain.commodity in (e.commodities or [])
    return grain in policy.bin_accepts(e)


def markdown(rows: dict[str, dict]) -> str:
    keys = list(rows)
    def line(label, f):
        return f"| {label} | " + " | ".join(str(f(rows[k])) for k in keys) + " |"
    out = ["| Metric | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    out += [
        line("Configuration hash (first 12)", lambda r: r["config_hash"][:12]),
        line("Equipment / connections", lambda r: f"{r['equipment_total']} / {r['connections']}"),
        line("Equipment by type", lambda r: ", ".join(f"{t} {n}" for t, n in r["equipment_by_type"].items())),
        line("Independent intake systems", lambda r: r["intake_systems"]),
        line("Interconnect equipment", lambda r: ", ".join(r["interconnects"]) or "none"),
        line("Intake systems with interconnects removed", lambda r: r["intake_systems_without_interconnects"]),
        line("Intake routes / load routes", lambda r: f"{r['intake_routes']} / {r['load_routes']}"),
        line("Hopper-bin pairs with alternative intermediate routes", lambda r: f"{len(r['pairs_with_alternative_intermediate_routes'])} / {r['hopper_bin_pairs']}"),
        line("Equipment shared by several hoppers", lambda r: ", ".join(r["shared_by_several_hoppers"]) or "none"),
        line("Equipment shared by intake and load-out", lambda r: ", ".join(r["shared_intake_and_loadout"]) or "none"),
        line("Multi-feed equipment", lambda r: ", ".join(r["multi_feed_equipment"]) or "none"),
        line("Graded commodities", lambda r: ", ".join(r["graded_commodities"]) or "none"),
        line("Compatible bins per grain identity", lambda r: ", ".join(f"{g} {len(v['bins'])}" for g, v in r["grain_compatibility"].items())),
        line("Grain identities with a single reachable bin from some hopper", lambda r: ", ".join(g for g, v in r["grain_compatibility"].items() if v["min_reachable_bins"] == 1) or "none"),
        line("Load points / weighbridges", lambda r: f"{r['load_points']} / {r['weighbridges']}"),
    ]
    return "\n".join(out) + "\n"
