"""
Insert synthetic demo orders into the existing PostgreSQL database (raw layer).

Run from the project root:
    python scripts/simulate_db_orders.py --orders 360000
    python scripts/simulate_db_orders.py --orders 360000 --replace
    python scripts/simulate_db_orders.py --remove

After adding or removing demo rows, rebuild the other layers:
    python staging/run_staging.py
    python warehouse/run_etl.py
    python warehouse/generate_inventory.py

How the demo data is made realistic:
- Products, sellers and prices come from the ORIGINAL Olist sales history.
- Monthly order volume grows gradually (~55% to ~145% of average) with
  seasonal variation (Nov/Dec peak). Orders are allocated to months with
  the largest-remainder method so the total is always exact.
- Review scores follow the real Olist score distribution.
- Every order gets its own new customer_id, as in Olist.
- About 3% of orders belong to an existing customer (returning customer).
- All orders are within the configured historical period (Nov 2018 to
  Sep 2026) and are either delivered (98%) or canceled (2%).
- Delivery and estimated delivery times approximate Olist averages.

Large-volume safety:
- Rows are generated and inserted in batches (BATCH_SIZE orders each)
  so memory stays bounded even at 360,000+ orders.
- Each batch is inserted inside the same outer transaction.
  If anything fails, the whole transaction is rolled back.
- Original Olist rows are never changed or deleted.
- Every generated row has _source_file = 'synthetic_demo'.
- Only demo rows are removed by --replace / --remove.
- Without --replace the script refuses to run if demo orders already exist.

Expected row counts at 360,000 orders (approximate):
    raw.orders          360,000
    raw.customers       360,000
    raw.order_items     504,000   (~1.4 items/order average)
    raw.order_payments  360,000
    raw.order_reviews   247,000   (~70% of delivered orders)
    Total             1,831,000
"""

import argparse
import calendar
import random
import sys
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

DEMO_SOURCE = "synthetic_demo"
SEED = 20261026

REFERENCE_DATE = datetime(2026, 10, 26)

# Start right after the original Olist sales period ends (Oct 2018).
START = datetime(2018, 9, 1)
END = datetime(2026, 9, 30, 23, 59, 59)

RETURNING_CUSTOMER_SHARE = 0.03
CANCELED_SHARE = 0.02

# How many orders to build and insert per database round-trip.
# 5,000 is a safe default: low memory pressure, good throughput.
# Raise to 10,000 on machines with plenty of RAM.
BATCH_SIZE = 5_000

CUSTOMER_COLUMNS = (
    "customer_id",
    "customer_unique_id",
    "customer_zip_code_prefix",
    "customer_city",
    "customer_state",
)

NUMBER = r"'^[0-9]+(\.[0-9]+)?$'"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def load_env(path):
    """Load PostgreSQL settings from the project's .env file."""
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


def connect():
    """Connect to PostgreSQL using the existing project .env settings."""
    env = load_env(ENV_FILE)
    missing = [k for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
               if k not in env]
    if missing:
        sys.exit(f"ERROR: missing in .env: {', '.join(missing)}")
    return psycopg2.connect(
        host=env.get("POSTGRES_HOST", "127.0.0.1"),
        port=int(env.get("POSTGRES_PORT", 5432)),
        user=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
        dbname=env["POSTGRES_DB"],
    )


def money(value):
    """Round a numeric value to two decimal places."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


def stamp(value):
    """Format a datetime for insertion into PostgreSQL."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def count_demo(cur):
    """Count synthetic demo orders in the raw orders table."""
    cur.execute(
        "SELECT COUNT(*) FROM raw.orders WHERE _source_file = %s",
        (DEMO_SOURCE,),
    )
    return cur.fetchone()[0]


def remove_demo(cur):
    """Delete only synthetic demo rows, children first."""
    removed = {}
    for table in ("order_reviews", "order_payments", "order_items",
                  "orders", "customers"):
        cur.execute(
            f"DELETE FROM raw.{table} WHERE _source_file = %s",
            (DEMO_SOURCE,),
        )
        removed[table] = cur.rowcount
    return removed


# ---------------------------------------------------------------------------
# Reference data (read once from original Olist rows)
# ---------------------------------------------------------------------------

def load_reference_data(cur):
    """
    Read original Olist rows needed to generate realistic demo orders.

    Synthetic rows are excluded so that replacing demo data does not let
    old synthetic rows pollute the reference statistics.
    """
    # Real (product, seller) combinations with average price, freight and
    # number of historical sales.
    cur.execute(
        f"""
        SELECT
            product_id,
            seller_id,
            AVG(CASE WHEN price::text ~ {NUMBER} THEN price::text::numeric END),
            AVG(CASE WHEN freight_value::text ~ {NUMBER}
                     THEN freight_value::text::numeric END),
            COUNT(*)
        FROM raw.order_items
        WHERE _source_file IS DISTINCT FROM %s
        GROUP BY product_id, seller_id
        HAVING AVG(CASE WHEN price::text ~ {NUMBER}
                        THEN price::text::numeric END) IS NOT NULL
        ORDER BY product_id, seller_id
        """,
        (DEMO_SOURCE,),
    )
    offers = {}
    for product_id, seller_id, price, freight, n in cur.fetchall():
        offers.setdefault(product_id, []).append(
            (seller_id, float(price), float(freight or 0), n)
        )
    products = sorted(offers)
    product_weights = [sum(o[3] for o in offers[p]) for p in products]

    # Real review score distribution.
    cur.execute(
        """
        SELECT review_score::text, COUNT(*)
        FROM raw.order_reviews
        WHERE _source_file IS DISTINCT FROM %s
          AND review_score::text IN ('1', '2', '3', '4', '5')
        GROUP BY 1
        ORDER BY 1
        """,
        (DEMO_SOURCE,),
    )
    dist = {int(score): count for score, count in cur.fetchall()}
    scores = [1, 2, 3, 4, 5]
    score_weights = [dist.get(s, 0) for s in scores]
    if not any(score_weights):
        score_weights = [115, 32, 82, 193, 578]   # Olist fallback

    # Validate the columns we need from raw.customers.
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = 'customers'
        """
    )
    have = {row[0] for row in cur.fetchall()}
    missing = [c for c in CUSTOMER_COLUMNS + ("_source_file",) if c not in have]
    if missing:
        sys.exit("ERROR: raw.customers is missing columns: " + ", ".join(missing))

    # Only original customers are used as address / returning-customer pool.
    cur.execute(
        """
        SELECT customer_unique_id, customer_zip_code_prefix,
               customer_city, customer_state
        FROM raw.customers
        WHERE _source_file IS DISTINCT FROM %s
        ORDER BY customer_id
        """,
        (DEMO_SOURCE,),
    )
    customers = cur.fetchall()

    if not products or not customers:
        sys.exit(
            "ERROR: no original sales history or customers found in the raw layer."
        )

    return offers, products, product_weights, scores, score_weights, customers


# ---------------------------------------------------------------------------
# Date distribution: growth + seasonality
# ---------------------------------------------------------------------------

def build_monthly_order_counts(n_orders):
    """
    Allocate exactly n_orders across months from START to END.

    The monthly baseline grows gradually from 70% to 130% of the average
    (simulating organic store growth).  Seasonal multipliers add realistic
    within-year variation: Q4 peaks, Q1 dip.

    The largest-remainder method guarantees sum(counts) == n_orders exactly.

    NOTE: The growth curve and seasonal factors are configurable demo
    assumptions, not figures derived from measured Olist monthly data.
    """
    months = []
    year, month = START.year, START.month
    while (year, month) <= (END.year, END.month):
        months.append((year, month))
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1

    # Monthly seasonal multipliers (Jan=1 baseline).
    seasonal = {
        1: 0.85, 2: 0.90, 3: 0.95, 4: 0.95,
        5: 1.10, 6: 1.00, 7: 1.00, 8: 1.10,
        9: 1.05, 10: 1.00, 11: 1.25, 12: 1.10,
    }

    last_idx = max(len(months) - 1, 1)
    weights = [
        (0.70 + 0.60 * i / last_idx) * seasonal[m]
        for i, (_, m) in enumerate(months)
    ]

    total_weight = sum(weights)
    exact = [n_orders * w / total_weight for w in weights]
    counts = [int(x) for x in exact]

    # Distribute remaining orders to months with the largest fractional parts.
    remainder = n_orders - sum(counts)
    indices = sorted(range(len(months)),
                     key=lambda i: exact[i] - counts[i], reverse=True)
    for i in indices[:remainder]:
        counts[i] += 1

    return list(zip(months, counts))


def build_purchase_dates(n_orders, rng):
    """
    Generate exactly n_orders purchase timestamps.

    Orders are spread across months according to growth + seasonality.
    Within each month, timestamps are drawn uniformly at random while
    respecting the global START and END boundaries.
    """
    dates = []
    for (year, month), count in build_monthly_order_counts(n_orders):
        month_start = max(datetime(year, month, 1), START)
        last_day = calendar.monthrange(year, month)[1]
        month_end = min(datetime(year, month, last_day, 23, 59, 59), END)
        seconds = int((month_end - month_start).total_seconds())
        if seconds <= 0:
            continue
        for _ in range(count):
            dates.append(month_start + timedelta(seconds=rng.randrange(seconds + 1)))

    rng.shuffle(dates)

    if len(dates) != n_orders:
        raise RuntimeError(
            f"Expected {n_orders} purchase dates, generated {len(dates)}."
        )
    return dates


# ---------------------------------------------------------------------------
# Order generation (one order at a time, yielded for batch insertion)
# ---------------------------------------------------------------------------

def generate_orders(n_orders, ref):
    """
    Generator — yields (customer_row, order_row, item_rows, payment_row,
    review_row_or_None) for each synthetic order.

    Using a generator keeps memory O(BATCH_SIZE) regardless of n_orders.
    """
    rng = random.Random(SEED)
    offers, products, product_weights, scores, score_weights, customers = ref

    purchase_dates = build_purchase_dates(n_orders, rng)

    for purchase in purchase_dates:
        order_id = uuid.uuid4().hex
        customer_id = uuid.uuid4().hex

        if rng.random() < RETURNING_CUSTOMER_SHARE:
            unique_id, zip_code, city, state = rng.choice(customers)
        else:
            unique_id = uuid.uuid4().hex
            _, zip_code, city, state = rng.choice(customers)

        customer_row = (customer_id, unique_id, zip_code, city, state, DEMO_SOURCE)

        status = "canceled" if rng.random() < CANCELED_SHARE else "delivered"
        approved = purchase + timedelta(hours=rng.randint(1, 18))
        carrier = delivered = None

        if status == "delivered":
            max_days = max((REFERENCE_DATE - purchase).days - 1, 3)
            delivery_days = min(max(round(rng.gauss(12.5, 6)), 3), 40, max_days)
            carrier = approved + timedelta(days=rng.randint(1, 3))
            delivered = purchase + timedelta(days=delivery_days,
                                             hours=rng.randint(0, 23))
            if delivered <= carrier:
                delivered = carrier + timedelta(days=1)

        estimated = purchase + timedelta(
            days=min(max(round(rng.gauss(24.5, 6)), 10), 45)
        )

        order_row = (
            order_id, customer_id, status,
            stamp(purchase), stamp(approved),
            stamp(carrier) if carrier else None,
            stamp(delivered) if delivered else None,
            stamp(estimated),
            DEMO_SOURCE,
        )

        order_total = Decimal("0.00")
        item_rows = []
        item_count = rng.choice([1, 1, 1, 2, 3])

        for item_no in range(1, item_count + 1):
            product_id = rng.choices(products, weights=product_weights, k=1)[0]
            seller_offers = offers[product_id]
            seller_id, avg_price, avg_freight, _ = rng.choices(
                seller_offers,
                weights=[o[3] for o in seller_offers],
                k=1,
            )[0]
            price = money(max(avg_price * rng.uniform(0.9, 1.1), 1))
            freight = money(max(avg_freight * rng.uniform(0.8, 1.2), 0))
            order_total += price + freight
            item_rows.append((
                order_id, str(item_no), product_id, seller_id,
                stamp(purchase + timedelta(days=rng.randint(2, 5))),
                str(price), str(freight), DEMO_SOURCE,
            ))

        payment_type = rng.choices(
            ["credit_card", "boleto", "voucher", "debit_card"],
            weights=[74, 19, 5, 2], k=1,
        )[0]
        installments = rng.randint(1, 10) if payment_type == "credit_card" else 1
        payment_row = (
            order_id, "1", payment_type, str(installments),
            str(money(order_total)), DEMO_SOURCE,
        )

        review_row = None
        if status == "delivered" and rng.random() < 0.70:
            created = delivered + timedelta(days=rng.randint(1, 5))
            answered = created + timedelta(hours=rng.randint(1, 72))
            review_row = (
                uuid.uuid4().hex, order_id,
                str(rng.choices(scores, weights=score_weights, k=1)[0]),
                rng.choice(["Great", "Good", "As expected",
                             "Could improve", "Excellent"]),
                rng.choice([
                    "Delivery was smooth.",
                    "Product matched the description.",
                    "Good value for money.",
                    "Everything arrived in good condition.",
                    "",
                ]),
                stamp(created), stamp(answered), DEMO_SOURCE,
            )

        yield customer_row, order_row, item_rows, payment_row, review_row


# ---------------------------------------------------------------------------
# Batch insertion
# ---------------------------------------------------------------------------

def insert_batch(cur, customer_rows, order_rows, item_rows,
                 payment_rows, review_rows):
    """Insert one batch of rows into the raw tables."""
    execute_values(cur, """
        INSERT INTO raw.customers
        (customer_id, customer_unique_id, customer_zip_code_prefix,
         customer_city, customer_state, _source_file)
        VALUES %s
    """, customer_rows)

    execute_values(cur, """
        INSERT INTO raw.orders
        (order_id, customer_id, order_status, order_purchase_timestamp,
         order_approved_at, order_delivered_carrier_date,
         order_delivered_customer_date, order_estimated_delivery_date,
         _source_file)
        VALUES %s
    """, order_rows)

    execute_values(cur, """
        INSERT INTO raw.order_items
        (order_id, order_item_id, product_id, seller_id,
         shipping_limit_date, price, freight_value, _source_file)
        VALUES %s
    """, item_rows)

    execute_values(cur, """
        INSERT INTO raw.order_payments
        (order_id, payment_sequential, payment_type,
         payment_installments, payment_value, _source_file)
        VALUES %s
    """, payment_rows)

    if review_rows:
        execute_values(cur, """
            INSERT INTO raw.order_reviews
            (review_id, order_id, review_score, review_comment_title,
             review_comment_message, review_creation_date,
             review_answer_timestamp, _source_file)
            VALUES %s
        """, review_rows)


def insert_all_batched(conn, n_orders, ref):
    """
    Generate and insert all orders in BATCH_SIZE chunks.

    All inserts share a single transaction (conn is already inside one).
    Progress is printed after every batch so large runs stay observable.
    """
    total_customers = total_orders = total_items = 0
    total_payments = total_reviews = 0

    customer_buf, order_buf, item_buf, payment_buf, review_buf = [], [], [], [], []
    batches_done = 0

    gen = generate_orders(n_orders, ref)
    orders_generated = 0

    for customer_row, order_row, item_rows, payment_row, review_row in gen:
        customer_buf.append(customer_row)
        order_buf.append(order_row)
        item_buf.extend(item_rows)
        payment_buf.append(payment_row)
        if review_row:
            review_buf.append(review_row)
        orders_generated += 1

        if orders_generated % BATCH_SIZE == 0:
            with conn.cursor() as cur:
                insert_batch(cur, customer_buf, order_buf, item_buf,
                             payment_buf, review_buf)
            batches_done += 1
            total_customers += len(customer_buf)
            total_orders += len(order_buf)
            total_items += len(item_buf)
            total_payments += len(payment_buf)
            total_reviews += len(review_buf)
            customer_buf, order_buf, item_buf, payment_buf, review_buf = \
                [], [], [], [], []
            pct = 100 * orders_generated // n_orders
            print(f"  batch {batches_done}: {orders_generated:,}/{n_orders:,} "
                  f"orders inserted ({pct}%)", flush=True)

    # Flush any remaining rows in the last partial batch.
    if customer_buf:
        with conn.cursor() as cur:
            insert_batch(cur, customer_buf, order_buf, item_buf,
                         payment_buf, review_buf)
        total_customers += len(customer_buf)
        total_orders += len(order_buf)
        total_items += len(item_buf)
        total_payments += len(payment_buf)
        total_reviews += len(review_buf)

    return {
        "customers": total_customers,
        "orders": total_orders,
        "order items": total_items,
        "payments": total_payments,
        "reviews": total_reviews,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global BATCH_SIZE

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--orders",
        type=int,
        default=380000,
        help="number of demo orders to insert (default: 380000; "
             "use 8000 for a quick test)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        metavar="N",
        help="orders per database round-trip (default: 5000)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="remove existing demo rows first, then insert new ones",
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="only remove existing demo rows (insert nothing)",
    )
    args = parser.parse_args()

    # Must be declared before any reference to BATCH_SIZE in this scope.
    global BATCH_SIZE

    if args.orders < 1:
        sys.exit("--orders must be at least 1")
    if args.batch_size < 100:
        sys.exit("--batch-size must be at least 100")

    BATCH_SIZE = args.batch_size

    conn = connect()
    try:
        # Everything runs in one transaction: either all commits or nothing.
        conn.autocommit = False
        with conn.cursor() as cur:
            existing = count_demo(cur)

        if args.remove:
            with conn.cursor() as cur:
                removed = remove_demo(cur)
            conn.commit()
            print("Removed demo rows:",
                  ", ".join(f"{t}={n:,}" for t, n in removed.items()))
            print("Next: python staging/run_staging.py  "
                  "python warehouse/run_etl.py  "
                  "python warehouse/generate_inventory.py")
            return

        if existing and not args.replace:
            sys.exit(
                f"Found {existing:,} existing synthetic demo orders. "
                "Nothing was added to avoid duplicates. "
                "Use --replace to remove them and insert new ones."
            )

        if existing and args.replace:
            with conn.cursor() as cur:
                removed = remove_demo(cur)
            print("Removed old demo rows:",
                  ", ".join(f"{t}={n:,}" for t, n in removed.items()))

        print(f"Generating {args.orders:,} demo orders "
              f"(batch size: {BATCH_SIZE:,}) …")

        with conn.cursor() as cur:
            ref = load_reference_data(cur)

        counts = insert_all_batched(conn, args.orders, ref)
        conn.commit()

        print("\nInserted demo data:")
        for name, n in counts.items():
            print(f"  {name}: {n:,}")
        print(f"Source marker : {DEMO_SOURCE}")
        print(f"Date range    : {START:%Y-%m-%d} to {END:%Y-%m-%d}")
        print("Next: python staging/run_staging.py  "
              "python warehouse/run_etl.py  "
              "python warehouse/generate_inventory.py")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
