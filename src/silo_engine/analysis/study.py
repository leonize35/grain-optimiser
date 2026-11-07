"""TLS slice T6: an improvement study over replications (docs/TLS_ANALYSIS_DESIGN.md §6). Analysis only.

A study is {"name", "classification": {step: class}, "ctq": {...} or absent, "settings": {lead_share, lead_ratio,
min_hour_min, little_tolerance}, "activity": "unload"}. It is kept beside the site configuration (store.save_study)
and never changes the simulation. `improvement_study` combines, over the replications of one configuration:
- toc: candidates pooled over runs (mean truck-minutes per run), the constraint verdict on the pooled evidence, and
  in how many runs each resource was the constraint (`led_runs`);
- resource_use: per equipment, the mean over runs of utilisation, busy, blocked and queued time;
- lean: the value-stream map, averaged over runs (process cycle efficiency only when every step is classified);
- six_sigma: capability against the CTQ (None without a CTQ);
- little: Little's law in every run; reconciled: the truck wait causes reconcile with the step records in every run.
"""
from statistics import mean

from ..config.schema import SiteConfig
from .capability import capability
from .constraints import _reconciled, constraint_candidates, rank_wait_causes
from .resource_use import resource_use
from .value_stream import value_stream

ASSURANCE = ("Simulated results for the configuration as entered; not validated against observations of the site. "
             "Thresholds are provisional settings.")


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return mean(xs) if xs else None


def improvement_study(site: SiteConfig, results: list, study: dict) -> dict:
    st = study.get("settings") or {}
    lead_share, lead_ratio = st.get("lead_share", 0.4), st.get("lead_ratio", 1.5)
    min_hour, tol = st.get("min_hour_min", 5), st.get("little_tolerance", 0.1)
    activity = study.get("activity", "unload")
    classes = study.get("classification") or {}

    uses = [resource_use(site, r, little_tolerance=tol) for r in results]
    eq_ids = list(dict.fromkeys(k for u in uses for k in u["equipment"]))
    pooled_use = {}
    for k in eq_ids:
        rows = [u["equipment"][k] for u in uses if k in u["equipment"]]
        pooled_use[k] = {"kind": rows[0]["kind"], "lanes": rows[0]["lanes"],
                         **{f: _mean([x[f] for x in rows]) for f in ("utilisation", "busy_min", "blocked_min",
                                                                       "queued_truck_min", "served")}}
    util = {k: v["utilisation"] for k, v in pooled_use.items()}
    for seg in dict.fromkeys(k for u in uses for k in u["segments"]):  # belts and elevators: grain flowing
        util[seg] = _mean([u["segments"][seg]["utilisation"] for u in uses if seg in u["segments"]])

    per_run = [constraint_candidates(site, r, lead_share, lead_ratio, min_hour) for r in results]
    toc = rank_wait_causes(site, [r.wait_causes for r in results], util, lead_share, lead_ratio, min_hour)
    led: dict[str, int] = {}
    for c in per_run:
        if c["constraint"]:
            led[c["constraint"]] = led.get(c["constraint"], 0) + 1
    toc["led_runs"] = led
    toc["run_verdicts"] = [c["verdict"] for c in per_run]

    maps = [value_stream(site, r, classes, activity) for r in results]
    steps = []
    for i, s in enumerate(maps[0]["steps"] if maps else []):
        rows = [m["steps"][i] for m in maps if i < len(m["steps"]) and m["steps"][i]["step"] == s["step"]]
        steps.append({"step": s["step"], "class": s["class"], "lanes": s["lanes"],
                      **{f: _mean([x[f] for x in rows]) for f in ("trucks", "mean_move_min", "mean_wait_min",
                                                                    "mean_service_min", "mean_held_in_service_min",
                                                                    "mean_blocked_min", "cycle_min")}})
    takt = _mean([m["takt_min"] for m in maps])
    for s in steps:
        s["slower_than_takt"] = None if s["cycle_min"] is None or takt is None else s["cycle_min"] > takt
    lean = {"steps": steps, "takt_min": takt,
            "mean_lead_time_min": _mean([m["mean_lead_time_min"] for m in maps]),
            "breakdown_min": {k: _mean([m["breakdown_min"][k] for m in maps])
                              for k in (maps[0]["breakdown_min"] if maps else {})},
            "process_cycle_efficiency": (None if any(m["process_cycle_efficiency"] is None for m in maps)
                                         else _mean([m["process_cycle_efficiency"] for m in maps])),
            "adds_up": all(m["adds_up"] for m in maps), "notes": maps[0]["notes"] if maps else [],
            "waste": {k: _mean([m["waste"][k] for m in maps]) for k in
                      ("waiting_truck_min", "moving_truck_min", "unfinished_trucks", "turned_away_trucks",
                       "mean_trucks_on_site", "mean_tipping_to_storage_min")},
            "not_modelled": maps[0]["waste"]["not_modelled"] if maps else []}

    six = capability(results, study["ctq"]) if study.get("ctq") else None
    little = {"exact_ok": all(u["little"]["exact_ok"] for u in uses),
              "steady_gap_mean": _mean([u["little"]["steady_gap"] for u in uses]), "tolerance": tol,
              "steady_ok_runs": sum(1 for u in uses if u["little"]["steady_ok"])}
    return {"toc": toc, "resource_use": pooled_use, "lean": lean, "six_sigma": six, "little": little,
            "reconciled": all(_reconciled(r) for r in results), "replications": len(results),
            "limitations": sorted({x for u in uses for x in u["limitations"]} | set(toc["limitations"])),
            "assurance": ASSURANCE}
