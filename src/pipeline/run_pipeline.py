"""CLI entrypoint:  python -m pipeline.run_pipeline --raw data/raw --db data/warehouse.duckdb"""
from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from pipeline.etl import build_dim_date, extract, load, transform_transactions
from pipeline.quality import run_checks

log = logging.getLogger("pipeline")
SCHEMA = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"


def run(raw_dir: Path, db_path: Path) -> bool:
    run_id = uuid.uuid4().hex[:8]
    log.info("run %s: extracting from %s", run_id, raw_dir)
    data = extract(raw_dir)

    res = transform_transactions(data["transactions"], set(data["customers"]["customer_id"]))
    log.info("transform: in=%d clean=%d rejected=%d dupes=%d",
             res.rows_in, len(res.clean), len(res.rejected), res.duplicates_removed)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    schema_sql = SCHEMA.read_text()
    dim_date = build_dim_date("2024-01-01", "2025-07-01")
    load(con, schema_sql, data["customers"], data["merchants"], res.clean, res.rejected, dim_date)

    checks = run_checks(con, res.rows_in, res.duplicates_removed)
    for c in checks:
        log.log(logging.INFO if c.passed else logging.ERROR, "check %-24s %s  (%s)", c.name, "PASS" if c.passed else "FAIL", c.detail)
    ok = all(c.passed for c in checks if c.critical)

    con.execute("INSERT INTO pipeline_runs VALUES (?,?,?,?,?,?,?)",
                [run_id, datetime.now(timezone.utc).replace(tzinfo=None), res.rows_in, res.duplicates_removed,
                 len(res.clean), len(res.rejected), ok])
    con.close()
    log.info("run %s finished: %s", run_id, "SUCCESS" if ok else "FAILED")
    return ok


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw", type=Path)
    ap.add_argument("--db", default="data/warehouse.duckdb", type=Path)
    a = ap.parse_args()
    sys.exit(0 if run(a.raw, a.db) else 1)


if __name__ == "__main__":
    main()
