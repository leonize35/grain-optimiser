"""Evidence summary for Paper 2, generated from the evaluations (no hand-entered numbers)."""

PKG = "evidence/out/paper2-v1"


def _path(exp: str) -> str:
    return f"`{PKG}/experiments/{exp}/evaluation.json`"


def summary_markdown(res: dict, rows: dict) -> str:
    g = lambda e, k, d="n/a": res.get(e, {}).get(k, d)  # noqa: E731
    ok = lambda e: ("yes" if res[e]["accepted"] else "**NO**") if e in res else "not run"  # noqa: E731
    s1 = res["EV-S2"]["by_policy"]
    p1 = res["EV-P1"]["operational_by_site_policy"]
    p1_stalls = ", ".join(f"{k} {v['stalled']}/{v['runs']}" for k, v in sorted(p1.items()) if v["stalled"]) or "none"
    x1 = res.get("EV-X1", {})
    rows_md = [
        ("Physical grain conservation", "A, B, C; policies M-FF, M-PT, M-SF; demand ×1.0 and ×1.2; seeds 0-4", "EV-C1",
         f"{g('EV-C1', 'runs')} runs; audit problems {g('EV-C1', 'audit_problems_total')}; max |balance| {g('EV-C1', 'max_abs_balance_kg')} kg; "
         f"stalled runs {g('EV-C1', 'stalled_runs')} (reported, not failures)",
         "0 audit problems, balance 0 kg, 0 engine violations, unexplained 0 kg in every run", ok("EV-C1"),
         "Synthetic configurations; 1-day horizon; in-transit grain is a modelled mass (I2)", _path("EV-C1")),
        ("Conservation under disturbances", "A, B, C + scheduled outages and stock events (overlays); M-FF, M-PT; seeds 0-4", "EV-C2",
         f"{g('EV-C2', 'runs')} runs; audit problems {g('EV-C2', 'audit_problems_total')}; suspensions {g('EV-C2', 'suspensions_total')}; "
         f"stock events refused {g('EV-C2', 'stock_events_refused_total')}",
         "as EV-C1", ok("EV-C2"), "Deterministic outage plans only; losses in bins only", _path("EV-C2")),
        ("Independent checker is sensitive", "C + disturbances, M-FF, seed 0, records corrupted", "EV-C3",
         f"{g('EV-C3', 'detected')}/{g('EV-C3', 'applicable')} corruptions detected",
         "every applicable corruption detected", ok("EV-C3"), "Corruption set is finite and hand-chosen", _path("EV-C3")),
        ("Equipment and route feasibility: configurations", "A, B, C, C-trap", "EV-F1",
         "all pass the prototype-parity validator and the rules validator" if g("EV-F1", "accepted", False) else "see file",
         "no validation errors", ok("EV-F1"),
         "Rule-level feasibility; throughput rates are inputs (no mechanical capacity model)", _path("EV-F1")),
        ("Route feasibility: alternative route under an outage", "C; EN1 unavailable (a) 05:00-12:00, (b) 08:00-12:00; M-FF; seeds 0-4", "EV-F2",
         f"transfers via CN1→EN2 during the outage per run: {g('EV-F2', 'alternative_route_transfers_during_outage_per_run')}; "
         f"audit problems {g('EV-F2', 'audit_problems_total')}",
         "(a) ≥ 1 per run; (a) and (b) 0 audit problems (incl. no flow through EN1 while down)", ok("EV-F2"),
         "(b) shows the provisional hold rule I1 keeping the shared upstream conveyor reserved, which blocks the "
         "alternative route; route and bin choice follow the fixed preference rule", _path("EV-F2")),
        ("Grain segregation", "C and C-trap (graded maize) in all experiments", "EV-S1",
         f"{g('EV-S1', 'runs')} runs; audit problems {g('EV-S1', 'audit_problems_total')}",
         "0 bin-identity or segment-commodity problems", ok("EV-S1"),
         "Golden sites A, B have no grades; changeover assumed to clean completely", _path("EV-S1")),
        ("Segregation risk is detected and reported", "C-trap; M-FF, M-PT, M-SF; seeds 0-4", "EV-S2",
         "; ".join(f"{k}: {v['stalled']}/{v['runs']} stalled {v['stall_reason_codes'] or ''}" for k, v in sorted(s1.items())),
         "physical invariants hold in every run; every stall has recorded reasons", ok("EV-S2"),
         "Stalls under M-SF are operational outcomes of a stress mapping, not representative practice; no static warning yet",
         _path("EV-S2")),
        ("Queue policies cannot violate physical constraints", "A, B, C; adversarial ADV-REV, ADV-RAND, ADV-RHOL; seeds 0-4", "EV-P1",
         f"{g('EV-P1', 'runs')} runs; audit problems {g('EV-P1', 'audit_problems_total')}; stalled (reported separately): {p1_stalls}",
         "0 audit problems in every run (stalls allowed, reported)", ok("EV-P1"),
         "Adversarial policies are test devices, not proposed practice", _path("EV-P1")),
        ("Reporting does not change decisions", "A, B, C; starvation threshold 0 / 120 / 10 000 min; seeds 0-2", "EV-P2",
         f"{g('EV-P2', 'cells_with_identical_decisions')}/{g('EV-P2', 'cells')} cells with identical decision digests",
         "identical decisions for every threshold", ok("EV-P2"), "Applies to the fairness threshold only", _path("EV-P2")),
        ("Transferability: one unchanged engine", "A, B, C, C-trap", "EV-T1 + EV-T2 + structure",
         f"{g('EV-T1', 'runs_total')} runs, one engine source digest; site-constant hits {len(g('EV-T2', 'hits', []))}; "
         f"intake systems A/B/C = {rows['A']['intake_systems']}/{rows['B']['intake_systems']}/{rows['C']['intake_systems']} "
         f"({rows['C']['intake_systems_without_interconnects']} without interconnect); alternative intermediate routes "
         f"A/B/C = {len(rows['A']['pairs_with_alternative_intermediate_routes'])}/{len(rows['B']['pairs_with_alternative_intermediate_routes'])}/"
         f"{len(rows['C']['pairs_with_alternative_intermediate_routes'])}",
         "all configurations validate and run with 0 audit problems; 0 site constants in engine code", ok("EV-T1"),
         "Three synthetic configurations; non-programmer configuration needs the UI and a user study",
         f"`{PKG}/experiments/EV-T1/evaluation.json`, `{PKG}/structure/structure.md`"),
        ("Stochastic reproducibility", "Selected runs repeated in fresh interpreters, PYTHONHASHSEED 0 and 12345", "EV-R1",
         f"{g('EV-R1', 'identical')}/{g('EV-R1', 'total')} identical run digests",
         "all identical", ok("EV-R1"),
         "One platform (see environment/); no Linux/macOS or other Python versions; dependencies not pinned", _path("EV-R1")),
        ("Cross-implementation equivalence (JavaScript prototype vs Python)", "17 validation cases; 10 admission scenarios; prototype self-tests", "EV-X1",
         f"validation parity {dict(x1.get('validation_parity_cases', {}))}; admission identical {len(x1.get('identical_admission_decisions', []))}/"
         f"{x1.get('admission_scenarios_compared', 'n/a')}, tie-break only {len(x1.get('differ_only_by_equal_age_tie_break', []))}; "
         f"prototype rules refused {len(x1.get('prototype_rules_refused_not_approximated', []))}; "
         f"prototype self-tests {x1.get('prototype_selftests', {}).get('passed')}/{x1.get('prototype_selftests', {}).get('total')}",
         "8 identical, 2 differing only by the documented tie-break, refused rules not approximated, self-tests all pass",
         ok("EV-X1"), "Common subset only (see not_representable_in_prototype); equal-age tie-break differs (open decision)",
         _path("EV-X1")),
    ]
    out = [
        "# Paper 2 evidence summary (generated)", "",
        "**Software verification on synthetic configurations.** None of these results is an observation of a real silo; "
        "no empirical validation has been performed. Sites A and B are the prototype's demonstration configurations; "
        "Site C and its trap variant are synthetic configurations written for this evidence.", "",
        "Queue-policy mappings (every queue group named; see `manifest.json`): M-FF feasible_first everywhere (engine "
        "default); M-PT strict FIFO at the hopper, feasible_first elsewhere (prototype-equivalent); M-SF strict FIFO "
        "everywhere including transfers (stress case, **not** claimed to represent practice); ADV-* adversarial test "
        "policies.", "",
        "Reproduction compares deterministic outputs only (`manifest.json` → `deterministic_files`); `environment/` "
        "(time, platform, versions, raw test timings) is excluded.", "",
        "| Research claim | Configuration | Experiment | Quantitative outcome | Acceptance criterion | Accepted | Limitations | Evidence file |",
        "|---|---|---|---|---|---|---|---|",
    ]
    out += ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows_md]
    out += ["", "## Not executed in this package (scientific gaps)", "",
            "- EV-R2 platform independence (Linux/macOS, other Python versions): needs CI.",
            "- EV-X2 distribution-level comparison with the prototype on the common subset: not re-run here "
            "(an earlier interactive comparison is in `docs/PORT_LOG.md`, step 11).",
            "- Experiments on alternative routes and multiple compatible bins beyond the fixed preference rule: need a "
            "bin-allocation policy (not implemented by decision).",
            "- Capacity from mechanical parameters, random breakdowns, drying/shrink formulas, by-products, regrading.",
            "- Empirical validation against observed silo data.", ""]
    return "\n".join(out)
