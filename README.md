# Olist E-Commerce Data Warehouse & AI Analytics Assistant

An end-to-end data engineering project built on the [Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce). It ingests raw CSVs, cleans them, models them as a star schema in PostgreSQL, validates data quality at every layer, and serves the results through a FastAPI backend with an executive dashboard and an AI analytics assistant.

## Table of Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Data Pipeline](#data-pipeline)
- [Warehouse Design](#warehouse-design)
- [Analytical Queries](#analytical-queries)
- [Data Quality](#data-quality)
- [Synthetic Data](#synthetic-data)
- [Web Application](#web-application)
- [Deployment (Azure App Service)](#deployment-azure-app-service)

---

## Features

- **Layered warehouse:** `raw` → `staging` → `warehouse` (Gold star schema), with a separate `dq` schema for quality results.
- **Automated data quality:** 38 profiling checks on raw data and 69 tests on the Gold layer, with generated Markdown reports.
- **Star schema:** 5 dimensions and 3 fact tables, plus a synthetic inventory fact table.
- **21 analytical queries** covering sales, delivery, reviews, payments, geography, customers, and inventory.
- **Executive dashboard:** KPIs, an interactive time explorer, revenue trend, top states, categories and sellers, payment mix, delivery and inventory insights, year filtering, data-scope switching (all data or original Olist only), and CSV / PDF export.
- **AI analytics assistant:** answers business questions in natural language (English and Arabic keywords) by routing them to approved SQL reports.
- **Performance:** connection pooling, a combined single-round-trip KPI query, and a one-hour in-memory cache with background pre-warming.
- **One-command pipeline:** run every stage end to end with `scripts/run_pipeline.py`.

## Screenshots

### Landing page

![Landing page](docs/images/landing.png)

### Executive dashboard

![Dashboard overview: time explorer and KPI cards](docs/images/dashboard-overview.png)

![Monthly sales and revenue trend with annual summary](docs/images/dashboard-revenue-trend.png)

![Top states by revenue and delivery SLA, payment methods](docs/images/dashboard-states-payments.png)

### AI analytics assistant

![Warehouse AI Copilot answering an inventory question](docs/images/chat-assistant.png)

### Warehouse ERD

![Star schema ERD](docs/erd/warehouse_erd.png)

## Tech Stack

| Area | Tools |
|---|---|
| Database | PostgreSQL (Docker locally, Azure Database for PostgreSQL for hosted data) |
| Pipeline | Python, SQL |
| Backend | FastAPI, Uvicorn, `psycopg2` `ThreadedConnectionPool` |
| Frontend | HTML, Tailwind CSS, Chart.js, vanilla JavaScript |
| Infrastructure | Docker Compose, Azure |

## Architecture

```
Olist CSVs ──► raw ──► staging ──► warehouse (star schema) ──► FastAPI ──► Dashboard / AI Assistant
                │          │              │
                └──────────┴──────────────┴──► dq (quality checks & reports)
```

| Layer | Purpose |
|---|---|
| `raw` | Data loaded as-is from the source files |
| `staging` | Typed and cleaned data |
| `warehouse` | Gold layer: star schema used by analytics |
| `dq` | Column profiles and data quality check results |

## Project Structure

```
ecommerce-data-engine/
├── api/               # FastAPI app (main.py, routers: analytics, chat, health)
├── data/raw/          # Olist CSVs (not in Git, see Data section)
├── docs/              # profiling report, warehouse DQ report, ERD, screenshots
├── ingestion/         # raw loader
├── profiling/         # raw data profiling and quality checks
├── scripts/           # run_pipeline, simulate_db_orders, run_queries, test_connection
├── sql/
│   ├── init/          # schemas (run automatically by Docker)
│   ├── staging/       # staging layer SQL
│   └── warehouse/     # DDL, load scripts, analytical queries, inventory
├── staging/           # staging runner and validation
├── warehouse/         # DDL runner, ETL, inventory generation, DQ checks
├── index.html         # Executive dashboard
├── chat.html          # AI analytics assistant
├── landing.html       # Landing page (entry point of the site)
├── enhance.js         # Shared UX layer for the three pages
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

## Getting Started

### Prerequisites

- Python 3.13
- Docker (only for the local database)
- The Olist CSV files (see [Data](#data))

### 1. Clone and install

```bash
git clone https://github.com/mohamedahmed005/ecommerce-data-engine.git
cd ecommerce-data-engine

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure the environment

```bash
cp .env.example .env     # Windows: copy .env.example .env
```

Set the connection variables in `.env`:

| Variable | Description |
|---|---|
| `POSTGRES_HOST` | `localhost` for Docker, or the Azure PostgreSQL server FQDN |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_DB` | Database name (`ecom`) |
| `POSTGRES_USER` | Database user |
| `POSTGRES_PASSWORD` | Database password |
| `PGSSLMODE` | `require` for Azure, omit or `prefer` locally |

> `.env` is local only and is never committed. Copy it from `.env.example` on every machine.

### 3. Choose a database

**Option A: Local database (Docker)**

```bash
docker compose up -d
docker compose ps                    # ecom_postgres should be "healthy"
python scripts/test_connection.py    # prints the Postgres version
```

Then build the warehouse with the [pipeline](#data-pipeline). To reset the local database completely (deletes all data): `docker compose down -v`.

**Option B: Existing Azure PostgreSQL database**

The warehouse data is already loaded in an Azure PostgreSQL database named `ecom`. Point your `.env` at it and skip the pipeline. Do not run the Docker or rebuild steps against this database.

### 4. Run the app

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

| Page | URL |
|---|---|
| Landing page | http://localhost:8000/ |
| Executive dashboard | http://localhost:8000/dashboard |
| AI assistant | http://localhost:8000/chat |
| API docs | http://localhost:8000/docs |
| Health check | http://localhost:8000/api/health |

## Data

The CSVs are not committed. Download the Olist dataset from [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) and place the 9 files in `data/raw/`.

| Table | Expected rows |
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

## Data Pipeline

### Run everything with one command

```bash
python scripts/run_pipeline.py                                   # standard run (original Olist data only)
python scripts/run_pipeline.py --docker                          # check/start Docker first
python scripts/run_pipeline.py --replace-demo 380000 --batch-size 5000   # generate demo orders first
python scripts/run_pipeline.py --from etl                        # resume from a stage
python scripts/run_pipeline.py --only dq                         # run a single stage
```

### Run stage by stage

| Step | Command | What it does |
|---|---|---|
| 1. Ingestion | `python ingestion/ingest_olist.py` | Loads the 9 CSVs into `raw` |
| 2. Profiling | `python profiling/profile_raw.py` | Writes column stats to `dq.column_profile`, 38 checks to `dq.check_results`, and `docs/profiling_report.md` |
| 3. Staging | `python staging/run_staging.py` | Builds typed, cleaned tables in `staging` |
| 4. Warehouse DDL | `python warehouse/run_ddl.py` | Creates the empty star schema (safe to re-run) |
| 5. Warehouse ETL | `python warehouse/run_etl.py` | Loads dimensions and facts, then validates |
| 6. Inventory | `python warehouse/generate_inventory.py` | Generates synthetic `fact_inventory` |
| 7. Queries | `python scripts/run_queries.py` | Runs the analytical queries |
| 8. DQ checks | `python warehouse/run_dq_checks.py` | Runs 69 Gold-layer tests and writes `docs/warehouse_dq_report.md` |

Profiling checks are grouped by uniqueness, integrity, completeness, validity, and consistency. To add one, append a tuple to `CHECKS` in `profiling/profile_raw.py`.

## Warehouse Design

Star schema ERD and data dictionary: `docs/erd/warehouse_erd.md` (diagram: `docs/erd/warehouse_erd.png`).

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
| fact_inventory | fact (synthetic) | one product per month | (product_key, snapshot_date_key) |

**Design notes**

- Every dimension has a surrogate key; the natural key is kept as a `UNIQUE` attribute.
- Each dimension (except `dim_date`) has an **Unknown** member with key `-1`. A fact row that cannot resolve a key points to it instead of being dropped.
- `fact_sales` has five role-playing date keys (purchase, approved, carrier, delivered, estimated). They are `NULL` when the event never happened.
- `fact_sales` carries the quality flags `is_valid_item`, `is_valid_sale`, `is_delivered`, and `is_synthetic`. Suspicious rows are flagged, never deleted.
- `order_id` is a degenerate dimension: `fact_payments` and `fact_reviews` link to `fact_sales` through `order_id` only, with no enforced FK.

**ETL rules**

- A date that does not exist (for example, an order never delivered) stays `NULL`.
- `dim_customer` keeps one row per `customer_unique_id`, with the address of the customer's most recent order.
- `dim_geography` contains every zip in `staging.geolocation`, plus zips used by customers or sellers that geolocation lacks (coordinates `NULL`).
- `delivery_days` = delivered date − purchase date. `delay_days` = delivered date − estimated date (positive = late). Both use calendar dates.
- `is_valid_item` = `price > 0` and `freight_value >= 0` and all keys resolved. `is_valid_sale` = `is_valid_item` and status not `canceled`/`unavailable`. `is_delivered` = status `delivered` and a delivered date exists.

**Synthetic inventory (`fact_inventory`)**

Olist does not track inventory, so it is generated from actual monthly sales via `sql/warehouse/06_inventory.sql`.

| Column | Meaning |
|---|---|
| `product_key`, `snapshot_date_key` | Keys to `dim_product` and `dim_date` (last day of the month) |
| `opening_stock` | Stock at the start of the month |
| `units_received` | Simulated restock shipments |
| `units_sold` | Real valid-sale items of the product in that month |
| `closing_stock` | `opening_stock + units_received - units_sold` |
| `reorder_level` | Simulated reorder threshold |
| `is_low_stock` | `closing_stock <= reorder_level` |

## Analytical Queries

All queries live in `sql/warehouse/05_analytical_queries.sql` (Gold layer) and are divided into three sections:

- **Section A (1–5):** Olist reference queries (`is_synthetic = FALSE`), used as deterministic benchmarks.
- **Section B (6–17):** Full-timeline analytics (2016–2026, original plus demo data) for the dashboard and AI assistant.
- **Section C (18–21):** Inventory analytics.

| # | Query | Section | What it measures |
|---|---|---|---|
| 1 | Reference: Monthly Sales Performance | A | Monthly revenue and orders |
| 2 | Reference: Delivery Performance | A | Delivery delays, on-time rate |
| 3 | Reference: Customer Review Analysis | A | Review score breakdown |
| 4 | Reference: Payment Analysis | A | Payment types and volume |
| 5 | Reference: Sales by Customer State | A | Geographic distribution |
| 6 | Monthly Sales Performance | B | Continuous revenue and order trend |
| 7 | Average Order Value and Monthly Growth | B | Monthly AOV and MoM growth |
| 8 | Top 10 Product Categories | B | Revenue and market share |
| 9 | Top 10 Products by Revenue | B | Best sellers across all years |
| 10 | Top 10 Sellers by Revenue | B | Top merchants by sales |
| 11 | Delivery Performance | B | Delivery speed and late rates |
| 12 | Delivery Delay vs Customer Reviews | B | Satisfaction impact of delays |
| 13 | Customer Review Analysis | B | Rating distribution |
| 14 | Payment Analysis | B | Payment method shares and values |
| 15 | Sales by Customer State | B | Geographic sales and revenue share |
| 16 | Customer Spending & Repeat Orders | B | Retention and repeat purchases |
| 17 | Order Status Breakdown by Month | B | Cancellation and fulfillment rates |
| 18 | Low-Stock Products | C | SKUs at or below reorder threshold |
| 19 | Monthly Inventory Health | C | Stock-out and low-stock rates |
| 20 | Stock Coverage by Category | C | Months of cover per category |
| 21 | Best-Selling Products vs Current Stock | C | Top products compared to closing stock |

Run them with `python scripts/run_queries.py`.

## Data Quality

`python warehouse/run_dq_checks.py` runs 69 tests on the warehouse schema, logs results to `dq.warehouse_check_results`, and writes `docs/warehouse_dq_report.md`. This is independent from the validation inside `run_etl.py`.

| Category | What it checks |
|---|---|
| Reconciliation | Row counts and sums (`price`, `freight_value`, `payment_value`) match `staging` |
| Uniqueness | No duplicate primary or composite keys |
| Referential integrity | All foreign keys resolve to dimension rows |
| Unknown members | No fact row unexpectedly defaults to `-1` |
| Completeness | Required measures, date keys, and statuses have no unexpected `NULL`s |
| Validity | No negative prices, ratings outside 1–5, or delivery date paradoxes |
| Consistency | Quality flags align with timestamps and statuses |
| Olist reference results | Known baseline metrics on original records (for example, 112,101 valid sales) |
| Synthetic demo data | `is_synthetic` flag is consistent across sales, payments, and reviews |
| Inventory (synthetic) | Stock continuity, movement math, and reorder levels |

## Synthetic Data

Optional. Adds realistic demo orders to the `raw` layer from November 2018 to September 2026, continuing where the original Olist data ends, so the dashboard and assistant have a longer timeline.

```bash
python scripts/simulate_db_orders.py --orders 380000 --batch-size 5000            # add demo orders
python scripts/simulate_db_orders.py --orders 380000 --replace --batch-size 5000  # replace with a fresh batch
python scripts/simulate_db_orders.py --remove                                     # back to original Olist only
```

After generating or removing demo rows, always rebuild the downstream layers:

```bash
python staging/run_staging.py
python warehouse/run_etl.py
python warehouse/generate_inventory.py
```

**Characteristics**

- Covers 2018-11-01 to 2026-09-30 (about 95 months) with gradual growth and seasonal peaks such as Black Friday and the holidays.
- Uses real product and seller pairs from the original data, with slight price and freight variation, realistic review scores, delivery lead times (about 12.5 days on average), and a 2% cancellation rate.
- Inserts in configurable batches inside a single atomic transaction.
- Original Olist rows are never modified. Synthetic rows carry `_source_file = 'synthetic_demo'` in `raw` and `is_synthetic = TRUE` in `warehouse`. Queries 1–5 and the DQ reference checks use original records only.

## Web Application

### Backend

- FastAPI app with entry point `api.main:app`.
- PostgreSQL access through `ThreadedConnectionPool` (`minconn=2`, `maxconn=10`).
- KPI and dashboard responses are cached in memory for one hour. A background thread pre-warms the full-timeline cache by year, then the original Olist summary.
- A combined CTE query returns sales, delivery, and review KPIs in one database round trip.

### Endpoints

| Endpoint | Description |
|---|---|
| `/api/analytics/dashboard` | Dashboard data. Supports `year` and `include_synthetic` |
| `/api/analytics/kpis` | Executive KPIs. Supports `year` and `include_synthetic` |
| `/api/health` | Database connection check |
| `/docs` | Interactive API documentation |

`include_synthetic` selects the data scope: original Olist data only, or the full timeline (Olist plus synthetic data).

### Pages

| Page | File | Description |
|---|---|---|
| Landing | `landing.html` | Entry point of the site, with live headline KPIs |
| Dashboard | `index.html` | Executive dashboard |
| Assistant | `chat.html` | AI analytics assistant |

`enhance.js` is a shared UX layer loaded by all three pages. It wraps the existing page functions without changing markup or API logic, and every feature is guarded so a failure never breaks the page.

- **Dashboard:** loading skeletons, animated KPI counters, month-over-month and year-over-year deltas, optional 60-second live refresh, revenue chart PNG download, sortable and searchable tables, keyboard shortcuts (`←` `→` to step through months, `r` to reload), and automatic recovery when the API comes back online. The selected year and data scope are remembered.
- **Landing:** headline KPI strip and scroll-reveal animations.
- **Assistant:** command history (`↑` `↓`), `/` to focus the input, automatic text direction, copy buttons, timestamps, scroll-to-bottom button, mobile quick-prompt chips, chat export to `.txt`, and chat persistence between visits.

### AI analytics assistant

`api/routers/chat.py` routes each question to an approved report using intent classification and supported keywords in English and Arabic.

Supported topics:

- Revenue, monthly sales, and average order value
- Top product categories and sellers
- Delivery times and delays, customer reviews, and payment methods
- Low-stock and reorder reports (the executive inventory summary also reports out-of-stock counts)
- Trending product recommendations with healthy stock, optionally filtered by category such as `health_beauty`

Example questions:

- `What is the total revenue and order count?`
- `Top 10 categories by revenue`
- `Show low stock products that need reorder`
- `Recommend trending products in stock`
- `Recommend products in health_beauty category`

## Deployment (Azure App Service)

The warehouse data is hosted on Azure Database for PostgreSQL. The web application is not deployed yet and currently runs locally. This section describes how to publish it to a public HTTPS URL using Azure App Service, connected to the existing database (no second database is needed). Docker Compose is for local development only.

### 1. Prepare the repository

- Keep `.env` out of Git (it is already in `.gitignore`). Never commit database passwords.
- Commit `landing.html`, `chat.html`, and `enhance.js`; otherwise those pages will be missing from the deployment.
- Make sure `requirements.txt` includes FastAPI and Uvicorn.

### 2. Create the App Service

In the Azure portal, create an **App Service** on **Linux** with **Python 3.13** and pick a plan for your workload (check the tier and estimated cost first). Use a globally unique app name.

Under **Deployment Center**, connect the GitHub repository and branch. Set the App Service setting `SCM_DO_BUILD_DURING_DEPLOYMENT` to `true` so Azure installs `requirements.txt`. The app will be available at `https://<app-name>.azurewebsites.net` and redeploy on every push.

### 3. Set the startup command

In **Settings → Configuration → General settings**, set **Startup Command** to:

```text
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Save and restart the App Service.

### 4. Configure the database connection

In **Settings → Environment variables → App settings**, add the values for the existing Azure PostgreSQL server. Set them in the Azure portal, never in Git or this README.

| App setting | Value |
|---|---|
| `POSTGRES_HOST` | Server FQDN, such as `your-server.postgres.database.azure.com` (not `localhost`) |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_DB` | Existing database name |
| `POSTGRES_USER` | Existing database user |
| `POSTGRES_PASSWORD` | Existing database password |
| `PGSSLMODE` | `require` |

Save the settings and restart the app.

### 5. Allow the app to reach PostgreSQL

If PostgreSQL uses **Public access**, add all current and possible outbound IP addresses of the App Service (found on its **Properties** page) to the server's firewall rules. If it uses **Private access**, connect the App Service to the database's virtual network. A firewall rule alone does not grant database access; keep PostgreSQL authentication enabled.

### 6. Verify

Open the app's default domain and check `/`, `/dashboard`, `/chat`, `/docs`, and `/api/health`. If startup or the database connection fails, review **Monitoring → Log stream**.

References: [Deploy a Python FastAPI app to App Service](https://learn.microsoft.com/en-us/azure/app-service/quickstart-python) · [Configure a Linux Python app](https://learn.microsoft.com/en-us/azure/app-service/configure-language-python) · [PostgreSQL firewall rules](https://learn.microsoft.com/en-us/azure/postgresql/security/security-firewall-rules)
