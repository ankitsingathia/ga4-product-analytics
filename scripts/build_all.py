"""Build everything from nothing, in order, and stop at the first failure.

    python scripts/build_all.py                  # synthetic data
    python scripts/build_all.py --raw data/raw   # the real BigQuery extract

With --raw, the extract's manifest must say it came from BigQuery, and the
audit runs before anything is built on it. A synthetic readout is written to
out/ with a SYNTHETIC stamp; only a real-data build writes docs/readout.html.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DBT = (
    "import sys; from dbt.cli.main import dbtRunner; "
    "sys.exit(0 if dbtRunner().invoke(sys.argv[1:]).success else 1)"
)


def run(label: str, cmd: list[str], env: dict[str, str]) -> None:
    print(f"\n{'=' * 66}\n{label}\n{'=' * 66}", flush=True)
    result = subprocess.run(cmd, cwd=REPO, env=env)
    if result.returncode != 0:
        print(f"\nFAILED: {label} (exit {result.returncode})", file=sys.stderr)
        raise SystemExit(result.returncode)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=None, help="Real extract directory (omit for synthetic)")
    ap.add_argument("--users", type=int, default=60_000, help="Synthetic data size")
    ap.add_argument("--sims", type=int, default=1000, help="A/A simulations")
    args = ap.parse_args(argv)

    py = sys.executable
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO / "src"), env.get("PYTHONPATH", "")])
    t0 = time.perf_counter()

    if args.raw is None:
        raw = REPO / "data" / "raw_synth"
        run("1/6  Generate synthetic extract", [py, "-m", "gpa.synth", "--out", str(raw), "--users", str(args.users)], env)
    else:
        raw = args.raw.resolve()
        manifest = raw / "manifest.json"
        if not manifest.exists() or json.loads(manifest.read_text()).get("source") != "bigquery":
            raise SystemExit(f"{manifest} missing or not from BigQuery. Run `python -m gpa.extract` first.")
        print(f"1/6  Using real extract at {raw}")

    out = REPO / "out"
    db = REPO / "data" / "warehouse.duckdb"
    env["GPA_RAW_DIR"] = raw.as_posix()
    env["GPA_DUCKDB"] = db.as_posix()

    run("2/6  Audit the raw extract", [py, "-m", "gpa.audit", "--raw", str(raw), "--json", str(out / "audit.json")], env)
    run("3/6  dbt build (models + data tests)",
        [py, "-c", DBT, "build", "--project-dir", str(REPO / "dbt"), "--profiles-dir", str(REPO / "dbt")], env)
    run("4/6  Cross-check dbt against an independent pandas implementation",
        [py, "-m", "gpa.crosscheck", "--raw", str(raw), "--db", str(db)], env)
    run("5/6  Analysis", [py, "-m", "gpa.analysis", "--db", str(db), "--audit", str(out / "audit.json"),
                          "--out", str(out / "results.json"), "--sims", str(args.sims)], env)

    readout = REPO / "docs" / "readout.html" if args.raw else out / "readout_synthetic.html"
    run("6/6  Readout", [py, "-m", "gpa.readout", "--results", str(out / "results.json"), "--out", str(readout)], env)

    print(f"\nBuilt in {time.perf_counter() - t0:.0f}s -> {readout.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
