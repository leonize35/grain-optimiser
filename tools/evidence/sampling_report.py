"""Tables and figures for the sampler-access extension, read only from its evidence package.

  python tools/evidence/sampling_report.py

Writes evidence/out/paper2-ext-sampling-v1/report/: README.md, CSV tables, SVG figures and report_manifest.json (sha256 of
each report file and of the package manifest it was derived from). The package's own manifest does not list report/;
the rebuild-and-compare check covers the simulation outputs. Synthetic configurations; software outputs.
"""
import csv
from collections import defaultdict
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from silo_engine.experiments.runner import Interval  # noqa: E402
from tools.evidence import report  # noqa: E402

PKG = ROOT / "evidence" / "out" / "paper2-ext-sampling-v1"
OUT = PKG / "report"  # derived from the verified package files; listed in report/report_manifest.json
LAYOUTS = ["S1", "S2", "S3", "S4"]
LAYOUT_TEXT = {"S1": "S1 sep., no bypass", "S2": "S2 sep., bypass", "S3": "S3 at WB, no bypass", "S4": "S4 at WB, bypass"}


def f(x, d=1):
    return "–" if x is None else f"{x:.{d}f}"


def csv_text(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})
    return buf.getvalue()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "figures").mkdir(exist_ok=True)
    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    msha = hashlib.sha256((PKG / "manifest.json").read_bytes()).hexdigest()
    files = manifest["deterministic_files"]
    rel = "evidence/out/paper2-ext-sampling-v1"
    src = lambda p: f"`{rel}/{p}` (sha256 {files[p][:12]})"  # noqa: E731
    ver = json.loads((PKG / "verification.json").read_text(encoding="utf-8"))
    cells = json.loads((PKG / "summary_cells.json").read_text(encoding="utf-8"))
    comps = json.loads((PKG / "paired_comparisons.json").read_text(encoding="utf-8"))
    runs = json.loads((PKG / "runs.json").read_text(encoding="utf-8"))
    chk_path = PKG.parent / "paper2-ext-sampling-v1-reproduction-check.json"
    chk = json.loads(chk_path.read_text(encoding="utf-8")) if chk_path.exists() else None
    (OUT / "summary_cells.csv").write_text(csv_text(cells), encoding="utf-8")
    (OUT / "paired_comparisons.csv").write_text(csv_text(comps), encoding="utf-8")
    sites, shares = manifest["sites"], manifest["sampling_shares"]
    n = len(manifest["seeds"])
    md = ["# Paper 2 extension: sampler access, physical queue blocking and sampler location (generated)", "",
          f"Source: `{rel}/manifest.json` (sha256 `{msha}`), built at Git commit `{_commit()}`, extending baseline `{manifest['extends_baseline']['package']}` "
          f"(commit `{manifest['extends_baseline']['commit']}`, manifest sha256 `{manifest['extends_baseline']['manifest_sha256'][:16]}…`, unchanged). "
          f"Engine source sha256 `{manifest['engine_source_sha256'][:16]}…`.", "",
          "**Synthetic configurations; software outputs, not observations of a real silo. Provisional modelling "
          "assumptions O1-O11 (`docs/SAMPLER_ACCESS_DESIGN.md` §8) apply to every result.** Layouts differ only in "
          "layout; sampling units and weighbridge bays are the same within each site. Queue policy: M-FF in every queue "
          "group (stated, not claimed as practice).", "",
          "## Verification", "",
          f"| Check | Result |", "|---|---|",
          f"| Runs (2 sites × 4 layouts × {len(shares)} sampled shares × {n} seeds) | {ver['runs']} |",
          f"| Flow-audit problems (incl. access invariants) | {ver['audit_problems_total']} |",
          f"| max abs mass balance / engine violations | {ver['max_abs_balance_kg']} kg / {ver['engine_violations']} |",
          f"| Stalled runs (operational, reported) | {ver['stalled_runs']} |",
          f"| Rebuild and compare | " + (f"{chk['files_compared'] - len(chk['differing'])}/{chk['files_compared']} files identical" if chk else "not run") + " |",
          f"| Deterministic acceptance tests S1-S4 | `tests/test_sampler_access.py` (18 tests, hand-traced) |", "",
          f"Sources: {src('verification.json')}; {src('audit.json')}.", ""]
    idx = {(c["site"], c["share"], c["layout"], c["metric"]): c for c in cells}
    metrics = list(dict.fromkeys(c["metric"] for c in cells))
    for site in sites:
        md += [f"## Site {site}: performance by layout and sampled share (n = {n} seeds; mean ± 95% CI half-width [SD])", "",
               "| Share | Layout | " + " | ".join(f"{m} ({idx[(site, shares[0], 'S1', m)]['unit']})" for m in metrics) + " |",
               "|---|---|" + "---|" * len(metrics)]
        for share in shares:
            for lay in manifest["layouts"][site]:
                row = []
                for m in metrics:
                    c = idx[(site, share, lay, m)]
                    hw = None if c["ci_low"] is None else (c["ci_high"] - c["ci_low"]) / 2
                    d = 3 if c["unit"] == "fraction" else 1
                    row.append(f"{f(c['mean'], d)} ± {f(hw, d)} [{f(c['sd'], d)}]" if c["mean"] is not None else "–")
                md.append(f"| {share:g} | {lay} | " + " | ".join(row) + " |")
        md.append("")
    md += [f"Source: {src('summary_cells.json')} (all cells: `summary_cells.csv`).", ""]

    # ---- configuration differences between scenarios
    diffs = json.loads((PKG / "layout_differences.json").read_text(encoding="utf-8"))
    md += ["## Configuration differences between scenarios (verified by the build)", "",
           "Every scenario is generated from its site's S1 configuration; the build asserts that only "
           f"{', '.join('`' + x + '`' for x in manifest['allowed_layout_differences'])} differ. Sampling units, "
           "weighbridge bays, service-time distributions, hoppers, routes and demand are identical within a site.", "",
           "| Site: comparison | Differing configuration paths |", "|---|---|"]
    md += [f"| {k} | {', '.join(v) or 'none (reference)'} |" for k, v in diffs.items()]
    md += ["", f"Source: {src('layout_differences.json')}; configurations `{rel}/configs/`.", ""]

    # ---- waiting decomposition by class (share 0.7)
    by = defaultdict(list)
    for r in runs:
        by[(r["settings"]["site"], r["settings"]["layout"], r["settings"]["share"])].append(r)
    md += ["## Where trucks wait: decomposition by truck class (sampled share 0.7; mean minutes per truck over 20 seeds)", "",
           "Road blocking = behind another truck in the single-file approach; sampler queue = waiting for the sampler "
           "(or, for unsampled trucks, for the sampler bay to drive through), excluding road blocking; holding blocking = "
           "kept in the sampler bay after service because the holding space (or, without one, the weighbridge) was full; "
           "weighbridge = waiting for a weighbridge bay. The four parts do not overlap.", "",
           "| Site | Layout | Class | Trucks/day | Road blocking | Sampler queue | Holding blocking | Weighbridge | Turnaround | Pass-throughs/day |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for site in sites:
        for lay in manifest["layouts"][site]:
            rs = by[(site, lay, 0.7)]
            for k in ("sampled", "unsampled"):
                vals = [r["by_class"].get(k) for r in rs if r["by_class"].get(k)]
                if not vals:
                    continue
                mean = lambda key: sum(v[key] for v in vals if v[key] is not None) / max(1, len([v for v in vals if v[key] is not None]))  # noqa: E731
                md.append(f"| {site} | {lay} | {k} | {sum(v['trucks'] for v in vals) / len(vals):.1f} | {mean('mean_blocked_behind_min'):.2f} | "
                          f"{mean('mean_sampler_wait_min'):.2f} | {mean('mean_holding_block_min'):.2f} | {mean('mean_weighbridge_wait_min'):.2f} | "
                          f"{mean('mean_turnaround_min'):.1f} | {sum(v['pass_throughs'] for v in vals) / len(vals):.1f} |")
    md += ["", f"Source: {src('runs.json')} (field `by_class`).", ""]

    # ---- Site C throughput investigation
    md += ["## Site C throughput: access or downstream grain handling?", "",
           "| Share | Layout | Completed unloading trucks | Unfinished at closing, at a hopper | Hopper waiting (min) | Approach queue (time-avg) |",
           "|---|---|---|---|---|---|"]
    for share in shares:
        for lay in manifest["layouts"].get("C", []):
            get = lambda m: idx[("C", share, lay, m)]  # noqa: E731
            md.append(f"| {share:g} | {lay} | {f(get('Completed unloading trucks')['mean'])} | {f(get('Unfinished at closing, waiting at a hopper')['mean'])} | "
                      f"{f(get('Hopper waiting (tip), all unloading trucks')['mean'])} | {f(get('Approach queue length (time-average)')['mean'], 2)} |")
    corr_rows = []
    for share in shares:
        for a, b in (("S3", "S4"), ("S1", "S2"), ("S1", "S3")):
            pa = {r["settings"]["seed_index"]: r for r in by[("C", a, share)]}
            pb = {r["settings"]["seed_index"]: r for r in by[("C", b, share)]}
            dc = [pb[i]["operational"]["unload_completed"] - pa[i]["operational"]["unload_completed"] for i in pa]
            dt = [pb[i]["operational"]["unfinished_at_tip"] - pa[i]["operational"]["unfinished_at_tip"] for i in pa]
            corr_rows.append((share, f"{b} - {a}", sum(dc) / len(dc), sum(dt) / len(dt), _pearson(dc, dt)))
    md += ["", "Per-seed paired changes: completed trucks against trucks left waiting at a hopper at closing:", "",
           "| Share | Comparison | Mean change in completed | Mean change in unfinished at a hopper | Correlation across seeds |", "|---|---|---|---|---|"]
    md += [f"| {sh:g} | {c} | {f(m1)} | {f(m2)} | {f(r_, 2)} |" for sh, c, m1, m2, r_ in corr_rows]
    s_completed = {lay: idx[("S", 0.7, lay, "Completed unloading trucks")]["mean"] for lay in manifest["layouts"].get("S", [])}
    md += ["", "Controlled Site S (no downstream constraint), completed trucks at share 0.7: "
           + ", ".join(f"{k} {f(v)}" for k, v in s_completed.items())
           + f"; hopper waiting in every Site S cell: max {max(c['mean'] or 0 for c in cells if c['site'] == 'S' and c['metric'].startswith('Hopper waiting')):.2f} min.",
           "", "Interpretation rule used in this report: a throughput difference on Site C is attributed to truck access only "
           "where it is not accompanied by a matching change in trucks left waiting at the hoppers; Site S shows the "
           "access effect with downstream handling removed.", ""]
    counts = {}
    for c in comps:
        counts[c["support"]] = counts.get(c["support"], 0) + 1
    md += ["## Paired comparisons (by seed; common arrivals, sampling requirements and service draws)", "",
           f"Holm adjustment over {sum(1 for c in comps if c['p'] is not None)} tested comparisons. Outcome counts: "
           + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) + ". Listed: supported and nominal results; "
           "everything else is descriptive (`paired_comparisons.csv`).", "",
           "| Site | Share | Comparison (effect) | Metric | Mean difference | 95% CI | p (Holm) | Support |", "|---|---|---|---|---|---|---|---|"]
    for c in comps:
        if c["support"].startswith(("supported", "nominal", "constant")):
            md.append(f"| {c['site']} | {c['share']:g} | {c['comparison']} ({c['effect']}) | {c['metric']} ({c['unit']}) | "
                      f"{f(c['mean_difference'], 2)} | [{f(c['ci_low'], 2)}, {f(c['ci_high'], 2)}] | {f(c['p_holm'], 4)} | {c['support']} |")
    md += ["", f"Source: {src('paired_comparisons.json')}.", ""]
    # figures: share 0.7, per site, turnaround by class and blocked time of unsampled trucks
    for site in sites:
        site_layouts = manifest["layouts"][site]
        for metric, fname, ylabel in (("Turnaround, unsampled trucks", "turnaround_unsampled", "Mean turnaround of unsampled trucks (min)"),
                                      ("Turnaround, sampled trucks", "turnaround_sampled", "Mean turnaround of sampled trucks (min)"),
                                      ("Physically blocked behind another truck, unsampled", "blocked_unsampled", "Blocked behind another truck (min per unsampled truck)")):
            data = {}
            for share in shares:
                for lay in site_layouts[:4]:
                    c = idx[(site, share, lay, metric)]
                    hw = None if c["ci_low"] is None else (c["ci_high"] - c["ci_low"]) / 2
                    data[(f"{share:g}", lay)] = Interval(c["n"], c["mean"], c["sd"], hw)
            report.grouped_bars(OUT / "figures" / f"site_{site}_{fname}.svg", f"Site {site}: {metric}",
                                f"Grouped by sampled share; n = {n} seeds per bar (common random numbers); 95% CI. Synthetic.",
                                ylabel, data, [f"{s:g}" for s in shares], LAYOUTS, LAYOUT_TEXT, group_label="share {}",
                                legend_width=160)
    md += ["## Figures", "", "| Figure | Shows | Basis |", "|---|---|---|"]
    for site in sites:
        for fname, what in (("turnaround_unsampled", "mean turnaround of unsampled trucks"), ("turnaround_sampled", "mean turnaround of sampled trucks"),
                            ("blocked_unsampled", "time unsampled trucks were physically blocked behind another truck")):
            md.append(f"| `figures/site_{site}_{fname}.svg` | Site {site}: {what} by layout and sampled share, mean ± 95% CI | "
                      f"{n} seeds per bar, common random numbers; differences judged from the paired table, not overlapping whiskers |")
    md += ["", "## Limitations", "",
           "- Provisional assumptions O1-O11 (unconfirmed): no travel times, sampling then weighing at a probe bay without overlap, "
           "drive-through time 0.3-1.0 min, bypass lanes hold no trucks, no staff discretion, grading result awaited in the yard.",
           "- A bypass into a holding place promised to the truck being sampled gives no benefit under `reserve_next_space` "
           "(tested); the experiment's S2 bypass therefore leads to the weighbridge.",
           "- Throughput on Site C is partly driven by downstream grain dynamics: access layouts change the order in which "
           "trucks reach the hoppers, and pit-compatibility waits depend on that order (most trucks unfinished at closing "
           "wait at the hoppers).",
           "- Synthetic sites and demand; one queue-policy mapping; one day; one platform. No empirical validation.", ""]
    (OUT / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    listing = {q.relative_to(OUT).as_posix(): hashlib.sha256(q.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
               for q in sorted(OUT.rglob("*")) if q.is_file() and q.name != "report_manifest.json"}
    (OUT / "report_manifest.json").write_text(
        json.dumps({"derived_from_manifest_sha256": msha, "files": listing}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")




def _pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if not sxx or not syy:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sxx * syy) ** 0.5


def _commit():
    env = json.loads((PKG / "environment" / "environment.json").read_text(encoding="utf-8"))
    return env.get("git_commit", "?")[:7]


if __name__ == "__main__":
    main()
