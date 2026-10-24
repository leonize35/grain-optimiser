"""Results tables and figures for Paper 2, generated only from a built evidence package.

  python tools/evidence/report.py [evidence/out/paper2-v1]

Writes docs/evidence/PAPER2_RESULTS.md and docs/evidence/figures/*.svg. Every number is read from the package files;
the report records the sha256 of the manifest it was built from. Synthetic configurations; verification outputs.
"""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from silo_engine.experiments.runner import ci  # noqa: E402

# Reference categorical palette (dataviz skill, slots in fixed order) and text tokens, light surface for print.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
POLICY_ORDER = ["M-FF", "M-PT", "M-SF"]
SITE_ORDER = ["A", "B", "C"]


def load(pkg: Path, rel: str):
    return json.loads((pkg / rel).read_text(encoding="utf-8"))


def fmt(i, digits=1):
    if i.mean is None:
        return "–"
    return f"{i.mean:.{digits}f}" + ("" if i.half_width is None else f" ± {i.half_width:.{digits}f}")


def grouped_bars(path: Path, title: str, subtitle: str, ylabel: str, data: dict, groups: list[str], series: list[str],
                 labels: dict[str, str]) -> None:
    """Static grouped bar chart with 95% CI whiskers. data[(group, series)] = Interval. One axis, thin bars with
    rounded data ends, 2px gaps, recessive grid, legend + direct value labels on bar tops, <title> per bar for hover."""
    W, H, L, R, T, B = 720, 380, 64, 16, 70, 56
    pw, ph = W - L - R, H - T - B
    top = max((i.mean + (i.half_width or 0)) for i in data.values() if i.mean is not None) * 1.12
    raw_step = top / 5
    mag = 10 ** (len(str(int(raw_step))) - 1) if raw_step >= 1 else 1
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw_step)
    ticks = [k * step for k in range(0, int(top // step) + 1)]
    y = lambda v: T + ph - ph * v / top  # noqa: E731
    gw = pw / len(groups)
    bw = min(34, (gw - 28) / len(series) - 2)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Inter, Helvetica, Arial, sans-serif">',
           f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
           f'<text x="{L}" y="26" font-size="16" font-weight="600" fill="{INK}">{title}</text>',
           f'<text x="{L}" y="46" font-size="12" fill="{INK2}">{subtitle}</text>']
    for t in ticks:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{L - 8}" y="{y(t) + 4:.1f}" font-size="11" fill="{INK2}" text-anchor="end">{t:g}</text>')
    out.append(f'<text transform="translate(16,{T + ph / 2}) rotate(-90)" font-size="11" fill="{INK2}" text-anchor="middle">{ylabel}</text>')
    for gi, g in enumerate(groups):
        x0 = L + gi * gw + (gw - len(series) * (bw + 2)) / 2
        for si, s in enumerate(series):
            i = data.get((g, s))
            if i is None or i.mean is None:
                continue
            x, yt, yb = x0 + si * (bw + 2), y(i.mean), y(0)
            r = min(4, bw / 2)
            out.append(f'<path d="M{x:.1f},{yb:.1f} V{yt + r:.1f} Q{x:.1f},{yt:.1f} {x + r:.1f},{yt:.1f} H{x + bw - r:.1f} '
                       f'Q{x + bw:.1f},{yt:.1f} {x + bw:.1f},{yt + r:.1f} V{yb:.1f} Z" fill="{SERIES[si]}">'
                       f'<title>Site {g}, {labels[s]}: {fmt(i, 2)} (n={i.n})</title></path>')
            if i.half_width:
                cx = x + bw / 2
                out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(i.mean + i.half_width):.1f}" y2="{y(max(0, i.mean - i.half_width)):.1f}" stroke="{INK}" stroke-width="1.5"/>')
            out.append(f'<text x="{x + bw / 2:.1f}" y="{y(i.mean + (i.half_width or 0)) - 5:.1f}" font-size="10" fill="{INK2}" text-anchor="middle">{i.mean:.0f}</text>')
        out.append(f'<text x="{L + gi * gw + gw / 2:.1f}" y="{H - B + 20}" font-size="12" fill="{INK}" text-anchor="middle">Site {g}</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="{INK2}" stroke-width="1"/>')
    lx = L
    for si, s in enumerate(series):
        out.append(f'<rect x="{lx}" y="{H - 20}" width="10" height="10" rx="2" fill="{SERIES[si]}"/>')
        out.append(f'<text x="{lx + 14}" y="{H - 11}" font-size="11" fill="{INK}">{labels[s]}</text>')
        lx += 14 + 7 * len(labels[s]) + 18
    out.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main(pkg: Path) -> None:
    manifest = load(pkg, "manifest.json")
    msha = hashlib.sha256((pkg / "manifest.json").read_bytes()).hexdigest()
    ev = {p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted((pkg / "experiments").glob("*/evaluation.json"))}
    runs = {p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted((pkg / "experiments").glob("*/runs.json"))}
    rows = load(pkg, "structure/structure.json")
    rel = f"evidence/out/{pkg.name}"
    md = [f"# Paper 2: results from the evidence package `{pkg.name}` (generated)", "",
          f"Built from `{rel}/manifest.json` (sha256 `{msha}`), engine {manifest['engine_version']}, "
          f"engine source sha256 `{manifest['engine_source_sha256'][:16]}…`, base seed {manifest['base_seed']}.", "",
          "**Status of every number below: software-verification output on synthetic configurations.** Sites A and B "
          "are the prototype's demonstration configurations; Site C and the trap variant are synthetic. Nothing here "
          "is an observation of a real silo, and no empirical validation has been performed. Operational figures "
          "(throughput, waiting, stalls) are properties of the synthetic inputs and rules, not predictions for a real "
          "site.", ""]

    # ---- Table 1: equipment configurations
    md += ["## Table 1. Equipment configurations (`structure/structure.json`)", "",
           (pkg / "structure/structure.md").read_text(encoding="utf-8").split("\n", 2)[2], ""]

    # ---- Table 2: conservation
    md += ["## Table 2. Grain conservation (EV-C1 base days; EV-C2 with outages and stock events)", "",
           "| Experiment | Site | Policy mapping | Demand | Runs | Audit problems | max abs balance (kg) | Engine violations | Unexplained (kg) | Received t/day (mean ± 95% CI) |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for exp in ("EV-C1", "EV-C2"):
        cells = defaultdict(list)
        for r in runs[exp]:
            s = r["settings"]
            cells[(s["site"], s["policy"], s["demand"])].append(r)
        for (site, pol, dem), rs in sorted(cells.items(), key=lambda kv: (SITE_ORDER.index(kv[0][0]), POLICY_ORDER.index(kv[0][1]), kv[0][2])):
            md.append(f"| {exp} | {site} | {pol} | ×{dem} | {len(rs)} | {sum(x['physical']['audit_problems'] for x in rs)} | "
                      f"{max(abs(x['physical']['material_balance_kg']) for x in rs)} | {sum(x['physical']['engine_violations'] for x in rs)} | "
                      f"{sum(abs(x['physical']['unexplained_kg']) for x in rs)} | {fmt(ci([x['kpis']['received_t'] for x in rs]), 0)} |")
    md += ["", f"Checker sensitivity (EV-C3): {ev['EV-C3']['detected']}/{ev['EV-C3']['applicable']} corruptions detected: "
           + ", ".join(f"{k} ({v})" for k, v in ev["EV-C3"]["corruptions"].items()) + ".", ""]

    # ---- Table 3: resource constraints and feasibility
    f2 = ev["EV-F2"]["alternative_route_transfers_during_outage_per_run"]
    md += ["## Table 3. Equipment and route feasibility", "",
           "| Check | Configuration | Result | Accepted |", "|---|---|---|---|"]
    for k, v in ev["EV-F1"]["configs"].items():
        md.append(f"| Validators (prototype parity + rules) | {k} (`{v['file']}`) | prototype ok {v['prototype_validate_ok']}, rule errors {len(v['rules_errors'])} | {'yes' if v['prototype_validate_ok'] and not v['rules_errors'] else 'no'} |")
    md += [f"| Alternative route CN1→EN2 while EN1 unavailable 05:00-12:00 (EV-F2a) | C | transfers per run {f2.get('site_c_en1_outage_from_start')} | {'yes' if all(n >= 1 for n in f2.get('site_c_en1_outage_from_start', [0])) else 'no'} |",
           f"| Same, EN1 unavailable 08:00-12:00 (EV-F2b, observation) | C | transfers per run {f2.get('site_c_en1_outage')} | observation (hold rule I1) |",
           f"| Segment, feed-limit, merge, clear-time, outage invariants in all runs | A, B, C, C-trap | audit problems {sum(e.get('audit_problems_total', 0) for k, e in ev.items() if k in ('EV-C1', 'EV-C2', 'EV-F2', 'EV-S2', 'EV-P1', 'EV-P2'))} over {sum(e.get('runs', 0) for k, e in ev.items() if k in ('EV-C1', 'EV-C2', 'EV-F2', 'EV-S2', 'EV-P1', 'EV-P2'))} runs | {'yes' if all(ev[k]['physical_invariants_hold'] for k in ('EV-C1', 'EV-C2', 'EV-F2', 'EV-S2', 'EV-P1', 'EV-P2')) else 'no'} |", ""]

    # ---- Table 4: segregation
    md += ["## Table 4. Grain segregation", "",
           f"EV-S1: {ev['EV-S1']['runs']} runs on the graded configurations (C, C-trap), audit problems {ev['EV-S1']['audit_problems_total']}.", "",
           "| EV-S2 (C-trap) policy mapping | Runs | Stalled runs | Stall reason codes | Physical invariants |", "|---|---|---|---|---|"]
    for pol in POLICY_ORDER:
        b = ev["EV-S2"]["by_policy"].get(pol)
        if b:
            md.append(f"| {pol} | {b['runs']} | {b['stalled']} | {b['stall_reason_codes'] or '–'} | {'hold' if ev['EV-S2']['physical_invariants_hold'] else 'VIOLATED'} |")
    md.append("")

    # ---- Table 5: operating policies
    labels = {k: f"{k}" for k in POLICY_ORDER}
    md += ["## Table 5. Operating-policy mappings (EV-C1, demand ×1.0, 5 seeds; mean ± 95% CI)", "",
           "| Site | Mapping | Completed unloading trucks | Unfinished unloading trucks | Mean unloading turnaround (min) | Max overtakes of a truck | Starved trucks (≥120 min) | Stalled runs |",
           "|---|---|---|---|---|---|---|---|"]
    fig_completed, fig_turn = {}, {}
    for site in SITE_ORDER:
        for pol in POLICY_ORDER:
            rs = [r for r in runs["EV-C1"] if r["settings"]["site"] == site and r["settings"]["policy"] == pol and r["settings"]["demand"] == 1.0]
            k = lambda key: ci([r["kpis"].get(key) for r in rs])  # noqa: E731
            fig_completed[(site, pol)], fig_turn[(site, pol)] = k("unload.completed"), k("unload.mean_turnaround_min")
            md.append(f"| {site} | {pol} | {fmt(k('unload.completed'))} | {fmt(k('unload.unfinished'))} | {fmt(k('unload.mean_turnaround_min'))} | "
                      f"{fmt(k('unload.max_overtaken'))} | {fmt(k('unload.starved'))} | {sum(r['operational']['stalled'] for r in rs)} |")
    md += ["", "Adversarial policies (EV-P1, demand ×1.0, 5 seeds per cell): physical invariants "
           f"{'hold in every run' if ev['EV-P1']['physical_invariants_hold'] else 'VIOLATED'} "
           f"({ev['EV-P1']['audit_problems_total']} audit problems over {ev['EV-P1']['runs']} runs).", "",
           "| Site / adversarial policy | Runs | Stalled (operational, reported) | Completed trucks (total) | Unfinished (total) |", "|---|---|---|---|---|"]
    for key, v in sorted(ev["EV-P1"]["operational_by_site_policy"].items()):
        md.append(f"| {key} | {v['runs']} | {v['stalled']} | {v['completed']} | {v['unfinished']} |")
    md += ["", f"Reporting threshold (EV-P2): {ev['EV-P2']['cells_with_identical_decisions']}/{ev['EV-P2']['cells']} cells give identical decision digests for thresholds 0, 120 and 10 000 min.", ""]

    # ---- Table 6: interruptions and stock events
    md += ["## Table 6. Interruptions and stock events (EV-C2, demand ×1.0, 5 seeds per mapping)", "",
           "| Site | Mapping | Runs | Suspensions | Stock events refused | Losses (t, total) | Observations flagged (tolerance 1 t) | Book − physical at end (t, mean) | Unexplained (kg) | Audit problems |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for site in SITE_ORDER:
        for pol in ("M-FF", "M-PT"):
            rs = [r for r in runs["EV-C2"] if r["settings"]["site"] == site and r["settings"]["policy"] == pol]
            md.append(f"| {site} | {pol} | {len(rs)} | {sum(r['operational']['suspensions'] for r in rs)} | {sum(r['operational']['stock_events_refused'] for r in rs)} | "
                      f"{sum(r['kpis'].get('losses.total_t', 0) for r in rs):g} | {sum(r['kpis'].get('observations.flagged', 0) for r in rs)} | "
                      f"{fmt(ci([r['kpis'].get('reconciliation.difference_t') for r in rs]), 2)} | {sum(abs(r['physical']['unexplained_kg']) for r in rs)} | "
                      f"{sum(r['physical']['audit_problems'] for r in rs)} |")
    md.append("")

    # ---- Table 7: reproducibility and cross-implementation
    x1, r1 = ev.get("EV-X1", {}), ev.get("EV-R1", {})
    tests = load(pkg, "tests/test_outcomes.json") if (pkg / "tests/test_outcomes.json").exists() else {"counts": {}}
    check_path = pkg.parent / f"{pkg.name}-reproduction-check.json"
    chk = json.loads(check_path.read_text(encoding="utf-8")) if check_path.exists() else None
    md += ["## Table 7. Reproducibility and cross-implementation equivalence", "",
           "| Check | Result | Accepted |", "|---|---|---|",
           f"| Test suite outcomes | {tests['counts']} | {'yes' if not tests['counts'].get('failed') and not tests['counts'].get('error') else 'no'} |",
           f"| Fresh interpreters, PYTHONHASHSEED 0 and 12345 (EV-R1) | {r1.get('identical')}/{r1.get('total')} identical run digests | {'yes' if r1.get('accepted') else 'no'} |",
           f"| Full rebuild and comparison of deterministic files | " + (f"{chk['files_compared']} files compared, {len(chk['differing'])} differing" if chk else "not run") + f" | {('yes' if chk and chk['identical'] else 'no') if chk else '–'} |",
           f"| Validation parity with the prototype (EV-X1) | {x1.get('validation_parity_cases')} | {'yes' if x1.get('accepted') else 'no'} |",
           f"| Admission decisions vs prototype | identical {len(x1.get('identical_admission_decisions', []))}/{x1.get('admission_scenarios_compared')}; tie-break only {len(x1.get('differ_only_by_equal_age_tie_break', []))} ({', '.join(x1.get('differ_only_by_equal_age_tie_break', []))}); tie-break substitution diagnostics {x1.get('tie_break_substitution_diagnostics')} | {'yes' if x1.get('accepted') else 'no'} |",
           f"| Prototype rules refused, not approximated | {len(x1.get('prototype_rules_refused_not_approximated', []))} scenarios | yes |",
           f"| Prototype self-tests | {x1.get('prototype_selftests', {}).get('passed')}/{x1.get('prototype_selftests', {}).get('total')} | – |",
           f"| Features the prototype cannot represent (no equivalence claimed) | {', '.join(x1.get('not_representable_in_prototype', []))} | – |", ""]

    # ---- figures
    figs = ROOT / "docs" / "evidence" / "figures"
    grouped_bars(figs / "fig_completed_by_policy.svg", "Completed unloading trucks per synthetic day",
                 "EV-C1, demand ×1.0, 5 seeds, mean with 95% CI. Synthetic configurations; not observed data.",
                 "trucks per day", fig_completed, SITE_ORDER, POLICY_ORDER, labels)
    grouped_bars(figs / "fig_turnaround_by_policy.svg", "Mean unloading turnaround (minutes)",
                 "EV-C1, demand ×1.0, 5 seeds, mean with 95% CI. Synthetic configurations; not observed data.",
                 "minutes", fig_turn, SITE_ORDER, POLICY_ORDER, labels)
    md += ["## Figures", "",
           "- `docs/evidence/figures/fig_completed_by_policy.svg`: completed unloading trucks per day by site and policy mapping (Table 5).",
           "- `docs/evidence/figures/fig_turnaround_by_policy.svg`: mean unloading turnaround by site and policy mapping (Table 5).", "",
           "Policy mappings: M-FF feasible-first in every queue (engine default); M-PT strict FIFO at the hopper, "
           "feasible-first elsewhere (prototype-equivalent); M-SF strict FIFO in every queue including transfers "
           "(stress case, not representative practice).", ""]
    discussion = ROOT / "docs" / "evidence" / "paper2_discussion.md"  # hand-written interpretation, appended
    if discussion.exists():
        md += ["", discussion.read_text(encoding="utf-8")]
    out = ROOT / "docs" / "evidence" / "PAPER2_RESULTS.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {out} and figures (manifest sha256 {msha[:16]}…)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "evidence" / "out" / "paper2-v1")
