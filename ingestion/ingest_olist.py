"""
Load the Olist CSVs into Postgres schema `raw` exactly as they are.

- Every source column is stored as TEXT (Bronze layer: no cleaning, no casting).
- Two metadata columns are added: _source_file, _ingested_at.
- Safe to re-run: each table is dropped and recreated.

Usage:
    python ingestion/ingest_olist.py
    python ingestion/ingest_olist.py --data-dir data/raw
"""
import argparse
import csv
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

# csv file name -> raw table name
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


def connect():
    load_dotenv()
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        user=os.getenv("POSTGRES_USER", "ecom"),
        password=os.getenv("POSTGRES_PASSWORD", "ecom_pass"),
        dbname=os.getenv("POSTGRES_DB", "ecom"),
    )


def read_header(path: Path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return next(csv.reader(f))


def load_file(cur, path: Path, table: str) -> int:
    cols = read_header(path)
    ident = sql.Identifier("raw", table)

    col_defs = [sql.SQL("{} TEXT").format(sql.Identifier(c)) for c in cols]
    col_defs.append(sql.SQL("_source_file TEXT DEFAULT {}").format(sql.Literal(path.name)))
    col_defs.append(sql.SQL("_ingested_at TIMESTAMPTZ DEFAULT now()"))

    cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(ident))
    cur.execute(sql.SQL("CREATE TABLE {} ({})").format(ident, sql.SQL(", ").join(col_defs)))

    copy_stmt = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')").format(
        ident, sql.SQL(", ").join(sql.Identifier(c) for c in cols)
    )
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        cur.copy_expert(copy_stmt, f)

    cur.execute(sql.SQL("SELECT count(*) FROM {}").format(ident))
    return cur.fetchone()[0]


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
    try:
        with conn, conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS raw")
            print(f"{'table':32} {'rows':>10}")
            print("-" * 43)
            for fname, table in FILES.items():
                n = load_file(cur, data_dir / fname, table)
                print(f"raw.{table:28} {n:>10,}")
        print("\nDone. All tables loaded in a single transaction.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
