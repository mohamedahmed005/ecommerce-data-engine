"""
Profile the `raw` schema and run data-quality checks.

Outputs
- dq.column_profile : per-column stats (rows, nulls, distinct, min, max)
- dq.check_results  : one row per check per run (failed_rows / total_rows)
- docs/profiling_report.md : readable summary for the project documentation

Usage:
    python profiling/profile_raw.py
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

RAW_TABLES = [
    "customers", "geolocation", "order_items", "order_payments",
    "order_reviews", "orders", "products", "sellers",
    "product_category_translation",
]

DDL = """
CREATE SCHEMA IF NOT EXISTS dq;
CREATE TABLE IF NOT EXISTS dq.column_profile (
    run_id uuid, run_at timestamptz, table_name text, column_name text,
    total_rows bigint, null_rows bigint, null_pct numeric(6,2),
    distinct_values bigint, min_value text, max_value text
);
CREATE TABLE IF NOT EXISTS dq.check_results (
    run_id uuid, run_at timestamptz, check_name text, table_name text,
    category text, severity text, description text,
    failed_rows bigint, total_rows bigint, fail_pct numeric(7,3), status text
);
"""

# (name, table, category, severity, description, failed_sql, total_sql)
CHECKS = [
    # ---------- Uniqueness ----------
    ("pk_customers_customer_id", "customers", "uniqueness", "high",
     "customer_id must be unique",
     "SELECT count(*) - count(DISTINCT customer_id) FROM raw.customers",
     "SELECT count(*) FROM raw.customers"),
    ("pk_orders_order_id", "orders", "uniqueness", "high",
     "order_id must be unique",
     "SELECT count(*) - count(DISTINCT order_id) FROM raw.orders",
     "SELECT count(*) FROM raw.orders"),
    ("pk_products_product_id", "products", "uniqueness", "high",
     "product_id must be unique",
     "SELECT count(*) - count(DISTINCT product_id) FROM raw.products",
     "SELECT count(*) FROM raw.products"),
    ("pk_sellers_seller_id", "sellers", "uniqueness", "high",
     "seller_id must be unique",
     "SELECT count(*) - count(DISTINCT seller_id) FROM raw.sellers",
     "SELECT count(*) FROM raw.sellers"),
    ("pk_order_items", "order_items", "uniqueness", "high",
     "(order_id, order_item_id) must be unique",
     "SELECT count(*) - count(DISTINCT (order_id, order_item_id)) FROM raw.order_items",
     "SELECT count(*) FROM raw.order_items"),
    ("pk_order_payments", "order_payments", "uniqueness", "high",
     "(order_id, payment_sequential) must be unique",
     "SELECT count(*) - count(DISTINCT (order_id, payment_sequential)) FROM raw.order_payments",
     "SELECT count(*) FROM raw.order_payments"),
    ("pk_order_reviews_review_id", "order_reviews", "uniqueness", "medium",
     "review_id should be unique (known to repeat in Olist)",
     "SELECT count(*) - count(DISTINCT review_id) FROM raw.order_reviews",
     "SELECT count(*) FROM raw.order_reviews"),
    ("dup_geolocation_rows", "geolocation", "uniqueness", "low",
     "fully duplicated geolocation rows (same zip/lat/lng/city/state)",
     "SELECT count(*) - count(DISTINCT (geolocation_zip_code_prefix, geolocation_lat, geolocation_lng, geolocation_city, geolocation_state)) FROM raw.geolocation",
     "SELECT count(*) FROM raw.geolocation"),

    # ---------- Referential integrity ----------
    ("fk_orders_customer", "orders", "integrity", "high",
     "orders.customer_id must exist in customers",
     "SELECT count(*) FROM raw.orders o LEFT JOIN raw.customers c USING (customer_id) WHERE c.customer_id IS NULL",
     "SELECT count(*) FROM raw.orders"),
    ("fk_items_order", "order_items", "integrity", "high",
     "order_items.order_id must exist in orders",
     "SELECT count(*) FROM raw.order_items i LEFT JOIN raw.orders o USING (order_id) WHERE o.order_id IS NULL",
     "SELECT count(*) FROM raw.order_items"),
    ("fk_items_product", "order_items", "integrity", "high",
     "order_items.product_id must exist in products",
     "SELECT count(*) FROM raw.order_items i LEFT JOIN raw.products p USING (product_id) WHERE p.product_id IS NULL",
     "SELECT count(*) FROM raw.order_items"),
    ("fk_items_seller", "order_items", "integrity", "high",
     "order_items.seller_id must exist in sellers",
     "SELECT count(*) FROM raw.order_items i LEFT JOIN raw.sellers s USING (seller_id) WHERE s.seller_id IS NULL",
     "SELECT count(*) FROM raw.order_items"),
    ("fk_payments_order", "order_payments", "integrity", "high",
     "order_payments.order_id must exist in orders",
     "SELECT count(*) FROM raw.order_payments p LEFT JOIN raw.orders o USING (order_id) WHERE o.order_id IS NULL",
     "SELECT count(*) FROM raw.order_payments"),
    ("fk_reviews_order", "order_reviews", "integrity", "high",
     "order_reviews.order_id must exist in orders",
     "SELECT count(*) FROM raw.order_reviews r LEFT JOIN raw.orders o USING (order_id) WHERE o.order_id IS NULL",
     "SELECT count(*) FROM raw.order_reviews"),
    ("fk_products_category_translation", "products", "integrity", "medium",
     "product_category_name should have an English translation",
     """SELECT count(*) FROM raw.products p
        LEFT JOIN raw.product_category_translation t USING (product_category_name)
        WHERE p.product_category_name IS NOT NULL AND t.product_category_name IS NULL""",
     "SELECT count(*) FROM raw.products WHERE product_category_name IS NOT NULL"),
    ("fk_customers_zip_geolocation", "customers", "integrity", "low",
     "customer zip prefix should exist in geolocation",
     """SELECT count(*) FROM raw.customers c
        WHERE NOT EXISTS (SELECT 1 FROM raw.geolocation g
                          WHERE g.geolocation_zip_code_prefix = c.customer_zip_code_prefix)""",
     "SELECT count(*) FROM raw.customers"),
    ("orders_without_items", "orders", "integrity", "medium",
     "every order should have at least one item",
     "SELECT count(*) FROM raw.orders o WHERE NOT EXISTS (SELECT 1 FROM raw.order_items i WHERE i.order_id = o.order_id)",
     "SELECT count(*) FROM raw.orders"),
    ("orders_without_payments", "orders", "integrity", "medium",
     "every order should have at least one payment",
     "SELECT count(*) FROM raw.orders o WHERE NOT EXISTS (SELECT 1 FROM raw.order_payments p WHERE p.order_id = o.order_id)",
     "SELECT count(*) FROM raw.orders"),

    # ---------- Completeness ----------
    ("products_null_category", "products", "completeness", "medium",
     "product_category_name is null",
     "SELECT count(*) FROM raw.products WHERE product_category_name IS NULL",
     "SELECT count(*) FROM raw.products"),
    ("products_null_dimensions", "products", "completeness", "medium",
     "weight or any dimension is null",
     """SELECT count(*) FROM raw.products WHERE product_weight_g IS NULL OR product_length_cm IS NULL
        OR product_height_cm IS NULL OR product_width_cm IS NULL""",
     "SELECT count(*) FROM raw.products"),
    ("delivered_without_delivery_date", "orders", "completeness", "high",
     "status = delivered but order_delivered_customer_date is null",
     "SELECT count(*) FROM raw.orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NULL",
     "SELECT count(*) FROM raw.orders WHERE order_status = 'delivered'"),
    ("reviews_without_comment", "order_reviews", "completeness", "low",
     "review has no comment message (informational)",
     "SELECT count(*) FROM raw.order_reviews WHERE review_comment_message IS NULL",
     "SELECT count(*) FROM raw.order_reviews"),

    # ---------- Validity / business rules ----------
    ("orders_invalid_status", "orders", "validity", "medium",
     "order_status outside the known set",
     """SELECT count(*) FROM raw.orders WHERE order_status NOT IN
        ('created','approved','invoiced','processing','shipped','delivered','unavailable','canceled')""",
     "SELECT count(*) FROM raw.orders"),
    ("items_non_positive_price", "order_items", "validity", "high",
     "price <= 0",
     "SELECT count(*) FROM raw.order_items WHERE price::numeric <= 0",
     "SELECT count(*) FROM raw.order_items"),
    ("items_negative_freight", "order_items", "validity", "high",
     "freight_value < 0",
     "SELECT count(*) FROM raw.order_items WHERE freight_value::numeric < 0",
     "SELECT count(*) FROM raw.order_items"),
    ("payments_negative_value", "order_payments", "validity", "high",
     "payment_value < 0",
     "SELECT count(*) FROM raw.order_payments WHERE payment_value::numeric < 0",
     "SELECT count(*) FROM raw.order_payments"),
    ("payments_zero_installments", "order_payments", "validity", "medium",
     "payment_installments = 0 (should be >= 1)",
     "SELECT count(*) FROM raw.order_payments WHERE payment_installments::int = 0",
     "SELECT count(*) FROM raw.order_payments"),
    ("payments_not_defined_type", "order_payments", "validity", "low",
     "payment_type = 'not_defined'",
     "SELECT count(*) FROM raw.order_payments WHERE payment_type = 'not_defined'",
     "SELECT count(*) FROM raw.order_payments"),
    ("reviews_score_out_of_range", "order_reviews", "validity", "high",
     "review_score outside 1-5",
     "SELECT count(*) FROM raw.order_reviews WHERE review_score::int NOT BETWEEN 1 AND 5",
     "SELECT count(*) FROM raw.order_reviews"),
    ("products_zero_weight", "products", "validity", "medium",
     "product_weight_g = 0",
     "SELECT count(*) FROM raw.products WHERE product_weight_g::numeric = 0",
     "SELECT count(*) FROM raw.products"),
    ("customers_invalid_state", "customers", "validity", "low",
     "customer_state is not a 2-letter code",
     "SELECT count(*) FROM raw.customers WHERE customer_state !~ '^[A-Z]{2}$'",
     "SELECT count(*) FROM raw.customers"),
    ("geolocation_outside_brazil", "geolocation", "validity", "medium",
     "lat/lng outside Brazil's bounding box",
     """SELECT count(*) FROM raw.geolocation
        WHERE geolocation_lat::numeric NOT BETWEEN -34 AND 6
           OR geolocation_lng::numeric NOT BETWEEN -74 AND -34""",
     "SELECT count(*) FROM raw.geolocation"),

    # ---------- Timeliness / logical order of dates ----------
    ("delivered_before_purchase", "orders", "consistency", "high",
     "delivered date earlier than purchase timestamp",
     """SELECT count(*) FROM raw.orders
        WHERE order_delivered_customer_date::timestamp < order_purchase_timestamp::timestamp""",
     "SELECT count(*) FROM raw.orders WHERE order_delivered_customer_date IS NOT NULL"),
    ("carrier_before_purchase", "orders", "consistency", "high",
     "carrier pickup earlier than purchase timestamp",
     """SELECT count(*) FROM raw.orders
        WHERE order_delivered_carrier_date::timestamp < order_purchase_timestamp::timestamp""",
     "SELECT count(*) FROM raw.orders WHERE order_delivered_carrier_date IS NOT NULL"),
    ("delivered_before_carrier", "orders", "consistency", "medium",
     "customer delivery earlier than carrier pickup",
     """SELECT count(*) FROM raw.orders
        WHERE order_delivered_customer_date::timestamp < order_delivered_carrier_date::timestamp""",
     "SELECT count(*) FROM raw.orders WHERE order_delivered_customer_date IS NOT NULL AND order_delivered_carrier_date IS NOT NULL"),
    ("non_delivered_with_delivery_date", "orders", "consistency", "medium",
     "has a delivered date but status is not delivered",
     "SELECT count(*) FROM raw.orders WHERE order_status <> 'delivered' AND order_delivered_customer_date IS NOT NULL",
     "SELECT count(*) FROM raw.orders WHERE order_delivered_customer_date IS NOT NULL"),
    ("review_before_purchase", "order_reviews", "consistency", "medium",
     "review created before the order was placed",
     """SELECT count(*) FROM raw.order_reviews r JOIN raw.orders o USING (order_id)
        WHERE r.review_creation_date::timestamp < o.order_purchase_timestamp::timestamp""",
     "SELECT count(*) FROM raw.order_reviews"),
    ("payment_vs_items_mismatch", "orders", "consistency", "medium",
     "sum(payments) differs from sum(price+freight) by more than 1.00",
     """SELECT count(*) FROM (
          SELECT i.order_id, i.total AS items_total, p.total AS paid_total
          FROM (SELECT order_id, sum(price::numeric + freight_value::numeric) total
                FROM raw.order_items GROUP BY order_id) i
          JOIN (SELECT order_id, sum(payment_value::numeric) total
                FROM raw.order_payments GROUP BY order_id) p USING (order_id)
          WHERE abs(i.total - p.total) > 1.00) x""",
     """SELECT count(*) FROM (SELECT DISTINCT order_id FROM raw.order_items) a
        JOIN (SELECT DISTINCT order_id FROM raw.order_payments) b USING (order_id)"""),
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


def profile_columns(cur, run_id, run_at):
    rows_out = []
    for table in RAW_TABLES:
        cur.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema='raw' AND table_name=%s AND column_name NOT LIKE '\\_%%'
               ORDER BY ordinal_position""",
            (table,),
        )
        for (col,) in cur.fetchall():
            ident = sql.Identifier("raw", table)
            c = sql.Identifier(col)
            cur.execute(
                sql.SQL("""SELECT count(*), count(*) - count({c}), count(DISTINCT {c}),
                                  min({c}), max({c}) FROM {t}""").format(c=c, t=ident)
            )
            total, nulls, distinct, mn, mx = cur.fetchone()
            pct = round(100.0 * nulls / total, 2) if total else 0
            rows_out.append((str(run_id), run_at, table, col, total, nulls, pct, distinct,
                             (mn or "")[:80] if mn else None, (mx or "")[:80] if mx else None))
    cur.executemany(
        "INSERT INTO dq.column_profile VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows_out
    )
    return rows_out


def run_checks(cur, run_id, run_at):
    results = []
    for name, table, cat, sev, desc, failed_sql, total_sql in CHECKS:
        try:
            cur.execute(failed_sql); failed = cur.fetchone()[0]
            cur.execute(total_sql);  total = cur.fetchone()[0]
            pct = round(100.0 * failed / total, 3) if total else 0
            status = "PASS" if failed == 0 else "FAIL"
        except Exception as e:  # keep going; record the error
            cur.connection.rollback()
            failed, total, pct, status = None, None, None, f"ERROR: {str(e).splitlines()[0][:80]}"
        results.append((str(run_id), run_at, name, table, cat, sev, desc, failed, total, pct, status))
        flag = "✓" if status == "PASS" else "✗"
        print(f"  {flag} {name:38} {failed if failed is not None else '-':>8} / {total if total is not None else '-'}")
    cur.executemany(
        "INSERT INTO dq.check_results VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", results
    )
    return results


def write_report(profile, checks, run_at):
    out = Path("docs"); out.mkdir(exist_ok=True)
    lines = [f"# Raw Data Profiling Report", f"_Generated: {run_at:%Y-%m-%d %H:%M UTC}_", "",
             "## 1. Data quality checks", "",
             "| Check | Table | Category | Severity | Failed | Total | Fail % | Status |",
             "|---|---|---|---|---:|---:|---:|---|"]
    order = {"high": 0, "medium": 1, "low": 2}
    for r in sorted(checks, key=lambda r: (r[10] == "PASS", order.get(r[5], 3))):
        lines.append(f"| {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[7]} | {r[8]} | {r[9]} | {r[10]} |")
    lines += ["", "## 2. Columns with nulls", "",
              "| Table | Column | Nulls | Null % | Distinct |", "|---|---|---:|---:|---:|"]
    for r in sorted(profile, key=lambda r: -float(r[6])):
        if r[5] > 0:
            lines.append(f"| {r[2]} | {r[3]} | {r[5]:,} | {r[6]} | {r[7]:,} |")
    lines += ["", "## 3. Full column profile", "",
              "| Table | Column | Rows | Nulls | Distinct | Min | Max |", "|---|---|---:|---:|---:|---|---|"]
    for r in profile:
        lines.append(f"| {r[2]} | {r[3]} | {r[4]:,} | {r[5]:,} | {r[7]:,} | {r[8] or ''} | {r[9] or ''} |")
    (out / "profiling_report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    run_id, run_at = uuid.uuid4(), datetime.now(timezone.utc)
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(DDL)
            print("Profiling columns...")
            profile = profile_columns(cur, run_id, run_at)
            print(f"  {len(profile)} columns profiled\n\nRunning checks...")
            checks = run_checks(cur, run_id, run_at)
        write_report(profile, checks, run_at)
        fails = [c for c in checks if c[10] != "PASS"]
        print(f"\n{len(checks) - len(fails)} passed, {len(fails)} need attention.")
        print("Report: docs/profiling_report.md  |  Tables: dq.column_profile, dq.check_results")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
