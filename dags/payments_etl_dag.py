"""Airflow DAG that orchestrates the same pipeline daily.

Each stage is a separate task so a failure is visible, retryable and alertable at the
right granularity. (Requires apache-airflow; not needed to run the pipeline locally.)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from airflow.decorators import dag, task

RAW = Path("/opt/airflow/data/raw")
DB = Path("/opt/airflow/data/warehouse.duckdb")


@dag(
    dag_id="payments_etl",
    schedule="0 2 * * *",  # 02:00 daily, after the core-banking extract lands
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["payments", "etl"],
)
def payments_etl():
    @task
    def generate_extract():
        from gen_data import main  # stand-in for the SFTP/API pull from the source system
        main()

    @task
    def run_pipeline():
        from pipeline.run_pipeline import run
        if not run(RAW, DB):
            raise ValueError("Critical data-quality check failed - blocking downstream consumers")

    generate_extract() >> run_pipeline()


payments_etl()
