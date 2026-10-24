"""Paper 2 evidence package (docs/evidence/EVIDENCE_READINESS.md).

  python tools/evidence_run.py build [--quick] [--no-tests]   write evidence/out/paper2-v1
  python tools/evidence_run.py check                          rebuild and compare deterministic outputs
  python tools/evidence_run.py digest '<cell json>'           run one cell, print its result digest
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from tools.evidence.runner import PACKAGE_ID, build, check, run_cell  # noqa: E402

OUT = ROOT / "evidence" / "out" / PACKAGE_ID


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("build", "check", "digest"):
        print(__doc__)
        return 2
    if argv[0] == "build":
        results = build(OUT, with_tests="--no-tests" not in argv, quick="--quick" in argv)
        failed = [k for k, v in results.items() if not v.get("accepted")]
        print("not accepted:", failed or "none")
        return 1 if failed else 0
    if argv[0] == "check":
        report = check(OUT)
        (ROOT / "evidence" / "out" / f"{PACKAGE_ID}-reproduction-check.json").write_text(
            json.dumps(report, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "differing"} | {"differing": report["differing"][:20]}, indent=1))
        return 0 if report["identical"] else 1
    record, _, _ = run_cell(json.loads(argv[1]))
    print(record["run_sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
