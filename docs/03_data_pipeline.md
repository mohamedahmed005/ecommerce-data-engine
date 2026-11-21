# 03. Data Pipeline & ETL

## End-to-End Pipeline Overview

The data pipeline transforms raw Olist CSV files into a validated dimensional warehouse and analytical report suite. Every stage is idempotent and safely re-runnable.

```text
[1. Ingest CSVs] ──► [2. Profile Raw] ──► [3. Optional Synthetic Orders]
                                                     │
                                                     ▼
[4. Staging SQL + Checks] ──► [5. Warehouse DDL] ──► [6. Warehouse ETL + Checks]
                                                               │
                                                               ▼
                     [7. Synthetic Inventory] ──► [8. Warehouse DQ (69 Tests)] ──► [9. Analytical Queries (21)]
```

---

## Single-Command Orchestration (`scripts/run_pipeline.py`)

The core pipeline (`staging` → `ddl` → `etl` → `inventory` → `dq` → `queries`) can be executed from the project root with one command:

```bash
# Standard core rebuild (assumes raw tables already exist)
python scripts/run_pipeline.py

# Full cold start: start Docker Postgres, ingest CSVs, profile raw, build warehouse & verify
python scripts/run_pipeline.py --docker --ingest

# Rebuild with 380,000 synthetic demo orders (replacing any prior demo batch)
python scripts/run_pipeline.py --replace-demo 380000 --batch-size 5000

# Resume from a specific stage
python scripts/run_pipeline.py --from etl

# Run a single stage only
python scripts/run_pipeline.py --only dq
```

### Supported CLI Flags

| Flag | Description |
|---|---|
| `--docker` | Runs `docker compose up -d` and polls PostgreSQL until ready (90s timeout) |
| `--ingest` | Prepends `ingestion/ingest_olist.py` and `profiling/profile_raw.py` before core stages |
| `--demo N` | Appends `N` synthetic demo orders via `scripts/simulate_db_orders .py` |
| `--replace-demo N` | Removes existing synthetic demo rows and generates `N` fresh demo orders |
| `--remove-demo` | Deletes synthetic demo rows, restoring original Olist data only |
| `--batch-size N` | Orders per DB round-trip during demo generation (default: `5000`) |
| `--from STEP` | Starts execution at `STEP` (`staging`, `ddl`, `etl`, `inventory`, `dq`, `queries`) |
| `--only STEP` | Runs only one step (`ingest`, `profile`, `demo`, or any core step) |
| `--keep-going` | Continues running subsequent steps even if a step fails |
| `--quiet` | Suppresses stdout/stderr for passing steps (displays output only on failure) |
| `--dry-run` | Prints planned execution commands without executing them |
| `--list` | Lists all optional and core pipeline steps |

---

## Stage-by-Stage Technical Breakdown

### Stage 1: Raw Ingestion (`ingestion/ingest_olist.py`)
- **Command:** `python ingestion/ingest_olist.py [--data-dir data/raw]`
- **Behavior:**
  1. Verifies all 9 Olist CSV files exist in `--data-dir`.
  2. Connects with TCP keepalives enabled (`keepalives_idle=20`, `keepalives_interval=10`, `keepalives_count=5`) and `SET synchronous_commit = OFF;` for Azure PostgreSQL stability.
  3. Terminates idle competing sessions for the current user/database to avoid DDL lock contention.
  4. For each CSV, drops and recreates `raw.<table>` as an `UNLOGGED` table with all CSV headers defined as `TEXT`, plus audit columns `_source_file TEXT DEFAULT '<filename>'` and `_ingested_at TIMESTAMPTZ DEFAULT now()`.
  5. Streams rows in chunks of `BATCH_ROWS = 3000` using PostgreSQL `COPY ... FROM STDIN WITH (FORMAT csv, HEADER false, ENCODING 'UTF8')`.
  6. Converts each table back to crash-safe `LOGGED` storage via `ALTER TABLE raw.<table> SET LOGGED`.

### Stage 2: Raw Profiling (`profiling/profile_raw.py`)
- **Command:** `python profiling/profile_raw.py`
- **Behavior:**
  - Profiles every non-metadata column across all 9 `raw.*` tables (row count, null count, null %, distinct count, min/max values) and writes results to `dq.column_profile`.
  - Executes **38 raw data quality checks** across uniqueness, integrity, completeness, validity, and consistency, storing results in `dq.check_results` and generating `docs/profiling_report.md`.

### Stage 3: Optional Synthetic Data Generation (`scripts/simulate_db_orders .py`)
> **Filename Note:** The script file in the repository is named `scripts/simulate_db_orders .py` (containing a space before `.py`), which `scripts/run_pipeline.py` invokes automatically. When running it directly from the shell, quote the path: `python "scripts/simulate_db_orders .py" --orders 380000 --replace --batch-size 5000`.

- **Purpose:** Extends the transactional timeline beyond October 2018 (covering late 2018 through September 2026) so time-series charts and AI assistant trends span a multi-year window.
- **Design & Safety Guarantees:**
  - Deterministic seed (`SEED = 20261026`).
  - Samples real `(product_id, seller_id)` pairs, price distributions, and review score distributions from original Olist history.
  - Allocates monthly order counts using gradual growth (~55% to ~145% of mean) with November/December seasonal peaks via the largest-remainder method so total count is exact.
  - Simulates 98% `delivered` and 2% `canceled` orders, ~3% returning customers, and ~70% review rate on delivered orders.
  - Inserts rows across `raw.orders`, `raw.customers`, `raw.order_items`, `raw.order_payments`, and `raw.order_reviews` in configurable batches inside a **single atomic transaction** (all-or-nothing rollback on failure).
  - Tags every generated record with `_source_file = 'synthetic_demo'`. Original Olist rows are never modified or deleted; `--remove` / `--replace` delete strictly where `_source_file = 'synthetic_demo'`.

### Stage 4: Staging Layer (`staging/run_staging.py`)
- **Command:** `python staging/run_staging.py`
- **SQL Execution Order (`sql/staging/`):**
  1. `00_extensions.sql`: Installs `unaccent` extension and ensures `staging` schema exists.
  2. `01_reference.sql`:
     - `staging.category_translation`: Combines 71 official Olist translations with 2 missing Portuguese categories (`pc_gamer` → `pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos` → `portable_kitchen_food_preparers`) for 73 total mappings.
     - `staging.geolocation`: Filters out non-Brazil coordinates (`lat BETWEEN -34 AND 6`, `lng BETWEEN -74 AND -34`), averages coordinates per `zip_code_prefix`, normalizes city (`lower(unaccent(trim(...)))`) and state (`upper(trim(...))`), and picks modal city/state.
  3. `02_dimensions.sql`:
     - `staging.customers`: Normalizes city/state, checks `zip_in_geolocation`, indexes `customer_unique_id`.
     - `staging.sellers`: Normalizes city/state, adds `flag_city_suspect` (`~ '[0-9@/,]'`) and `zip_in_geolocation`.
     - `staging.products`: Joins `category_translation`, defaults missing categories to `'unknown'`, fixes source typos (`product_name_lenght` → `name_length`, `product_description_lenght` → `description_length`), converts invalid `0g` weight to `NULL`, and adds `flag_missing_category` and `flag_zero_weight`.
  4. `03_facts.sql`:
     - `staging.orders`: Casts all 5 timestamps, aggregates item/payment totals, sets 5 anomaly flags (`flag_delivered_no_date`, `flag_delivery_date_not_delivered`, `flag_carrier_before_purchase`, `flag_delivered_before_carrier`, `flag_payment_mismatch` > R$1.00), and adds two `GENERATED ALWAYS ... STORED` boolean columns: `has_date_anomaly` and `is_valid_sale` (`has_items AND order_status NOT IN ('canceled', 'unavailable')`).
     - `staging.order_items`: Casts `order_item_id`, `price`, `freight_value`, `shipping_limit_ts`; flags pre-synthetic `>= 2019-01-01` shipping limits (`flag_shipping_limit_outlier`).
     - `staging.order_payments`: Normalizes 0 installments to 1 via `GREATEST(payment_installments::int, 1)` with `flag_installments_fixed`, and flags `not_defined` payment types.
     - `staging.order_reviews`: Deduplicates on `(review_id, order_id)` keeping the latest `review_answer_timestamp`, marks `is_latest_for_order`, and flags `flag_review_before_purchase`.
- **Inline Validation:** Runs **25 SQL assertions** comparing staging counts against `raw` and verifying that every anomaly count matches the profiling report.

### Stage 5: Warehouse DDL (`warehouse/run_ddl.py`)
- **Command:** `python warehouse/run_ddl.py`
- Executes `sql/warehouse/01_dimensions.sql` and `sql/warehouse/02_facts.sql` to recreate the 5 dimensions (including `-1` Unknown members) and 3 core fact tables, then verifies all 8 expected tables exist in `information_schema.tables`.

### Stage 6: Warehouse ETL (`warehouse/run_etl.py`)
- **Command:** `python warehouse/run_etl.py`
- Executes `sql/warehouse/03_load_dimensions.sql` and `sql/warehouse/04_load_facts.sql`:
  1. Truncates all warehouse tables (`RESTART IDENTITY CASCADE`) and re-inserts `-1` Unknown members.
  2. Populates `dim_date` across the full contiguous date span (`min` to `max` across all order and review timestamps via `generate_series`).
  3. Populates `dim_geography` from `staging.geolocation` unioned with customer/seller zip prefixes absent from geolocation (with `NULL` lat/lng).
  4. Populates `dim_customer` deduplicated to one row per `customer_unique_id`, taking the address from each customer's most recent order (`DISTINCT ON ... ORDER BY purchase_ts DESC NULLS LAST`).
  5. Populates `dim_seller` and `dim_product`.
  6. Loads `fact_sales`, `fact_payments`, and `fact_reviews` using `COALESCE(..., -1)` for unresolved surrogate keys, computing `delivery_days`, `delay_days`, quality flags, and `is_synthetic` (derived from `raw.orders._source_file = 'synthetic_demo'`).
  7. Runs `ANALYZE;` to refresh PostgreSQL query planner statistics.
- **Inline Validation:** Runs **31 validation queries** verifying row counts, exact monetary totals (`price`, `freight_value`, `payment_value`), zero unexpected `-1` references, primary key uniqueness, and flag consistency.

### Stage 7: Synthetic Inventory Generation (`warehouse/generate_inventory.py`)
- **Command:** `python warehouse/generate_inventory.py`
- Executes `sql/warehouse/06_inventory.sql` and populates `warehouse.fact_inventory` using deterministic `SEED = 42`:
  - Uses **original Olist valid sales only** (`is_valid_sale = TRUE AND is_synthetic = FALSE`) to avoid simulating across the multi-year synthetic gap.
  - Tracks each product from its first sale month up to the last month with `>= 100` orders (`MIN_ORDERS_LAST_MONTH = 100`).
  - Simulation rules per product:
    - `reorder_level = max(2, ceil(1.5 * avg_monthly_sales))`
    - `order_up_to = max(reorder_level + 3, ceil(3.0 * avg_monthly_sales)) + rng.randint(0, 3)`
    - Initial stock = `ceil(2.5 * avg_monthly_sales) + rng.randint(0, 5)`
    - When `opening_stock <= reorder_level`, a replenishment order is triggered with simulated supply-chain friction: **15% partial delivery** (`received // 2`) and **10% delayed delivery** (`received = 0`).
    - **Emergency receipt safeguard:** If `opening_stock + units_received < units_sold`, extra units are received so `closing_stock` is never negative.
  - Bulk-inserts via `psycopg2.extras.execute_values` (`page_size=5000`).

### Stage 8 & 9: Quality Verification & Analytical Queries
- `python warehouse/run_dq_checks.py` runs **69 independent Gold-layer tests**, logs results to `dq.warehouse_check_results`, and writes `docs/warehouse_dq_report.md`.
- `python scripts/run_queries.py` executes and formats all **21 analytical queries** in `sql/warehouse/05_analytical_queries.sql`.
