"""Synthetic Nigerian fintech dataset generator (reproducible, seeded).

Produces customers, merchants, transactions and loans CSVs that mimic a
wallet / payments / digital-lending business. No real customer data is used.

Usage:
    python gen_data.py --out data/raw [--customers 5000] [--dirty]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

START = pd.Timestamp("2024-01-01")
END = pd.Timestamp("2025-06-30")

STATES = ["Lagos", "Abuja", "Rivers", "Oyo", "Kano", "Enugu", "Kaduna", "Ogun", "Anambra", "Delta"]
STATE_P = [0.34, 0.14, 0.09, 0.08, 0.08, 0.06, 0.06, 0.07, 0.04, 0.04]
CHANNELS_ACQ = ["organic", "referral", "paid_social", "agent", "campus"]
TX_TYPES = ["transfer", "bill_payment", "airtime", "pos_purchase", "card_online", "withdrawal"]
TX_P = [0.30, 0.12, 0.20, 0.16, 0.12, 0.10]
TX_CHANNEL = {"transfer": ["app", "ussd", "web"], "bill_payment": ["app", "web"], "airtime": ["app", "ussd"],
              "pos_purchase": ["pos"], "card_online": ["web", "app"], "withdrawal": ["atm", "agent"]}
AMT_MU = {"transfer": 9.2, "bill_payment": 8.6, "airtime": 6.6, "pos_purchase": 8.4, "card_online": 8.9, "withdrawal": 9.3}
MERCH_CATS = ["grocery", "restaurant", "fuel", "telco", "utilities", "ecommerce", "transport", "betting", "pharmacy", "education"]


def make_customers(rng: np.random.Generator, n: int) -> pd.DataFrame:
    signup = START + pd.to_timedelta(rng.integers(0, (pd.Timestamp("2025-03-31") - START).days, n), unit="D")
    kyc = rng.choice([1, 2, 3], n, p=[0.5, 0.35, 0.15])
    channel = rng.choice(CHANNELS_ACQ, n, p=[0.35, 0.25, 0.2, 0.12, 0.08])
    # churn hazard: tier-1 KYC and paid_social churn faster
    scale = 260 * np.where(kyc == 1, 0.7, np.where(kyc == 3, 1.5, 1.0)) * np.where(channel == "paid_social", 0.75, 1.0)
    life = rng.exponential(scale)
    churn = signup + pd.to_timedelta(np.round(life), unit="D")
    churn = churn.where(churn <= END, pd.NaT)
    return pd.DataFrame({
        "customer_id": [f"C{i:06d}" for i in range(n)],
        "signup_date": signup.strftime("%Y-%m-%d"),
        "state": rng.choice(STATES, n, p=STATE_P),
        "acquisition_channel": channel,
        "kyc_tier": kyc,
        "age": np.clip(rng.normal(31, 8, n), 18, 65).astype(int),
        "churn_date": churn.strftime("%Y-%m-%d"),
    })


def make_merchants(rng: np.random.Generator, n: int = 200) -> pd.DataFrame:
    return pd.DataFrame({
        "merchant_id": [f"M{i:04d}" for i in range(n)],
        "merchant_name": [f"Merchant {i:04d}" for i in range(n)],
        "category": rng.choice(MERCH_CATS, n),
        "state": rng.choice(STATES, n, p=STATE_P),
    })


def make_transactions(rng: np.random.Generator, cust: pd.DataFrame, merch: pd.DataFrame) -> pd.DataFrame:
    signup = pd.to_datetime(cust["signup_date"])
    churn = pd.to_datetime(cust["churn_date"]).fillna(END)
    end = churn.clip(upper=END)
    days = (end - signup).dt.days.clip(lower=1).to_numpy()
    rate = np.where(cust["kyc_tier"] == 1, 0.55, np.where(cust["kyc_tier"] == 2, 0.9, 1.4))  # tx/day
    rate = rate * rng.gamma(2.0, 0.5, len(cust)) * 0.18
    n_tx = rng.poisson(rate * days)
    idx = np.repeat(np.arange(len(cust)), n_tx)
    total = len(idx)
    offs = (rng.random(total) * days[idx]).astype(int)
    hour = np.clip(rng.normal(14, 5, total), 0, 23.99)
    # a little late-night activity
    night = rng.random(total) < 0.04
    hour[night] = rng.uniform(0, 5, night.sum())
    ts = signup.to_numpy()[idx] + pd.to_timedelta(offs, unit="D") + pd.to_timedelta(hour, unit="h")
    ttype = rng.choice(TX_TYPES, total, p=TX_P)
    channel = np.empty(total, dtype=object)
    for t in TX_TYPES:
        m = ttype == t
        channel[m] = rng.choice(TX_CHANNEL[t], m.sum())
    mu = pd.Series(ttype).map(AMT_MU).to_numpy()
    amount = np.round(rng.lognormal(mu, 1.0), 2).clip(50, 5_000_000)
    # fraud model: risk factors multiply a base probability
    days_since_signup = offs
    p = np.full(total, 0.003)
    p *= np.where(amount > 200_000, 4, 1)
    p *= np.where(hour < 5, 3.5, 1)
    p *= np.where(np.isin(ttype, ["card_online"]), 2.5, 1)
    p *= np.where(days_since_signup < 14, 3, 1)
    p *= np.where(np.isin(channel, ["ussd"]), 1.5, 1)
    fraud = rng.random(total) < np.clip(p, 0, 0.5)
    amount = np.where(fraud, np.round(amount * rng.uniform(1.5, 5, total), 2), amount)
    # status: ussd flakier, fraud often reversed
    p_fail = np.where(channel == "ussd", 0.085, 0.03)
    r = rng.random(total)
    status = np.where(r < p_fail, "failed", "success")
    status = np.where(fraud & (rng.random(total) < 0.5), "reversed", status)
    merchant_ids = rng.choice(merch["merchant_id"], total)
    needs_merchant = np.isin(ttype, ["pos_purchase", "card_online", "bill_payment"])
    merchant_ids = np.where(needs_merchant, merchant_ids, None)
    df = pd.DataFrame({
        "transaction_id": [f"T{i:08d}" for i in range(total)],
        "customer_id": cust["customer_id"].to_numpy()[idx],
        "merchant_id": merchant_ids,
        "txn_timestamp": pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M:%S"),
        "txn_type": ttype,
        "channel": channel,
        "amount_ngn": amount,
        "status": status,
        "is_fraud": fraud.astype(int),
    })
    df = df[pd.to_datetime(df["txn_timestamp"]) <= END + pd.Timedelta(days=1)]
    return df.sort_values("txn_timestamp").reset_index(drop=True)


def make_loans(rng: np.random.Generator, cust: pd.DataFrame) -> pd.DataFrame:
    sel = cust.sample(frac=0.3, random_state=int(rng.integers(0, 10_000))).reset_index(drop=True)
    n = len(sel)
    principal = rng.choice([20_000, 50_000, 100_000, 200_000, 500_000], n, p=[0.3, 0.3, 0.2, 0.15, 0.05])
    tenor = rng.choice([1, 3, 6, 12], n, p=[0.3, 0.35, 0.25, 0.1])
    signup = pd.to_datetime(sel["signup_date"])
    latest = (END - pd.Timedelta(days=15))
    span = np.clip((latest - signup).dt.days.to_numpy() - 30, 1, None)
    disb = signup + pd.to_timedelta(30 + (rng.random(n) * span).astype(int), unit="D")
    monthly_rate = rng.choice([0.04, 0.05, 0.06, 0.08], n, p=[0.25, 0.35, 0.25, 0.15])
    due = disb + pd.to_timedelta(tenor * 30, unit="D")
    p_bad = 0.05 + 0.04 * np.log10(principal / 20_000) + np.where(sel["kyc_tier"] == 1, 0.07, 0) + 0.002 * tenor + np.where(sel["acquisition_channel"] == "paid_social", 0.04, 0)
    bad = rng.random(n) < p_bad
    first_miss = disb + pd.to_timedelta((tenor * 30 * rng.uniform(0.3, 1.0, n)).astype(int), unit="D")
    first_miss = first_miss.where(bad & (first_miss <= END), pd.NaT)
    total_due = principal * (1 + monthly_rate * tenor)
    repaid = np.where(first_miss.notna(), total_due * rng.uniform(0.1, 0.7, n), np.where(due <= END, total_due, total_due * np.clip((END - disb).dt.days.to_numpy() / (tenor * 30), 0, 1)))
    status = np.where(first_miss.notna(), "delinquent", np.where(due <= END, "repaid", "active"))
    return pd.DataFrame({
        "loan_id": [f"L{i:06d}" for i in range(n)],
        "customer_id": sel["customer_id"],
        "disbursed_date": disb.dt.strftime("%Y-%m-%d"),
        "principal_ngn": principal,
        "tenor_months": tenor,
        "monthly_rate": monthly_rate,
        "due_date": due.dt.strftime("%Y-%m-%d"),
        "status": status,
        "first_missed_date": first_miss.dt.strftime("%Y-%m-%d"),
        "amount_repaid_ngn": np.round(repaid, 2),
    })


def make_dirty(rng: np.random.Generator, tx: pd.DataFrame) -> pd.DataFrame:
    """Inject realistic data-quality problems for the ETL project to catch."""
    d = tx.copy()
    d["status"] = d["status"].astype(object)
    k = len(d)
    d.loc[rng.choice(k, int(k * 0.01), replace=False), "status"] = "SUCCESS "
    d.loc[rng.choice(k, int(k * 0.005), replace=False), "status"] = "Failed"
    d.loc[rng.choice(k, int(k * 0.004), replace=False), "amount_ngn"] = np.nan
    d.loc[rng.choice(k, int(k * 0.002), replace=False), "amount_ngn"] = -100.0
    d.loc[rng.choice(k, int(k * 0.003), replace=False), "customer_id"] = "C999999"  # orphan keys
    dup = d.sample(int(k * 0.006), random_state=1)
    return pd.concat([d, dup], ignore_index=True).sample(frac=1, random_state=2).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--customers", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dirty", action="store_true", help="inject data-quality issues into transactions")
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cust = make_customers(rng, a.customers)
    merch = make_merchants(rng)
    tx = make_transactions(rng, cust, merch)
    loans = make_loans(rng, cust)
    if a.dirty:
        tx = make_dirty(rng, tx)
    cust.to_csv(out / "customers.csv", index=False)
    merch.to_csv(out / "merchants.csv", index=False)
    tx.to_csv(out / "transactions.csv", index=False)
    loans.to_csv(out / "loans.csv", index=False)
    print(f"customers={len(cust):,} merchants={len(merch):,} transactions={len(tx):,} loans={len(loans):,} -> {out}")


if __name__ == "__main__":
    main()

