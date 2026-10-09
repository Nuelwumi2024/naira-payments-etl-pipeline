"""Extract -> Transform -> Load for the payments warehouse.

Design notes
------------
* Bad rows are *quarantined with a reason*, never silently dropped, so that
  row counts always reconcile: rows_in = rows_loaded + rows_rejected + duplicates.
* Load is a full refresh and idempotent (re-running yields the same warehouse).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

VALID_STATUS = {"success", "failed", "reversed"}


@dataclass
class TransformResult:
    clean: pd.DataFrame
    rejected: pd.DataFrame
    duplicates_removed: int
    rows_in: int


def extract(raw_dir: Path) -> dict[str, pd.DataFrame]:
    """Read raw CSV extracts as-is (everything typed loosely, cleaned later)."""
    return {name: pd.read_csv(raw_dir / f"{name}.csv") for name in ("customers", "merchants", "transactions", "loans")}


def transform_transactions(tx: pd.DataFrame, valid_customers: set[str]) -> TransformResult:
    rows_in = len(tx)
    df = tx.copy()

    # 1. standardise categorical text (' SUCCESS ' -> 'success')
    df["status"] = df["status"].astype(str).str.strip().str.lower()
    df["txn_timestamp"] = pd.to_datetime(df["txn_timestamp"], errors="coerce")

    # 2. de-duplicate on the business key, keeping the first occurrence
    before = len(df)
    df = df.drop_duplicates(subset="transaction_id", keep="first")
    duplicates_removed = before - len(df)

    # 3. quarantine rows that break rules, tagging the first failing reason
    reason = pd.Series("", index=df.index)
    reason = reason.mask((reason == "") & df["amount_ngn"].isna(), "missing_amount")
    reason = reason.mask((reason == "") & (df["amount_ngn"] <= 0), "non_positive_amount")
    reason = reason.mask((reason == "") & ~df["status"].isin(VALID_STATUS), "invalid_status")
    reason = reason.mask((reason == "") & df["txn_timestamp"].isna(), "bad_timestamp")
    reason = reason.mask((reason == "") & ~df["customer_id"].isin(valid_customers), "orphan_customer")

    rejected = df[reason != ""].assign(reject_reason=reason[reason != ""])
    clean = df[reason == ""].copy()
    clean["txn_date"] = clean["txn_timestamp"].dt.date
    clean["txn_hour"] = clean["txn_timestamp"].dt.hour
    return TransformResult(clean, rejected, duplicates_removed, rows_in)


def build_dim_date(start: str, end: str) -> pd.DataFrame:
    d = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    return pd.DataFrame({
        "date_key": d["date"].dt.strftime("%Y%m%d").astype(int),
        "date": d["date"].dt.date,
        "year": d["date"].dt.year,
        "quarter": d["date"].dt.quarter,
        "month": d["date"].dt.month,
        "month_name": d["date"].dt.month_name(),
        "day_of_week": d["date"].dt.day_name(),
        "is_weekend": d["date"].dt.dayofweek >= 5,
    })


def load(con: duckdb.DuckDBPyConnection, schema_sql: str, customers, merchants, clean, rejected, dim_date) -> None:
    con.execute(schema_sql)
    con.register("customers_df", customers)
    con.register("merchants_df", merchants)
    con.register("dim_date_df", dim_date)
    con.register("clean_df", clean)
    con.register("rejected_df", rejected)

    con.execute("""INSERT INTO dim_customer
        SELECT customer_id, CAST(signup_date AS DATE), state, acquisition_channel, kyc_tier, age,
               CAST(churn_date AS DATE) FROM customers_df""")
    con.execute("INSERT INTO dim_merchant SELECT merchant_id, merchant_name, category, state FROM merchants_df")
    con.execute("INSERT INTO dim_date SELECT * FROM dim_date_df")
    con.execute("""INSERT INTO fact_transactions
        SELECT transaction_id, customer_id, merchant_id,
               CAST(strftime(txn_timestamp, '%Y%m%d') AS INTEGER) AS date_key,
               txn_timestamp, txn_hour, txn_type, channel, amount_ngn, status, CAST(is_fraud AS BOOLEAN)
        FROM clean_df""")
    con.execute("""INSERT INTO rejected_transactions
        SELECT transaction_id, customer_id, CAST(amount_ngn AS DOUBLE), status, reject_reason FROM rejected_df""")
