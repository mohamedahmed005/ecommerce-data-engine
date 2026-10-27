# E-Commerce Data Engine

## Project structure
```
ecommerce-data-engine/
├── data/raw/          # Olist CSVs (not in Git, see below)
├── docs/              # profiling report + warehouse DQ report + docs/erd (warehouse ERD)
├── ingestion/         # raw loader
├── profiling/         # data quality profiling
├── scripts/           # helper scripts (run_pipeline, simulate_db_orders, run_queries, test_connection)
├── sql/init/          # schemas (run automatically by Docker)
├── sql/staging/       # staging layer SQL
├── sql/warehouse/     # warehouse DDL, load scripts, analytical queries, inventory
├── staging/           # staging runner + validation
├── warehouse/         # warehouse DDL, ETL, inventory generation, DQ checks
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
python scripts/test_connection.py      # should print the Postgres version
```

> `.env` is local only and is never committed. Copy it from `.env.example` on every machine.
> To reset the database completely (deletes all data): `docker compose down -v`

---

## Running the full pipeline with one command

You can run all stages end-to-end using `scripts/run_pipeline.py`:

```bash
# Standard pipeline run (original Olist data only)
python scripts/run_pipeline.py

# Run with Docker check/startup
python scripts/run_pipeline.py --docker

# Run with demo orders generated first (e.g. 380,000 orders)
python scripts/run_pipeline.py --replace-demo 380000 --batch-size 5000

# Run specific partial steps
python scripts/run_pipeline.py --from etl
python scripts/run_pipeline.py --only dq
```

---

## Data
The CSVs are not committed. Download the Olist Brazilian E-Commerce dataset from Kaggle and put the 9 files in `data/raw/`.

Download link: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

## Setup (optional: Python virtual environment)
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Step 1: Ingestion (Raw layer)
1. Put the 9 Olist CSVs in `data/raw/`
2. Run:
```bash
python ingestion/ingest_olist.py
```

### Expected row counts (original Olist dataset)
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

---

## Step 2: Profiling & data quality checks
```bash
python profiling/profile_raw.py
```
- Writes per-column stats to `dq.column_profile` and 38 check results to `dq.check_results`
- Generates `docs/profiling_report.md` — paste/adapt it into the Requirements and System Analysis docs
- Checks are grouped by category: uniqueness, integrity, completeness, validity, consistency
- To add a check, append a tuple to `CHECKS` in `profiling/profile_raw.py`

---

## Step 2b: Synthetic demo orders (Optional - for Dashboards & AI Assistant)
Adds realistic synthetic demo orders directly to the `raw` layer spanning **November 2018 to September 2026** (continuing seamlessly from where original Olist data ends).

```bash
# Add demo orders (default: 380,000, or specify custom N)
python scripts/simulate_db_orders.py --orders 380000 --batch-size 5000

# Replace existing demo orders with a fresh batch
python scripts/simulate_db_orders.py --orders 380000 --replace --batch-size 5000

# Remove demo orders completely (revert back to original Olist only)
python scripts/simulate_db_orders.py --remove
```

> **After generating or removing demo rows**, always rebuild the downstream layers:
> ```bash
> python staging/run_staging.py
> python warehouse/run_etl.py
> python warehouse/generate_inventory.py
> ```

### Key characteristics of the demo generator:
- **Timeline & Growth**: Covers 2018-11-01 to 2026-09-30 (~95 calendar months). Features gradual organic store growth combined with monthly seasonal variations (e.g. Q4 Black Friday & holiday peak).
- **Realistic Attributes**: Uses real product/seller pairs from original Olist history with slight price/freight variation; realistic review score distribution; realistic delivery lead times (~12.5 days avg) and cancellation rates (2%).
- **Batch Processing**: Uses a memory-safe generator and inserts data in configurable batches (`--batch-size 5000`) inside a single atomic transaction.
- **Safety**: Original Olist rows are never modified. All synthetic records carry `_source_file = 'synthetic_demo'` in `raw` and `is_synthetic = TRUE` in the `warehouse`. Analytical queries 1–5 and DQ reference checks continue testing original Olist records exclusively.

---

## Warehouse design
Star schema ERD and data dictionary: `docs/erd/warehouse_erd.md` (diagram: `docs/erd/warehouse_erd.png`).

---

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
- `fact_sales` carries the quality flags `is_valid_item`, `is_valid_sale`, `is_delivered`, and `is_synthetic`. Suspicious rows are flagged, never deleted.
- `order_id` is a degenerate dimension: `fact_payments` and `fact_reviews` link to `fact_sales` through `order_id` only, with no enforced FK.

Check the tables from the terminal:
```bash
docker exec -it ecom_postgres psql -U ecom -d ecom -c "\dt warehouse.*"
```

---

## Step 4: Warehouse ETL (staging -> Gold)
Loads the 8 warehouse tables from `staging` and validates the result. Run it after Step 3.

```bash
python warehouse/run_etl.py
```

It runs `sql/warehouse/03_load_dimensions.sql` (dimensions) then `sql/warehouse/04_load_facts.sql` (facts), then prints a validation report. It is safe to re-run: every run empties the warehouse tables and reloads them. It exits with an error if any check fails.

Rules:
- A key that cannot be resolved points to the Unknown member (`-1`); the row is kept.
- A date that does not exist (e.g. an order never delivered) stays `NULL`.
- `dim_customer` keeps one row per `customer_unique_id`, with the address of the customer's most recent order.
- `dim_geography` contains every zip in `staging.geolocation`, plus zips used by customers/sellers that geolocation lacks (coordinates `NULL`).
- `delivery_days` = delivered date - purchase date. `delay_days` = delivered date - estimated date (positive = late). Both are computed on calendar dates (time of day is ignored).
- Flags: `is_valid_item` = `price > 0` and `freight_value >= 0` and all keys resolved; `is_valid_sale` = `is_valid_item` and status not `canceled`/`unavailable`; `is_delivered` = status `delivered` and a delivered date exists; `is_synthetic` identifies rows generated by the demo script.

---

## Step 5: Analytical queries
SQL analytical queries in `sql/warehouse/05_analytical_queries.sql` are divided into 3 clear sections:
1. **Section A (Queries 1–5)**: Olist reference queries (`is_synthetic = FALSE`) used as deterministic benchmarks.
2. **Section B (Queries 6–17)**: Full-timeline analytics spanning 2016–2026 (Original + Demo data) for dashboard reporting and the AI analytics assistant.
3. **Section C (Queries 18–21)**: Inventory analytics tracking stock coverage, reorders, and stockouts.

Run them from the project root:
```bash
python scripts/run_queries.py
```

| # | Query | Section | What it measures |
|---|---|---|---|
| 1 | Reference: Monthly Sales Performance | A (Olist Reference) | Monthly revenue & orders (original benchmark) |
| 2 | Reference: Delivery Performance | A (Olist Reference) | Delivery delays, on-time rate (original benchmark) |
| 3 | Reference: Customer Review Analysis | A (Olist Reference) | Review score breakdown (original benchmark) |
| 4 | Reference: Payment Analysis | A (Olist Reference) | Payment types & volume (original benchmark) |
| 5 | Reference: Sales by Customer State | A (Olist Reference) | Geographic distribution (original benchmark) |
| 6 | Monthly Sales Performance (Full Timeline) | B (Full Timeline) | Continuous revenue & order trend (2016–2026) |
| 7 | Average Order Value and Monthly Growth | B (Full Timeline) | Monthly AOV and MoM sales growth rate |
| 8 | Top 10 Product Categories | B (Full Timeline) | Revenue & market share by category |
| 9 | Top 10 Products by Revenue | B (Full Timeline) | Best-selling products across all years |
| 10 | Top 10 Sellers by Revenue | B (Full Timeline) | Top merchants by sales volume |
| 11 | Delivery Performance (Full Timeline) | B (Full Timeline) | Delivery speed & late delivery rates |
| 12 | Delivery Delay vs Customer Reviews | B (Full Timeline) | Customer satisfaction impact of shipping delays |
| 13 | Customer Review Analysis (Full Timeline) | B (Full Timeline) | Rating distribution across all orders |
| 14 | Payment Analysis (Full Timeline) | B (Full Timeline) | Payment method shares and values |
| 15 | Sales by Customer State (Full Timeline) | B (Full Timeline) | Geographic sales volume and revenue share |
| 16 | Customer Spending & Repeat Orders | B (Full Timeline) | Customer retention and repeat purchase behavior |
| 17 | Order Status Breakdown by Month | B (Full Timeline) | Cancellation & fulfillment rates over time |
| 18 | Low-Stock Products | C (Inventory) | SKUs at or below reorder threshold |
| 19 | Monthly Inventory Health | C (Inventory) | Stock-out & low-stock rates over time |
| 20 | Stock Coverage by Category | C (Inventory) | Months of cover by product category |
| 21 | Best-Selling Products vs Current Stock | C (Inventory) | Top revenue products compared to closing stock |

---

## Step 6: Warehouse data quality checks
Independent automated tests on the Gold layer, separate from the validation inside `run_etl.py`:

```bash
python warehouse/run_dq_checks.py
```

It runs 69 comprehensive tests across the warehouse schema, logs results to `dq.warehouse_check_results`, and writes `docs/warehouse_dq_report.md`.

| Category | What it checks |
|---|---|
| Reconciliation | Row counts and sums (`price`, `freight_value`, `payment_value`) match `staging` |
| Uniqueness | No duplicate primary or composite keys in facts or dimensions |
| Referential integrity | All foreign keys resolve to dimension rows without orphans |
| Unknown members | No fact row unexpectedly defaults to the Unknown member (`-1`) |
| Completeness | Required measures, date keys, and statuses contain no unexpected `NULL`s |
| Validity | No negative prices, ratings outside 1–5, or delivery date paradoxes |
| Consistency | Quality flags align with timestamps and statuses |
| Olist reference results | Verifies exact known baseline metrics on original Olist records (112,101 valid sales, etc.) |
| Synthetic demo data | Verifies consistency of the `is_synthetic` flag across sales, payments, and reviews |
| Inventory (synthetic) | Validates stock continuity, movement math (`opening + received - sold = closing`), and reorder levels |

---

## Step 7: Synthetic inventory
Olist does not track inventory, so the warehouse generates `fact_inventory` based on actual monthly sales.

```bash
python warehouse/generate_inventory.py
```

Run after `python warehouse/run_etl.py`. It drops and recreates the table using `sql/warehouse/06_inventory.sql`.

| Table | Type | Grain | Primary key |
|---|---|---|---|
| fact_inventory | fact (synthetic) | one product per month (stock at month end) | (product_key, snapshot_date_key) |

| Column | Meaning |
|---|---|
| `product_key`, `snapshot_date_key` | Keys to `dim_product` and `dim_date` (last day of the month) |
| `opening_stock` | Stock at the start of the month |
| `units_received` | Simulated restock shipments |
| `units_sold` | Real valid-sale items of the product in that month |
| `closing_stock` | `opening_stock + units_received - units_sold` |
| `reorder_level` | Simulated reorder threshold |
| `is_low_stock` | `closing_stock <= reorder_level` |
