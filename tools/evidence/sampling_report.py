"""Tables and figures for the sampler-access extension, read only from its evidence package.

  python tools/evidence/sampling_report.py

Writes docs/evidence/sampling_ext/README.md, CSV tables and SVG figures. Synthetic configurations; software outputs.
"""
import csv
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
OUT = ROOT / "docs" / "evidence" / "sampling_ext"
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
          f"Source: `{rel}/manifest.json` (sha256 `{msha}`), extending baseline `{manifest['extends_baseline']['package']}` "
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
        for metric, fname, ylabel in (("Turnaround, unsampled trucks", "turnaround_unsampled", "Mean turnaround of unsampled trucks (min)"),
                                      ("Turnaround, sampled trucks", "turnaround_sampled", "Mean turnaround of sampled trucks (min)"),
                                      ("Physically blocked behind another truck, unsampled", "blocked_unsampled", "Blocked behind another truck (min per unsampled truck)")):
            data = {}
            for share in shares:
                for lay in LAYOUTS:
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
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
