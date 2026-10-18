"""
Build the staging layer from raw and validate it.

Usage:
    python staging/run_staging.py
"""
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

SQL_DIR = Path("sql/staging")

# (label, query returning one number, expected number or query returning the expected number)
CHECKS = [
    # row counts: staging must not lose rows (except where we deliberately collapse)
    ("customers rows",      "SELECT count(*) FROM staging.customers",       "SELECT count(*) FROM raw.customers"),
    ("sellers rows",        "SELECT count(*) FROM staging.sellers",         "SELECT count(*) FROM raw.sellers"),
    ("products rows",       "SELECT count(*) FROM staging.products",        "SELECT count(*) FROM raw.products"),
    ("orders rows",         "SELECT count(*) FROM staging.orders",          "SELECT count(*) FROM raw.orders"),
    ("order_items rows",    "SELECT count(*) FROM staging.order_items",     "SELECT count(*) FROM raw.order_items"),
    ("order_payments rows", "SELECT count(*) FROM staging.order_payments",  "SELECT count(*) FROM raw.order_payments"),
    ("order_reviews rows (deduped on review_id+order_id)",
     "SELECT count(*) FROM staging.order_reviews",
     "SELECT count(*) FROM (SELECT DISTINCT review_id, order_id FROM raw.order_reviews) x"),
    ("geolocation rows (one per zip, inside Brazil)",
     "SELECT count(*) FROM staging.geolocation",
     """SELECT count(DISTINCT geolocation_zip_code_prefix) FROM raw.geolocation
        WHERE geolocation_lat::numeric BETWEEN -34 AND 6 AND geolocation_lng::numeric BETWEEN -74 AND -34"""),
    ("category_translation rows (71 + 2 manual)", "SELECT count(*) FROM staging.category_translation", "73"),
    # flags must reproduce what the profiling report found on raw
    ("flag_delivered_no_date",              "SELECT count(*) FROM staging.orders WHERE flag_delivered_no_date", "8"),
    ("flag_delivery_date_not_delivered",    "SELECT count(*) FROM staging.orders WHERE flag_delivery_date_not_delivered", "6"),
    ("flag_carrier_before_purchase",        "SELECT count(*) FROM staging.orders WHERE flag_carrier_before_purchase", "166"),
    ("flag_delivered_before_carrier",       "SELECT count(*) FROM staging.orders WHERE flag_delivered_before_carrier", "23"),
    ("flag_payment_mismatch",               "SELECT count(*) FROM staging.orders WHERE flag_payment_mismatch", "249"),
    ("orders without items",                "SELECT count(*) FROM staging.orders WHERE NOT has_items", "775"),
    ("orders without payments",             "SELECT count(*) FROM staging.orders WHERE NOT has_payment", "1"),
    ("products missing category",           "SELECT count(*) FROM staging.products WHERE flag_missing_category", "610"),
    ("products with no English name left (excl. missing category)",
     "SELECT count(*) FROM staging.products WHERE category_name_en = 'unknown' AND NOT flag_missing_category", "0"),
    ("products zero weight -> NULL",        "SELECT count(*) FROM staging.products WHERE flag_zero_weight", "4"),
    ("payments installments fixed",         "SELECT count(*) FROM staging.order_payments WHERE flag_installments_fixed", "2"),
    ("payments type not_defined",           "SELECT count(*) FROM staging.order_payments WHERE flag_type_not_defined", "3"),
    ("customers zip not in geolocation",    "SELECT count(*) FROM staging.customers WHERE NOT zip_in_geolocation", None),   # informational
    ("sellers with suspect city",           "SELECT count(*) FROM staging.sellers WHERE flag_city_suspect", None),          # informational
    ("order_items shipping_limit outliers", "SELECT count(*) FROM staging.order_items WHERE flag_shipping_limit_outlier", None),  # informational
    ("orders counted as valid sales",       "SELECT count(*) FROM staging.orders WHERE is_valid_sale", None),               # informational
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


def one(cur, q):
    cur.execute(q)
    return cur.fetchone()[0]


def main():
    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        sys.exit(f"No .sql files in {SQL_DIR}")

    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            for f in files:
                text = f.read_text(encoding="utf-8-sig")
                if not text.strip():
                    sys.exit(f"\n{f.name} is EMPTY ({f.stat().st_size} bytes). "
                             "Save the file in VS Code (Ctrl+S) or copy it again, then re-run.")
                print(f"Running {f.name} ({f.stat().st_size:,} bytes) ...")
                cur.execute(text)

            print(f"\n{'check':62} {'actual':>10} {'expected':>10}")
            print("-" * 84)
            bad = 0
            for label, q, exp in CHECKS:
                actual = one(cur, q)
                if exp is None:
                    print(f"{label:62} {actual:>10,} {'(info)':>10}")
                    continue
                expected = int(exp) if exp.isdigit() else one(cur, exp)
                ok = actual == expected
                bad += not ok
                print(f"{label:62} {actual:>10,} {expected:>10,}  {'OK' if ok else '<-- MISMATCH'}")
        print("\nStaging built." if not bad else f"\nStaging built, but {bad} check(s) differ. Send me this output.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()