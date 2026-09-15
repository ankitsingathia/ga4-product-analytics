"""The extract cannot be run in CI (it needs a Google login), so guard its
contract statically: every schema column must be produced by the SQL, and a
table missing a column must be refused rather than half-written."""

from __future__ import annotations

import re
from pathlib import Path

import pyarrow as pa
import pytest

from gpa import schema

SQL = Path(__file__).resolve().parents[1] / "sql" / "bigquery"


@pytest.mark.parametrize("sql_file,sch", [("extract_events.sql", schema.EVENTS), ("extract_items.sql", schema.ITEMS)])
def test_sql_produces_every_schema_column(sql_file, sch):
    sql = (SQL / sql_file).read_text()
    missing = [c for c in sch.names if not re.search(rf"\b{c}\b", sql)]
    assert not missing, f"{sql_file} does not produce {missing}"


def test_conform_refuses_a_table_missing_a_column():
    table = pa.table({"event_name": ["page_view"]})
    with pytest.raises(ValueError, match="missing columns"):
        schema.conform(table, schema.EVENTS)


def test_dbt_and_python_agree_on_the_funnel():
    import yaml

    project = yaml.safe_load((SQL.parents[1] / "dbt" / "dbt_project.yml").read_text())
    assert tuple(project["vars"]["funnel_steps"]) == schema.FUNNEL_STEPS


def test_extract_window_is_92_days():
    from gpa.extract import all_days

    days = all_days()
    assert len(days) == 92 and days[0] == schema.WINDOW_START and days[-1] == schema.WINDOW_END
