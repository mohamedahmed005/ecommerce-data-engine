"""
Load the Olist CSVs into Postgres schema `raw` (Azure-optimized chunked COPY).
"""
import argparse
import csv
import io
import os
import sys
import time
from pathlib import Path

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

FILES = {
    "olist_customers_dataset.csv": "customers",
    "olist_geolocation_dataset.csv": "geolocation",
    "olist_order_items_dataset.csv": "order_items",
    "olist_order_payments_dataset.csv": "order_payments",
    "olist_order_reviews_dataset.csv": "order_reviews",
    "olist_orders_dataset.csv": "orders",
    "olist_products_dataset.csv": "products",
    "olist_sellers_dataset.csv": "sellers",
    "product_category_name_translation.csv": "product_category_translation",
}

BATCH_ROWS = 3000


def connect():
    load_dotenv()
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        user=os.getenv("POSTGRES_USER", "ecom"),
        password=os.getenv("POSTGRES_PASSWORD", "ecom_pass"),
        dbname=os.getenv("POSTGRES_DB", "ecom"),
        sslmode=os.getenv("PGSSLMODE", "require"),
        keepalives=1,
        keepalives_idle=20,
        keepalives_interval=10,
        keepalives_count=5,
    )


def load_file(cur, path: Path, table: str) -> int:
    t0 = time.time()
    ident = sql.Identifier("raw", table)

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        cols = next(reader)

        col_defs = [sql.SQL("{} TEXT").format(sql.Identifier(c)) for c in cols]
        col_defs.append(sql.SQL("_source_file TEXT DEFAULT {}").format(sql.Literal(path.name)))
        col_defs.append(sql.SQL("_ingested_at TIMESTAMPTZ DEFAULT now()"))

        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(ident))
        cur.execute(sql.SQL("CREATE UNLOGGED TABLE {} ({})").format(ident, sql.SQL(", ").join(col_defs)))

        copy_stmt = sql.SQL(
            "COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER false, ENCODING 'UTF8')"
        ).format(ident, sql.SQL(", ").join(sql.Identifier(c) for c in cols))

        total = 0
        batch = []
        for row in reader:
            batch.append(row)
            if len(batch) >= BATCH_ROWS:
                buf = io.StringIO()
                csv.writer(buf, lineterminator="\n").writerows(batch)
                buf.seek(0)
                cur.copy_expert(copy_stmt, buf)
                total += len(batch)
                batch.clear()
                print(f"\r  raw.{table:<28} {total:>10,} rows ({time.time() - t0:.1f}s)", end="", flush=True)

        if batch:
            buf = io.StringIO()
            csv.writer(buf, lineterminator="\n").writerows(batch)
            buf.seek(0)
            cur.copy_expert(copy_stmt, buf)
            total += len(batch)

    cur.execute(sql.SQL("ALTER TABLE {} SET LOGGED").format(ident))
    print(f"\r  raw.{table:<28} {total:>10,} rows ({time.time() - t0:.1f}s) - OK")
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/raw")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)

    missing = [f for f in FILES if not (data_dir / f).exists()]
    if missing:
        print(f"Missing files in {data_dir}:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)

    conn = connect()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET synchronous_commit = OFF;")
            cur.execute("""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND usename = current_user
                  AND pid <> pg_backend_pid()
            """)
            cur.execute("CREATE SCHEMA IF NOT EXISTS raw")
            print("Uploading Olist CSVs to Azure PostgreSQL...\n")
            for fname, table in FILES.items():
                load_file(cur, data_dir / fname, table)
        print("\nDone. All 9 tables loaded.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()