import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gen_data import make_customers, make_dirty, make_merchants, make_transactions  # noqa: E402
from pipeline.etl import transform_transactions  # noqa: E402
from pipeline.run_pipeline import run  # noqa: E402


def _tx(**over):
    base = dict(transaction_id="T1", customer_id="C1", merchant_id=None, txn_timestamp="2025-01-01 10:00:00",
                txn_type="transfer", channel="app", amount_ngn=100.0, status="success", is_fraud=0)
    base.update(over)
    return base


def test_status_normalised_and_duplicates_removed():
    df = pd.DataFrame([_tx(status=" SUCCESS "), _tx(), _tx(transaction_id="T2", status="Failed")])
    res = transform_transactions(df, {"C1"})
    assert res.duplicates_removed == 1
    assert set(res.clean["status"]) == {"success", "failed"}


def test_bad_rows_are_quarantined_with_reason():
    df = pd.DataFrame([
        _tx(transaction_id="A", amount_ngn=np.nan),
        _tx(transaction_id="B", amount_ngn=-5),
        _tx(transaction_id="C", customer_id="NOPE"),
        _tx(transaction_id="D", status="weird"),
        _tx(transaction_id="E"),
    ])
    res = transform_transactions(df, {"C1"})
    reasons = dict(zip(res.rejected["transaction_id"], res.rejected["reject_reason"]))
    assert reasons == {"A": "missing_amount", "B": "non_positive_amount", "C": "orphan_customer", "D": "invalid_status"}
    assert list(res.clean["transaction_id"]) == ["E"]


def test_end_to_end_reconciles(tmp_path):
    rng = np.random.default_rng(1)
    cust = make_customers(rng, 300)
    merch = make_merchants(rng, 20)
    tx = make_dirty(rng, make_transactions(rng, cust, merch))
    raw = tmp_path / "raw"
    raw.mkdir()
    cust.to_csv(raw / "customers.csv", index=False)
    merch.to_csv(raw / "merchants.csv", index=False)
    tx.to_csv(raw / "transactions.csv", index=False)
    pd.DataFrame({"loan_id": []}).to_csv(raw / "loans.csv", index=False)

    assert run(raw, tmp_path / "wh.duckdb") is True
    con = duckdb.connect(str(tmp_path / "wh.duckdb"))
    loaded, rejected = con.execute("SELECT (SELECT count(*) FROM fact_transactions), (SELECT count(*) FROM rejected_transactions)").fetchone()
    assert loaded + rejected + con.execute("SELECT duplicates FROM pipeline_runs").fetchone()[0] == len(tx)
