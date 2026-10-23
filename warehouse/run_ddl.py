"""
Create the warehouse (Gold) tables: 5 dimensions + 3 facts.
Re-runnable: it drops and recreates the warehouse tables each time.

Usage:
    python warehouse/run_ddl.py
"""
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

SQL_DIR = Path("sql/warehouse")
DDL_FILES = ["01_dimensions.sql", "02_facts.sql"]   # 03/04 are the ETL (run_etl.py)

EXPECTED_TABLES = [
    "dim_customer", "dim_date", "dim_geography", "dim_product", "dim_seller",
    "fact_payments", "fact_reviews", "fact_sales",
]


def connect():
    load_dotenv()
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        user=os.getenv("POSTGRES_USER", "ecom"),
        password=os.getenv("POSTGRES_PASSWORD", "ecom_pass"),
        dbname=os.getenv("POSTGRES_DB", "ecom"),
    )


def main():
    files = [SQL_DIR / n for n in DDL_FILES]
    missing = [f for f in files if not f.exists()]
    if missing:
        sys.exit(f"Missing: {[str(m) for m in missing]}")

    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            for f in files:
                text = f.read_text(encoding="utf-8-sig")
                if not text.strip():
                    sys.exit(f"\n{f.name} is EMPTY. Save the file (Ctrl+S) and re-run.")
                print(f"Running {f.name} ({f.stat().st_size:,} bytes) ...")
                cur.execute(text)

            cur.execute("""SELECT table_name FROM information_schema.tables
                           WHERE table_schema = 'warehouse' ORDER BY table_name""")
            found = [r[0] for r in cur.fetchall()]
            print(f"\n{'table':20} status")
            print("-" * 30)
            bad = 0
            for t in EXPECTED_TABLES:
                ok = t in found
                bad += not ok
                print(f"{t:20} {'OK' if ok else '<-- MISSING'}")
            cur.execute("""SELECT count(*) FROM warehouse.dim_customer WHERE customer_key = -1""")
            print(f"\nUnknown member rows present: {cur.fetchone()[0]} (expected 1 per dimension)")
        print("\nWarehouse DDL applied." if not bad else f"\n{bad} table(s) missing. Send me this output.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
