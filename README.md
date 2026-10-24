# E-Commerce Data Engine

## Project structure
```
ecommerce-data-engine/
├── data/raw/          # Olist CSVs (not in Git, see below)
├── docs/              # profiling report + docs/erd (warehouse ERD)
├── ingestion/         # raw loader
├── profiling/         # data quality profiling
├── scripts/           # helper scripts (connection test, analytical query runner)
├── sql/init/          # schemas (run automatically by Docker)
├── sql/staging/       # staging layer SQL
├── sql/warehouse/     # warehouse DDL, load scripts, analytical queries
├── staging/           # staging runner + validation
├── warehouse/         # warehouse DDL + ETL runners
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
- `delivery_days` = delivered date - purchase date. `delay_days` = delivered date - estimated date (positive = late). Both are computed on calendar dates (time of day is ignored), so an order delivered later on the estimated day counts as on time.
- Flags: `is_valid_item` = `price > 0` and `freight_value >= 0` and all keys resolved; `is_valid_sale` = `is_valid_item` and status not `canceled`/`unavailable`; `is_delivered` = status `delivered` and a delivered date exists.
- Orders without items (775) have no row in `fact_sales`; their payments and reviews are still loaded.

Validation results on the full Olist data:

| Table | Rows |
|---|---|
| dim_customer | 96,096 |
| dim_seller | 3,095 |
| dim_product | 32,951 |
| dim_geography | 19,173 |
| dim_date | 800 |
| fact_sales | 112,650 |
| fact_payments | 103,886 |
| fact_reviews | 99,224 |

Totals match staging to the cent: `sum(price)` 13,591,643.70, `sum(freight_value)` 2,251,909.54, `sum(payment_value)` 16,008,872.12. No fact points to an Unknown member and there are no duplicate keys. In `fact_sales`: 112,101 rows are valid sales, 549 are not (canceled/unavailable orders), 110,189 are delivered, and 7,265 were delivered late (counted per order item).

## Step 5: Analytical queries
SQL analytical queries on the Gold layer provide business insights into sales performance, delivery operations, payments, and customer reviews. They are in `sql/warehouse/05_analytical_queries.sql`.

Run them all from the project root (connection settings are read from `.env`):

```bash
python scripts/run_queries.py
```

To run a different SQL file, pass its path: `python scripts/run_queries.py path/to/file.sql`. The runner executes each query that starts with a `-- N. Title` comment and prints its result as a table.

| # | Query | What it measures |
|---|---|---|
| 1 | Monthly Sales Performance | Monthly sales revenue, freight costs, and number of orders |
| 2 | Top Products | Top 10 products by sales revenue, items sold, and orders |
| 3 | Top Sellers | Top 10 sellers by sales revenue, items sold, and orders |
| 4 | Delivery Performance | Average delivery time, average net delay, average delay of late orders, late and on-time/early orders, late-order percentage |
| 5 | Customer Review Analysis | Review score distribution, percentages, and the overall average score (weighted by reviews per score) |
| 6 | Payment Analysis | Payment methods by records, orders, total and average payment value |
| 7 | Delivery Delay vs. Customer Reviews | Average review score of late vs. on-time/early deliveries |
| 8 | Top Product Categories | Top 10 categories by sales revenue, items sold, orders, and share of total sales |
| 9 | Average Order Value and Monthly Growth | Monthly average order value and sales growth compared with the previous month |
| 10 | Sales by Customer State | Sales, orders, unique customers, and sales share per state |
| 11 | Customer Spending and Repeat Orders | Average spending, orders per customer, repeat customers and their percentage |
| 12 | Delivery Performance by State | Average delivery time and late-order percentage per customer state |
| 13 | Top Sellers by Satisfaction | Top 10 sellers by average review score (with sales and late-order percentage) |
| 14 | Order Status Breakdown by Month | Canceled and unavailable orders per month |
| 15 | Credit Card Installments | Credit-card payments grouped by number of installments |

Technical notes:
- All queries use PostgreSQL and tables in the `warehouse` schema.
- Sales queries (1-3 and 8-11) use the `is_valid_sale` flag to exclude items that do not meet the valid-sale criteria.
- Delivery queries (4, 7, 12 and 13) use the `is_delivered` flag, which already excludes canceled and unavailable orders. They are aggregated at the **order** level so multi-item orders are counted once. This is why Query 4 reports fewer late orders than the item-level count in Step 4.
- An order is **late** when `delay_days > 0`, i.e. delivered at least one full calendar day after the estimated date. `avg_delay_days` is the net delay (early deliveries count as negative); `avg_delay_days_late_only` averages late orders only.
- In Queries 7 and 13, reviews are averaged per order first, then joined to delivery data.
- `dim_customer` has one row per real customer (`customer_unique_id`), so Queries 10-12 count a returning customer once. The customer's state is the address of their most recent order.
- Thresholds: Query 12 only shows states with at least 100 delivered orders, and Query 13 only sellers with at least 50 delivered orders, so percentages are reliable.
- Query 9 compares each month with the previous month that has data (the dataset has no orders in November 2016). Growth is shown only when both months have at least 100 orders, because the first and last months of the dataset are very small.
- Query 14 counts only orders that have at least one item in `fact_sales`. Almost all `unavailable` orders have no items, so they are not counted here, and the canceled percentage is also understated.
- Query 15 groups credit-card payments only, because installments are a credit-card feature.
- Sales revenue (`price`) and recorded payment value (`payment_value`) are analyzed separately because they represent different business measures. `payment_value` includes freight and installment effects, so its total will not equal the total of `price` in Query 1.

Results on the full Olist data:

| Metric | Value |
|---|---|
| Valid sales (Query 1, all months) | 13,494,400.74 |
| Delivered orders | 96,470 |
| Average delivery time | 12.50 days |
| Late orders | 6,534 (6.77%) |
| Overall average review score | 4.09 |
| Average review: late vs. on-time/early | 2.27 vs. 4.29 |
| Top payment method | credit_card (12,542,084.19) |

These queries are the foundation for business reporting, dashboards, and the project's AI-powered analytics assistant.

## Step 6: Warehouse data quality checks
Independent tests on the Gold layer, separate from the validation inside `run_etl.py`. Run it after Step 4:

```bash
python warehouse/run_dq_checks.py
```

It runs 54 checks, prints one line per check, stores every result in `dq.warehouse_check_results` (one `run_id` per run, so history is kept), and writes `docs/warehouse_dq_report.md`. It exits with an error if any `error`-severity check fails.

Each check is one SQL query that returns a single number and passes when it equals the expected value (0 for most checks).

| Category | What it checks |
|---|---|
| Reconciliation | Warehouse row counts and sums (`price`, `freight_value`, `payment_value`) match `staging`; dimension sizes match distinct natural keys |
| Uniqueness | No duplicate fact grain keys or natural keys in dimensions |
| Referential integrity | Every foreign key (customer, product, seller, date keys) resolves to a dimension row; optional date keys may be `NULL` |
| Unknown members | No fact row points to the Unknown member (`-1`) |
| Completeness | No `NULL` in required measure and key columns |
| Validity | No negative amounts, review scores within 1-5; warnings for suspicious values (delivery before purchase, delivery over 365 days, payments of value 0) |
| Consistency | Quality flags agree with order status and dates (`is_valid_sale`, `is_delivered`, `delay_days`) |
| Known results (Olist) | Counts documented in Step 4 (112,101 valid sales, 549 not valid, 110,189 delivered, 775 orders without items) |

Severity:
- `error`: a mismatch is a **FAIL** and stops the pipeline.
- `warn`: a mismatch is reported as **WARN** (a data anomaly to document, not a pipeline failure).

To add a check, call `add(...)` in `warehouse/run_dq_checks.py`. The "Known results" checks are specific to the Olist dataset; remove them if the data changes.
