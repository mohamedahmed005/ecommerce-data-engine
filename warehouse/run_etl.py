"""
Load the warehouse (Gold) from staging and validate it.

Order: 03_load_dimensions.sql -> 04_load_facts.sql -> checks.
Safe to re-run: every run empties the warehouse tables and reloads them.
Run warehouse/run_ddl.py first (the tables must exist).

Usage:
    python warehouse/run_etl.py
"""
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

SQL_DIR = Path("sql/warehouse")
ETL_FILES = ["03_load_dimensions.sql", "04_load_facts.sql"]

W = "warehouse"
# (label, query returning ONE value, expected value / query returning it / None = informational)
CHECKS = [
    # ---- row counts: nothing lost, nothing invented ----
    ("dim_customer rows (= distinct customer_unique_id)",
     f"SELECT count(*) FROM {W}.dim_customer WHERE customer_key <> -1",
     "SELECT count(DISTINCT customer_unique_id) FROM staging.customers"),
    ("dim_seller rows",
     f"SELECT count(*) FROM {W}.dim_seller WHERE seller_key <> -1",
     "SELECT count(*) FROM staging.sellers"),
    ("dim_product rows",
     f"SELECT count(*) FROM {W}.dim_product WHERE product_key <> -1",
     "SELECT count(*) FROM staging.products"),
    ("dim_geography rows (geolocation + missing zips)",
     f"SELECT count(*) FROM {W}.dim_geography WHERE geography_key <> -1",
     """SELECT count(*) FROM (
            SELECT zip_code_prefix FROM staging.geolocation
            UNION SELECT zip_code_prefix FROM staging.customers WHERE NOT zip_in_geolocation
            UNION SELECT zip_code_prefix FROM staging.sellers   WHERE NOT zip_in_geolocation) z"""),
    ("dim_date has no gaps (days = last - first + 1)",
     f"SELECT count(*) FROM {W}.dim_date",
     f"SELECT max(full_date) - min(full_date) + 1 FROM {W}.dim_date"),
    ("fact_sales rows (= staging.order_items)",
     f"SELECT count(*) FROM {W}.fact_sales", "SELECT count(*) FROM staging.order_items"),
    ("fact_payments rows (= staging.order_payments)",
     f"SELECT count(*) FROM {W}.fact_payments", "SELECT count(*) FROM staging.order_payments"),
    ("fact_reviews rows (= staging.order_reviews)",
     f"SELECT count(*) FROM {W}.fact_reviews", "SELECT count(*) FROM staging.order_reviews"),
    # ---- money: totals must match the source to the cent ----
    ("sum(price) fact_sales vs staging",
     f"SELECT round(COALESCE(sum(price),0),2) FROM {W}.fact_sales",
     "SELECT round(COALESCE(sum(price),0),2) FROM staging.order_items"),
    ("sum(freight_value) fact_sales vs staging",
     f"SELECT round(COALESCE(sum(freight_value),0),2) FROM {W}.fact_sales",
     "SELECT round(COALESCE(sum(freight_value),0),2) FROM staging.order_items"),
    ("sum(payment_value) fact_payments vs staging",
     f"SELECT round(COALESCE(sum(payment_value),0),2) FROM {W}.fact_payments",
     "SELECT round(COALESCE(sum(payment_value),0),2) FROM staging.order_payments"),
    # ---- keys: no fact points at Unknown ----
    ("fact_sales with unknown customer", f"SELECT count(*) FROM {W}.fact_sales WHERE customer_key = -1", "0"),
    ("fact_sales with unknown product",  f"SELECT count(*) FROM {W}.fact_sales WHERE product_key  = -1", "0"),
    ("fact_sales with unknown seller",   f"SELECT count(*) FROM {W}.fact_sales WHERE seller_key   = -1", "0"),
    ("fact_payments with unknown customer", f"SELECT count(*) FROM {W}.fact_payments WHERE customer_key = -1", "0"),
    ("fact_reviews with unknown customer",  f"SELECT count(*) FROM {W}.fact_reviews  WHERE customer_key = -1", "0"),
    ("customers/sellers with unknown geography",
     f"""SELECT (SELECT count(*) FROM {W}.dim_customer WHERE geography_key = -1 AND customer_key <> -1)
              + (SELECT count(*) FROM {W}.dim_seller   WHERE geography_key = -1 AND seller_key   <> -1)""", "0"),
    # ---- grain: primary keys already forbid duplicates; this proves it ----
    ("fact_sales duplicate (order_id, order_item_id)",
     f"SELECT count(*) - count(DISTINCT (order_id, order_item_id)) FROM {W}.fact_sales", "0"),
    ("fact_payments duplicate (order_id, payment_sequential)",
     f"SELECT count(*) - count(DISTINCT (order_id, payment_sequential)) FROM {W}.fact_payments", "0"),
    ("fact_reviews duplicate (review_id, order_id)",
     f"SELECT count(*) - count(DISTINCT (review_id, order_id)) FROM {W}.fact_reviews", "0"),
    # ---- flag logic ----
    ("is_valid_sale rows that are not is_valid_item (must be 0)",
     f"SELECT count(*) FROM {W}.fact_sales WHERE is_valid_sale AND NOT is_valid_item", "0"),
    ("is_delivered rows without a delivered date (must be 0)",
     f"SELECT count(*) FROM {W}.fact_sales WHERE is_delivered AND delivered_date_key IS NULL", "0"),
    ("canceled/unavailable rows counted as valid sale (must be 0)",
     f"SELECT count(*) FROM {W}.fact_sales WHERE is_valid_sale AND order_status IN ('canceled','unavailable')", "0"),
    ("delivered dates with no delivery_days (must be 0)",
     f"SELECT count(*) FROM {W}.fact_sales WHERE delivered_date_key IS NOT NULL AND delivery_days IS NULL", "0"),
    # ---- informational ----
    ("fact_sales: is_valid_item = false", f"SELECT count(*) FROM {W}.fact_sales WHERE NOT is_valid_item", None),
    ("fact_sales: is_valid_sale = true",  f"SELECT count(*) FROM {W}.fact_sales WHERE is_valid_sale", None),
    ("fact_sales: is_valid_sale = false", f"SELECT count(*) FROM {W}.fact_sales WHERE NOT is_valid_sale", None),
    ("fact_sales: is_delivered = true",   f"SELECT count(*) FROM {W}.fact_sales WHERE is_delivered", None),
    ("fact_sales: negative delivery_days (date anomaly)",
     f"SELECT count(*) FROM {W}.fact_sales WHERE delivery_days < 0", None),
    ("fact_sales: delivered late (delay_days > 0)",
     f"SELECT count(*) FROM {W}.fact_sales WHERE delay_days > 0", None),
    ("fact_reviews: has_comment = true", f"SELECT count(*) FROM {W}.fact_reviews WHERE has_comment", None),
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


def one(cur, query):
    cur.execute(query)
    return cur.fetchone()[0]


def main():
    for name in ETL_FILES:
        if not (SQL_DIR / name).exists():
            sys.exit(f"Missing {SQL_DIR / name}")

    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('warehouse.fact_sales'), to_regclass('staging.orders')")
            wh, st = cur.fetchone()
            if wh is None:
                sys.exit("warehouse tables are missing. Run: python warehouse/run_ddl.py")
            if st is None:
                sys.exit("staging tables are missing. Run: python staging/run_staging.py")

            for name in ETL_FILES:
                text = (SQL_DIR / name).read_text(encoding="utf-8-sig")
                if not text.strip():
                    sys.exit(f"\n{name} is EMPTY. Save the file (Ctrl+S) and re-run.")
                print(f"Running {name} ...")
                cur.execute(text)

        print("\nValidation")
        print(f"{'check':62} {'actual':>14} {'expected':>14}  status")
        print("-" * 104)
        bad = 0
        with conn.cursor() as cur:
            for label, query, expected in CHECKS:
                actual = one(cur, query)
                if expected is None:
                    print(f"{label:62} {str(actual):>14} {'':>14}  info")
                    continue
                exp = one(cur, expected) if expected.upper().startswith("SELECT") else expected
                ok = str(actual) == str(exp)
                bad += not ok
                print(f"{label:62} {str(actual):>14} {str(exp):>14}  {'OK' if ok else '<-- MISMATCH'}")
        print("\nWarehouse loaded and validated." if not bad
              else f"\n{bad} check(s) failed. Send me this output.")
        sys.exit(1 if bad else 0)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
