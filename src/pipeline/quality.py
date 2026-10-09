"""Post-load data-quality gates. A failed *critical* check fails the pipeline run."""
from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    critical: bool = True


def run_checks(con: duckdb.DuckDBPyConnection, rows_in: int, duplicates: int) -> list[Check]:
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    loaded = q("SELECT count(*) FROM fact_transactions")
    rejected = q("SELECT count(*) FROM rejected_transactions")
    checks = [
        Check("row_reconciliation", rows_in == loaded + rejected + duplicates,
              f"in={rows_in} loaded={loaded} rejected={rejected} dupes={duplicates}"),
        Check("pk_unique_fact", q("SELECT count(*) - count(DISTINCT transaction_id) FROM fact_transactions") == 0,
              "transaction_id unique"),
        Check("fk_customer", q("""SELECT count(*) FROM fact_transactions f
                                  LEFT JOIN dim_customer c USING (customer_id) WHERE c.customer_id IS NULL""") == 0,
              "every transaction has a customer"),
        Check("fk_merchant", q("""SELECT count(*) FROM fact_transactions f
                                  LEFT JOIN dim_merchant m USING (merchant_id)
                                  WHERE f.merchant_id IS NOT NULL AND m.merchant_id IS NULL""") == 0,
              "merchant ids resolve"),
        Check("fk_date", q("""SELECT count(*) FROM fact_transactions f
                              LEFT JOIN dim_date d USING (date_key) WHERE d.date_key IS NULL""") == 0,
              "every transaction date is in dim_date"),
        Check("amount_positive", q("SELECT count(*) FROM fact_transactions WHERE amount_ngn <= 0") == 0,
              "no non-positive amounts"),
        Check("reject_rate_under_2pct", rows_in == 0 or rejected / rows_in < 0.02,
              f"reject rate {rejected / max(rows_in, 1):.2%}", critical=False),
    ]
    return checks
