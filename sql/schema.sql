-- Star schema for the payments warehouse (DuckDB dialect, portable to Postgres/BigQuery with minor edits)
DROP TABLE IF EXISTS fact_transactions;
DROP TABLE IF EXISTS rejected_transactions;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_merchant;
DROP TABLE IF EXISTS dim_date;

CREATE TABLE dim_customer (
    customer_id         VARCHAR PRIMARY KEY,
    signup_date         DATE NOT NULL,
    state               VARCHAR,
    acquisition_channel VARCHAR,
    kyc_tier            INTEGER,
    age                 INTEGER,
    churn_date          DATE
);

CREATE TABLE dim_merchant (
    merchant_id   VARCHAR PRIMARY KEY,
    merchant_name VARCHAR,
    category      VARCHAR,
    state         VARCHAR
);

CREATE TABLE dim_date (
    date_key    INTEGER PRIMARY KEY,   -- yyyymmdd surrogate key
    date        DATE NOT NULL,
    year        INTEGER,
    quarter     INTEGER,
    month       INTEGER,
    month_name  VARCHAR,
    day_of_week VARCHAR,
    is_weekend  BOOLEAN
);

CREATE TABLE fact_transactions (
    transaction_id VARCHAR PRIMARY KEY,
    customer_id    VARCHAR NOT NULL,
    merchant_id    VARCHAR,            -- null for non-merchant flows (transfers, airtime, ...)
    date_key       INTEGER NOT NULL,
    txn_timestamp  TIMESTAMP NOT NULL,
    txn_hour       INTEGER,
    txn_type       VARCHAR,
    channel        VARCHAR,
    amount_ngn     DOUBLE NOT NULL,
    status         VARCHAR NOT NULL,
    is_fraud       BOOLEAN
);

-- Quarantine: every rejected row keeps its reason for triage
CREATE TABLE rejected_transactions (
    transaction_id VARCHAR,
    customer_id    VARCHAR,
    amount_ngn     DOUBLE,
    status         VARCHAR,
    reject_reason  VARCHAR
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id        VARCHAR,
    run_ts        TIMESTAMP,
    rows_in       BIGINT,
    duplicates    BIGINT,
    rows_loaded   BIGINT,
    rows_rejected BIGINT,
    checks_passed BOOLEAN
);
