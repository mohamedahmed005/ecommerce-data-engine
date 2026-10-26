"""Warehouse (Gold layer) data quality checks.

Runs independent tests on the warehouse schema, stores every result in
dq.warehouse_check_results and writes docs/warehouse_dq_report.md.

Each check is one SQL query that returns a single number (the "actual").
The check passes when actual == expected (expected is 0 for most checks).
Severity:  error -> a mismatch is a FAIL and the script exits with code 1
           warn  -> a mismatch is reported as WARN but does not fail the run

Usage (from the project root):
    python warehouse/run_dq_checks.py
"""
import sys
from datetime import datetime
from pathlib import Path

try:
    import psycopg2 as pg
except ImportError:
    import psycopg as pg

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
REPORT_FILE = BASE_DIR / "docs" / "warehouse_dq_report.md"


# ----------------------------------------------------------------------
# Connection (reads .env, same variables as docker-compose)
# ----------------------------------------------------------------------
def load_env(path):
    env = {}
    if not path.exists():
        sys.exit(f"ERROR: .env not found at {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def get_db_config():
    env = load_env(ENV_FILE)
    missing = [k for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB") if k not in env]
    if missing:
        sys.exit(f"ERROR: missing in .env: {', '.join(missing)}")
    return dict(
        host="127.0.0.1",
        port=int(env.get("POSTGRES_PORT", 5432)),
        dbname=env["POSTGRES_DB"],
        user=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
    )


# ----------------------------------------------------------------------
# Check definitions: (category, name, sql, expected, severity)
# ----------------------------------------------------------------------
CHECKS = []


def add(category, name, sql, expected=0, severity="error"):
    CHECKS.append((category, name, " ".join(sql.split()), expected, severity))


def orphan_sql(fact, col, dim, key, nullable):
    """Rows of a fact whose foreign key has no match in the dimension."""
    null_filter = f"f.{col} IS NOT NULL AND " if nullable else ""
    return (
        f"SELECT COUNT(*) FROM warehouse.{fact} f "
        f"LEFT JOIN warehouse.{dim} d ON d.{key} = f.{col} "
        f"WHERE {null_filter}d.{key} IS NULL"
    )


def dup_sql(table, cols):
    return (
        f"SELECT COUNT(*) FROM (SELECT 1 FROM warehouse.{table} "
        f"GROUP BY {cols} HAVING COUNT(*) > 1) t"
    )


def sum_diff_sql(wh_table, wh_col, st_table, st_col):
    return (
        f"SELECT ROUND(CAST(ABS((SELECT SUM({wh_col}) FROM warehouse.{wh_table}) "
        f"- (SELECT SUM({st_col}) FROM staging.{st_table})) AS numeric), 2)"
    )


def count_diff_sql(wh_table, st_table):
    return (
        f"SELECT ABS((SELECT COUNT(*) FROM warehouse.{wh_table}) "
        f"- (SELECT COUNT(*) FROM staging.{st_table}))"
    )


# ---- 1. Reconciliation with staging -----------------------------------
C = "Reconciliation"
add(C, "fact_sales rows = staging.order_items rows", count_diff_sql("fact_sales", "order_items"))
add(C, "fact_payments rows = staging.order_payments rows", count_diff_sql("fact_payments", "order_payments"))
add(C, "fact_reviews rows = staging.order_reviews rows", count_diff_sql("fact_reviews", "order_reviews"))
add(C, "sum(price) matches staging", sum_diff_sql("fact_sales", "price", "order_items", "price"))
add(C, "sum(freight_value) matches staging", sum_diff_sql("fact_sales", "freight_value", "order_items", "freight_value"))
add(C, "sum(payment_value) matches staging", sum_diff_sql("fact_payments", "payment_value", "order_payments", "payment_value"))
add(C, "distinct orders in fact_sales = distinct orders in staging.order_items",
    "SELECT ABS((SELECT COUNT(DISTINCT order_id) FROM warehouse.fact_sales) "
    "- (SELECT COUNT(DISTINCT order_id) FROM staging.order_items))")
add(C, "dim_customer (excl. Unknown) = distinct customer_unique_id in staging",
    "SELECT ABS((SELECT COUNT(*) FROM warehouse.dim_customer WHERE customer_key <> -1) "
    "- (SELECT COUNT(DISTINCT customer_unique_id) FROM staging.customers))")
add(C, "dim_product (excl. Unknown) = distinct product_id in staging",
    "SELECT ABS((SELECT COUNT(*) FROM warehouse.dim_product WHERE product_key <> -1) "
    "- (SELECT COUNT(DISTINCT product_id) FROM staging.products))")
add(C, "dim_seller (excl. Unknown) = distinct seller_id in staging",
    "SELECT ABS((SELECT COUNT(*) FROM warehouse.dim_seller WHERE seller_key <> -1) "
    "- (SELECT COUNT(DISTINCT seller_id) FROM staging.sellers))")

# ---- 2. Uniqueness -----------------------------------------------------
C = "Uniqueness"
add(C, "fact_sales: duplicate (order_id, order_item_id)", dup_sql("fact_sales", "order_id, order_item_id"))
add(C, "fact_payments: duplicate (order_id, payment_sequential)", dup_sql("fact_payments", "order_id, payment_sequential"))
add(C, "fact_reviews: duplicate (review_id, order_id)", dup_sql("fact_reviews", "review_id, order_id"))
add(C, "dim_customer: duplicate customer_unique_id", dup_sql("dim_customer", "customer_unique_id"))
add(C, "dim_product: duplicate product_id", dup_sql("dim_product", "product_id"))
add(C, "dim_seller: duplicate seller_id", dup_sql("dim_seller", "seller_id"))

# ---- 3. Referential integrity (no orphan keys) --------------------------
C = "Referential integrity"
add(C, "fact_sales.customer_key -> dim_customer", orphan_sql("fact_sales", "customer_key", "dim_customer", "customer_key", False))
add(C, "fact_sales.product_key -> dim_product", orphan_sql("fact_sales", "product_key", "dim_product", "product_key", False))
add(C, "fact_sales.seller_key -> dim_seller", orphan_sql("fact_sales", "seller_key", "dim_seller", "seller_key", False))
add(C, "fact_sales.purchase_date_key -> dim_date", orphan_sql("fact_sales", "purchase_date_key", "dim_date", "date_key", False))
for col in ("approved_date_key", "carrier_date_key", "delivered_date_key", "estimated_date_key"):
    add(C, f"fact_sales.{col} -> dim_date", orphan_sql("fact_sales", col, "dim_date", "date_key", True))
add(C, "fact_payments.customer_key -> dim_customer", orphan_sql("fact_payments", "customer_key", "dim_customer", "customer_key", False))
add(C, "fact_payments.payment_date_key -> dim_date", orphan_sql("fact_payments", "payment_date_key", "dim_date", "date_key", True))
add(C, "fact_reviews.customer_key -> dim_customer", orphan_sql("fact_reviews", "customer_key", "dim_customer", "customer_key", False))
add(C, "fact_reviews.review_date_key -> dim_date", orphan_sql("fact_reviews", "review_date_key", "dim_date", "date_key", True))
add(C, "fact_reviews.answer_date_key -> dim_date", orphan_sql("fact_reviews", "answer_date_key", "dim_date", "date_key", True))

# ---- 4. Unknown members (-1) -------------------------------------------
C = "Unknown members"
add(C, "fact_sales rows pointing to an Unknown customer/product/seller",
    "SELECT COUNT(*) FROM warehouse.fact_sales "
    "WHERE customer_key = -1 OR product_key = -1 OR seller_key = -1")
add(C, "fact_payments rows pointing to Unknown customer",
    "SELECT COUNT(*) FROM warehouse.fact_payments WHERE customer_key = -1")
add(C, "fact_reviews rows pointing to Unknown customer",
    "SELECT COUNT(*) FROM warehouse.fact_reviews WHERE customer_key = -1")

# ---- 5. Completeness ----------------------------------------------------
C = "Completeness"
add(C, "fact_sales: NULL price or freight_value",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE price IS NULL OR freight_value IS NULL")
add(C, "fact_sales: NULL or empty order_status",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE order_status IS NULL OR order_status = ''")
add(C, "fact_sales: NULL purchase_date_key",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE purchase_date_key IS NULL")
add(C, "fact_payments: NULL payment_type or payment_value",
    "SELECT COUNT(*) FROM warehouse.fact_payments WHERE payment_type IS NULL OR payment_value IS NULL")
add(C, "fact_reviews: NULL review_score",
    "SELECT COUNT(*) FROM warehouse.fact_reviews WHERE review_score IS NULL")

# ---- 6. Validity ----------------------------------------------------------
C = "Validity"
add(C, "fact_sales: negative price or freight_value",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE price < 0 OR freight_value < 0")
add(C, "fact_payments: negative payment_value",
    "SELECT COUNT(*) FROM warehouse.fact_payments WHERE payment_value < 0")
add(C, "fact_reviews: review_score outside 1-5",
    "SELECT COUNT(*) FROM warehouse.fact_reviews WHERE review_score NOT BETWEEN 1 AND 5")
add(C, "fact_sales: delivery_days < 0 (delivered before purchase)",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE delivery_days < 0", severity="warn")
add(C, "fact_sales: delivery_days > 365",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE delivery_days > 365", severity="warn")
add(C, "fact_payments: payment_value = 0",
    "SELECT COUNT(*) FROM warehouse.fact_payments WHERE payment_value = 0", severity="warn")

# ---- 7. Consistency of flags and derived columns ----------------------------
C = "Consistency"
add(C, "is_valid_sale = TRUE but is_valid_item = FALSE",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE is_valid_sale AND NOT is_valid_item")
add(C, "is_valid_sale = TRUE for a canceled/unavailable order",
    "SELECT COUNT(*) FROM warehouse.fact_sales "
    "WHERE is_valid_sale AND order_status IN ('canceled', 'unavailable')")
add(C, "is_delivered = TRUE without a delivered date",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE is_delivered AND delivered_date_key IS NULL")
add(C, "is_delivered = TRUE but order_status <> 'delivered'",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE is_delivered AND order_status <> 'delivered'")
add(C, "is_delivered = TRUE without delivery_days",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE is_delivered AND delivery_days IS NULL")
add(C, "delay_days present but delivered or estimated date missing",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE delay_days IS NOT NULL "
    "AND (delivered_date_key IS NULL OR estimated_date_key IS NULL)")
add(C, "delivered date earlier than purchase date (date keys)",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE delivered_date_key < purchase_date_key",
    severity="warn")

# ---- 8. Known results on the full Olist dataset (from the README) -------------
C = "Known results (Olist)"
add(C, "valid sales rows = 112,101",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE is_valid_sale", expected=112101)
add(C, "not-valid sales rows = 549",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE NOT is_valid_sale", expected=549)
add(C, "delivered rows = 110,189",
    "SELECT COUNT(*) FROM warehouse.fact_sales WHERE is_delivered", expected=110189)
add(C, "orders without items in staging = 775",
    "SELECT COUNT(*) FROM staging.orders o WHERE NOT EXISTS "
    "(SELECT 1 FROM staging.order_items oi WHERE oi.order_id = o.order_id)", expected=775)



# ---- 9. Synthetic inventory (added only when warehouse.fact_inventory exists) ----
def add_inventory_checks():
    C = "Inventory (synthetic)"
    add(C, "fact_inventory has rows",
        "SELECT CASE WHEN COUNT(*) > 0 THEN 0 ELSE 1 END FROM warehouse.fact_inventory")
    add(C, "fact_inventory: duplicate (product_key, snapshot_date_key)",
        dup_sql("fact_inventory", "product_key, snapshot_date_key"))
    add(C, "fact_inventory.product_key -> dim_product",
        orphan_sql("fact_inventory", "product_key", "dim_product", "product_key", False))
    add(C, "fact_inventory.snapshot_date_key -> dim_date",
        orphan_sql("fact_inventory", "snapshot_date_key", "dim_date", "date_key", False))
    add(C, "fact_inventory: negative stock or movement",
        "SELECT COUNT(*) FROM warehouse.fact_inventory WHERE opening_stock < 0 "
        "OR units_received < 0 OR units_sold < 0 OR closing_stock < 0")
    add(C, "fact_inventory: opening + received - sold <> closing",
        "SELECT COUNT(*) FROM warehouse.fact_inventory "
        "WHERE opening_stock + units_received - units_sold <> closing_stock")
    add(C, "fact_inventory: opening stock <> previous month's closing stock",
        "SELECT COUNT(*) FROM (SELECT opening_stock, LAG(closing_stock) OVER "
        "(PARTITION BY product_key ORDER BY snapshot_date_key) AS prev_closing "
        "FROM warehouse.fact_inventory) t "
        "WHERE prev_closing IS NOT NULL AND opening_stock <> prev_closing")
    add(C, "fact_inventory.units_sold <> real sales in fact_sales",
        "SELECT COUNT(*) FROM warehouse.fact_inventory i "
        "JOIN warehouse.dim_date dd ON dd.date_key = i.snapshot_date_key "
        "LEFT JOIN (SELECT f.product_key, d.year, d.month, COUNT(*) AS units "
        "FROM warehouse.fact_sales f JOIN warehouse.dim_date d ON f.purchase_date_key = d.date_key "
        "WHERE f.is_valid_sale GROUP BY f.product_key, d.year, d.month) s "
        "ON s.product_key = i.product_key AND s.year = dd.year AND s.month = dd.month "
        "WHERE i.units_sold <> COALESCE(s.units, 0)")
    add(C, "fact_inventory: reorder_level < 1",
        "SELECT COUNT(*) FROM warehouse.fact_inventory WHERE reorder_level < 1")
    add(C, "fact_inventory: is_low_stock inconsistent with closing_stock <= reorder_level",
        "SELECT COUNT(*) FROM warehouse.fact_inventory "
        "WHERE is_low_stock <> (closing_stock <= reorder_level)")
    add(C, "fact_inventory: snapshots with closing_stock = 0 (stock-outs)",
        "SELECT COUNT(*) FROM warehouse.fact_inventory WHERE closing_stock = 0",
        severity="warn")


# ----------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------
def run_checks(conn):
    results = []
    for category, name, sql, expected, severity in CHECKS:
        actual, message = None, ""
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                actual = cur.fetchone()[0]
            if actual is not None and float(actual) == float(expected):
                status = "PASS"
            else:
                status = "FAIL" if severity == "error" else "WARN"
        except Exception as e:  # missing column/table, etc.
            conn.rollback()
            status = "ERROR"
            message = str(e).strip().splitlines()[0]
        results.append(dict(category=category, name=name, severity=severity,
                            expected=expected, actual=actual, status=status,
                            message=message))
    return results


def save_results(conn, run_id, results):
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dq.warehouse_check_results (
                    run_id     text,
                    run_ts     timestamptz DEFAULT now(),
                    category   text,
                    check_name text,
                    severity   text,
                    expected   numeric,
                    actual     numeric,
                    status     text,
                    message    text
                )""")
            for r in results:
                cur.execute(
                    "INSERT INTO dq.warehouse_check_results "
                    "(run_id, category, check_name, severity, expected, actual, status, message) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (run_id, r["category"], r["name"], r["severity"],
                     r["expected"], r["actual"], r["status"], r["message"]))
        conn.commit()
        print("Results saved to dq.warehouse_check_results")
    except Exception as e:
        conn.rollback()
        print(f"WARNING: could not save results to dq schema: {e}")


def fmt(v):
    if v is None:
        return "-"
    f = float(v)
    return f"{int(f):,}" if f == int(f) else f"{f:,.2f}"


def write_report(results, run_ts):
    total = len(results)
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("PASS", "FAIL", "WARN", "ERROR")}
    categories = list(dict.fromkeys(r["category"] for r in results))

    lines = [
        "# Warehouse Data Quality Report",
        "",
        f"Generated by `warehouse/run_dq_checks.py` on {run_ts:%Y-%m-%d %H:%M}.",
        "Results are also stored in `dq.warehouse_check_results`.",
        "",
        "## Summary",
        "",
        "| Result | Checks |",
        "|---|---|",
        f"| PASS | {counts['PASS']} |",
        f"| FAIL | {counts['FAIL']} |",
        f"| WARN | {counts['WARN']} |",
        f"| ERROR | {counts['ERROR']} |",
        f"| **Total** | **{total}** |",
        "",
        "## Results by category",
        "",
        "| Category | Checks | Pass | Fail | Warn | Error |",
        "|---|---|---|---|---|---|",
    ]
    for cat in categories:
        rs = [r for r in results if r["category"] == cat]
        row = [sum(1 for r in rs if r["status"] == s) for s in ("PASS", "FAIL", "WARN", "ERROR")]
        lines.append(f"| {cat} | {len(rs)} | {row[0]} | {row[1]} | {row[2]} | {row[3]} |")

    problems = [r for r in results if r["status"] != "PASS"]
    lines += ["", "## Failures, warnings and errors", ""]
    if not problems:
        lines.append("None. All checks passed.")
    else:
        lines += ["| Status | Category | Check | Expected | Actual | Note |", "|---|---|---|---|---|---|"]
        for r in problems:
            lines.append(f"| {r['status']} | {r['category']} | {r['name']} | "
                         f"{fmt(r['expected'])} | {fmt(r['actual'])} | {r['message']} |")

    lines += ["", "## All checks", ""]
    for cat in categories:
        lines += [f"### {cat}", "", "| Status | Check | Expected | Actual |", "|---|---|---|---|"]
        for r in (x for x in results if x["category"] == cat):
            lines.append(f"| {r['status']} | {r['name']} | {fmt(r['expected'])} | {fmt(r['actual'])} |")
        lines.append("")

    lines += [
        "## How to read this report",
        "",
        "- Each check is one SQL query that returns a single number; it passes when the number equals the expected value (0 for most checks).",
        "- `FAIL` means a rule that must hold was broken. The script exits with an error in this case.",
        "- `WARN` marks data anomalies that are reported but do not stop the pipeline (for example payments with value 0).",
        "- `ERROR` means the check query itself could not run (for example a missing column).",
        "- To add a check, call `add(...)` in `warehouse/run_dq_checks.py`.",
        "",
    ]
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_FILE}")


def main():
    run_ts = datetime.now()
    run_id = run_ts.strftime("%Y%m%d_%H%M%S")
    conn = pg.connect(**get_db_config())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('warehouse.fact_inventory') IS NOT NULL")
            has_inventory = cur.fetchone()[0]
        if has_inventory:
            add_inventory_checks()
        else:
            print("warehouse.fact_inventory not found: inventory checks skipped\n")
        results = run_checks(conn)
        for r in results:
            print(f"[{r['status']:<5}] {r['category']:<22} {r['name']}"
                  f"  (expected {fmt(r['expected'])}, actual {fmt(r['actual'])})"
                  + (f"  -> {r['message']}" if r["message"] else ""))
        save_results(conn, run_id, results)
        write_report(results, run_ts)
    finally:
        conn.close()

    failed = [r for r in results if r["status"] in ("FAIL", "ERROR")]
    warned = [r for r in results if r["status"] == "WARN"]
    print(f"\n{len(results) - len(failed) - len(warned)}/{len(results)} passed, "
          f"{len(failed)} failed/errored, {len(warned)} warnings")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
