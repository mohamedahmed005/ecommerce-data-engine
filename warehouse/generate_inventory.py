"""Generate the synthetic inventory table (warehouse.fact_inventory).

Olist has no stock data, so this script simulates it from the REAL monthly
sales in warehouse.fact_sales:

  * grain: one row per product per month (stock at the end of the month)
  * units_sold    = real valid-sale items of that product in that month
  * reorder_level = max(2, ceil(1.5 * average monthly sales of the product))
  * a product is reordered up to ~3 months of sales when its opening stock
    is at or below the reorder level; deliveries are sometimes partial or
    late, so some products run low
  * if stock would not cover the real sales, an emergency receipt covers
    the gap, so closing_stock is never negative
  * a fixed seed makes the output identical on every run

Only ORIGINAL Olist sales are used (rows with is_synthetic = FALSE). The
synthetic demo orders of 2026 are ignored, otherwise every product would be
tracked through the 7-year gap between 2018 and 2026.

Tracking starts in the month of the product's first sale and ends at the
last month with at least 100 orders (the last months of the dataset are
almost empty).

Usage (from the project root, after warehouse/run_etl.py):
    python warehouse/generate_inventory.py
"""
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
DDL_FILE = BASE_DIR / "sql" / "warehouse" / "06_inventory.sql"

SEED = 42
MIN_ORDERS_LAST_MONTH = 100


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


def month_index(year, month):
    return year * 12 + month - 1


def simulate_product(product_key, sales, first_idx, last_idx):
    """Return one tuple per month: (idx, opening, received, sold, closing, reorder_level, low)."""
    rng = random.Random(f"{SEED}-{product_key}")
    months = range(first_idx, last_idx + 1)
    avg = sum(sales.get(i, 0) for i in months) / len(months)

    reorder_level = max(2, math.ceil(1.5 * avg))
    order_up_to = max(reorder_level + 3, math.ceil(3.0 * avg)) + rng.randint(0, 3)
    stock = math.ceil(2.5 * avg) + rng.randint(0, 5)

    rows = []
    for idx in months:
        opening = stock
        sold = sales.get(idx, 0)
        received = 0
        if opening <= reorder_level:
            received = order_up_to - opening
            roll = rng.random()
            if roll < 0.15:        # partial delivery
                received = received // 2
            elif roll < 0.25:      # delivery delayed to next month
                received = 0
        if opening + received < sold:   # emergency receipt: real sales must be covered
            received += sold - (opening + received)
        closing = opening + received - sold
        rows.append((idx, opening, received, sold, closing, reorder_level, closing <= reorder_level))
        stock = closing
    return rows


def main():
    conn = psycopg2.connect(**get_db_config())
    try:
        with conn.cursor() as cur:
            # last month with enough orders
            cur.execute("""
                SELECT d.year, d.month
                FROM warehouse.fact_sales f
                JOIN warehouse.dim_date d ON f.purchase_date_key = d.date_key
                WHERE f.is_valid_sale = TRUE AND f.is_synthetic = FALSE
                GROUP BY d.year, d.month
                HAVING COUNT(DISTINCT f.order_id) >= %s
                ORDER BY d.year DESC, d.month DESC
                LIMIT 1""", (MIN_ORDERS_LAST_MONTH,))
            row = cur.fetchone()
            if not row:
                sys.exit(f"ERROR: no month with at least {MIN_ORDERS_LAST_MONTH} orders in fact_sales")
            last_idx = month_index(*row)

            # last day of each month that exists in dim_date
            cur.execute("SELECT year, month, MAX(date_key) FROM warehouse.dim_date GROUP BY year, month")
            month_end = {month_index(y, m): k for y, m, k in cur.fetchall()}

            # real monthly sales per product
            cur.execute("""
                SELECT f.product_key, d.year, d.month, COUNT(*)
                FROM warehouse.fact_sales f
                JOIN warehouse.dim_date d ON f.purchase_date_key = d.date_key
                WHERE f.is_valid_sale = TRUE AND f.is_synthetic = FALSE AND f.product_key <> -1
                GROUP BY f.product_key, d.year, d.month""")
            sales = defaultdict(dict)
            for product_key, y, m, units in cur.fetchall():
                sales[product_key][month_index(y, m)] = units

        out, skipped = [], 0
        for product_key in sorted(sales):
            first_idx = min(sales[product_key])
            if first_idx > last_idx:
                skipped += 1
                continue
            for idx, opening, received, sold, closing, level, low in simulate_product(
                    product_key, sales[product_key], first_idx, last_idx):
                if idx not in month_end:
                    sys.exit(f"ERROR: dim_date has no dates for month index {idx}")
                out.append((product_key, month_end[idx], opening, received, sold, closing, level, low))

        with conn.cursor() as cur:
            cur.execute(DDL_FILE.read_text(encoding="utf-8"))
            execute_values(cur, """
                INSERT INTO warehouse.fact_inventory
                (product_key, snapshot_date_key, opening_stock, units_received,
                 units_sold, closing_stock, reorder_level, is_low_stock)
                VALUES %s""", out, page_size=5000)
            cur.execute("""
                SELECT COUNT(*), COUNT(DISTINCT product_key),
                       MIN(snapshot_date_key), MAX(snapshot_date_key),
                       SUM(is_low_stock::int), SUM((closing_stock = 0)::int),
                       SUM(units_sold)
                FROM warehouse.fact_inventory""")
            n, products, d1, d2, low, zero, sold_total = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("warehouse.fact_inventory generated (SYNTHETIC data, seed", SEED, ")")
    print(f"  rows (product x month): {n:,}")
    print(f"  products tracked:       {products:,}  (skipped, first sale after last month: {skipped})")
    print(f"  snapshot range:         {d1} -> {d2}")
    print(f"  low-stock snapshots:    {low:,} ({100.0 * low / n:.1f}%)")
    print(f"  stock-out snapshots:    {zero:,} ({100.0 * zero / n:.1f}%)")
    print(f"  total units sold:       {sold_total:,}")


if __name__ == "__main__":
    main()
