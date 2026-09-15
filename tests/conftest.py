"""One synthetic build per test session: generate, audit, dbt build.

Every pipeline test asserts against truth.json, the counts the generator
actually planted, so "close enough" is never accepted where exact is possible.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gpa import audit, synth

REPO = Path(__file__).resolve().parents[1]
DBT = (
    "import sys; from dbt.cli.main import dbtRunner; "
    "sys.exit(0 if dbtRunner().invoke(sys.argv[1:]).success else 1)"
)


@pytest.fixture(scope="session")
def built(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("build")
    raw, db = root / "raw", root / "warehouse.duckdb"
    truth = synth.write(raw, n_users=20_000, seed=3)
    audit_result = audit.run(raw)

    # dbt runs in a subprocess, exactly as build_all runs it. In-process,
    # dbt-duckdb keeps its read-write connection open and the tests could not
    # then open the warehouse read-only.
    env = dict(os.environ, GPA_RAW_DIR=raw.as_posix(), GPA_DUCKDB=db.as_posix())
    dbt_dir = str(REPO / "dbt")
    res = subprocess.run(
        [sys.executable, "-c", DBT, "build", "--project-dir", dbt_dir, "--profiles-dir", dbt_dir, "--quiet"],
        env=env, capture_output=True, text=True,
    )
    assert res.returncode == 0, f"dbt build failed on synthetic data:\n{res.stdout}\n{res.stderr}"

    return {"raw": raw, "db": db, "truth": truth, "audit": audit_result}


@pytest.fixture(scope="session")
def truth_file(built) -> dict:
    return json.loads((built["raw"] / "truth.json").read_text())
