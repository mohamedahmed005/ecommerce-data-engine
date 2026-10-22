# E-Commerce Data Engine — Step 1: Environment + Raw Ingestion

## Project structure
```
ecommerce-data-engine/
├── data/raw/          # Olist CSVs (not in Git, see below)
├── docs/              # profiling report + docs/erd (warehouse ERD)
├── ingestion/         # raw loader
├── profiling/         # data quality profiling
├── sql/init/          # schemas (run automatically by Docker)
├── sql/staging/       # staging layer SQL
├── sql/warehouse/     # warehouse DDL (dimensions + facts)
├── staging/           # staging runner + validation
├── warehouse/         # warehouse DDL runner
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

## Quick start (for teammates)

```bash
git clone https://github.com/mohamedahmed005/ecommerce-data-engine.git
cd ecommerce-data-engine

# create your local .env (Windows: copy .env.example .env)
cp .env.example .env

# start PostgreSQL in Docker
docker compose up -d
```

Check that it works:
```bash
docker compose ps                      # ecom_postgres should be "healthy"
pip install -r requirements.txt
python test_connection.py              # should print the Postgres version
```

> `.env` is local only and is never committed. Copy it from `.env.example` on every machine.
> To reset the database completely (deletes all data): `docker compose down -v`

## Data
The CSVs are not committed. Download the Olist Brazilian E-Commerce dataset from Kaggle and put the 9 files in `data/raw/`.

Download link: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

## Setup (optional: Python virtual environment)
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Load data
1. Put the 9 Olist CSVs in `data/raw/`
2. Run:
```bash
python ingestion/ingest_olist.py
```

## Expected row counts (original Olist dataset)
| table | rows |
|---|---|
| customers | 99,441 |
| geolocation | 1,000,163 |
| order_items | 112,650 |
| order_payments | 103,886 |
| order_reviews | 99,224 |
| orders | 99,441 |
| products | 32,951 |
| sellers | 3,095 |
| product_category_translation | 71 |

If your counts differ, check the CSVs before moving on.

## Layers
`raw` (as-is) → `staging` (typed/cleaned) → `warehouse` (star schema) ; `dq` holds quality-check results.

## Step 2: Profiling & data quality checks
```bash
python profiling/profile_raw.py
```
- Writes per-column stats to `dq.column_profile` and 38 check results to `dq.check_results`
- Generates `docs/profiling_report.md` — paste/adapt it into the Requirements and System Analysis docs
- Checks are grouped by category: uniqueness, integrity, completeness, validity, consistency
- To add a check, append a tuple to `CHECKS` in `profiling/profile_raw.py`

## Warehouse design
Star schema ERD and data dictionary: `docs/erd/warehouse_erd.md` (diagram: `docs/erd/warehouse_erd.png`).

## Step 3: Warehouse DDL (Gold layer)
Creates the empty star schema in the `warehouse` schema. Run it after the staging layer is built.

```bash
python warehouse/run_ddl.py
```

It runs `sql/warehouse/01_dimensions.sql` then `sql/warehouse/02_facts.sql`, and prints `OK` for each of the 8 tables. It is safe to re-run: it drops and recreates the warehouse tables and never touches `raw` or `staging`.

| Table | Type | Grain | Primary key |
|---|---|---|---|
| dim_date | dimension | one calendar day | date_key (YYYYMMDD) |
| dim_geography | dimension | one zip-code prefix | geography_key |
| dim_customer | dimension | one real customer (`customer_unique_id`) | customer_key |
| dim_product | dimension | one product | product_key |
| dim_seller | dimension | one seller | seller_key |
| fact_sales | fact | one order item | (order_id, order_item_id) |
| fact_payments | fact | one payment row of an order | (order_id, payment_sequential) |
| fact_reviews | fact | one review | (review_id, order_id) |

Design notes:
- Every dimension has a surrogate key; the natural key is kept as a `UNIQUE` attribute.
- Each dimension (except `dim_date`) has an **Unknown** member with key `-1`, so a fact row that cannot resolve a key points to it instead of being dropped.
- `fact_sales` has five role-playing date keys (purchase, approved, carrier, delivered, estimated). They are `NULL` when the event never happened.
- `fact_sales` carries the quality flags `is_valid_item`, `is_valid_sale` and `is_delivered`. Suspicious rows are flagged, never deleted. Definitions are in `docs/erd/warehouse_erd.md`.
- `order_id` is a degenerate dimension: `fact_payments` and `fact_reviews` link to `fact_sales` through `order_id` only, with no enforced FK.

Check the tables from the terminal:
```bash
docker exec -it ecom_postgres psql -U ecom -d ecom -c "\dt warehouse.*"
```

> Status: the tables are created empty. The ETL that loads them from `staging` is the next step.