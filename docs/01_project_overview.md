# 01. Project Overview

## Executive Summary

The **Olist E-Commerce Data Engine** is an end-to-end data engineering, analytics, and decision-support platform built on the [Olist Brazilian E-Commerce Public Dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce). The system ingests raw multi-table transactional CSV exports into PostgreSQL, cleans and standardizes them through a Medallion-style pipeline (`raw` → `staging` → `warehouse`), enforces automated data quality gates (`dq`), and serves governed business intelligence through a FastAPI backend, an interactive executive dashboard, an inventory-aware hybrid recommendation engine, and a bilingual (English/Arabic) AI analytics assistant.

The live production deployment is hosted on Microsoft Azure:
- **Landing Page:** https://ecommerce-api-v2.icycliff-7a2355f7.francecentral.azurecontainerapps.io/
- **Executive Dashboard:** https://ecommerce-api-v2.icycliff-7a2355f7.francecentral.azurecontainerapps.io/dashboard
- **AI Analytics Assistant:** https://ecommerce-api-v2.icycliff-7a2355f7.francecentral.azurecontainerapps.io/chat
- **Interactive API Docs (Swagger UI):** https://ecommerce-api-v2.icycliff-7a2355f7.francecentral.azurecontainerapps.io/docs
- **Health Check:** https://ecommerce-api-v2.icycliff-7a2355f7.francecentral.azurecontainerapps.io/api/health

---

## Problem Statement

Raw e-commerce marketplace exports present recurring engineering and analytical obstacles that prevent direct business consumption:

1. **Fragmented Transactional Schemas:** Sales, orders, payments, reviews, customers, sellers, products, and geolocation reside across nine separate CSV files with inconsistent granularity (`order_id` vs. `order_item_id` vs. `payment_sequential`).
2. **Source Data Anomalies:** The Olist dataset contains real-world quality issues—including duplicate `review_id` records across orders, over 261,000 duplicate geolocation rows, coordinates outside Brazil, orders marked `delivered` without delivery timestamps, missing product categories, zero-gram product weights, and per-order `customer_id` identifiers that obscure repeat customer behavior.
3. **Lack of Inventory Visibility:** Marketplace sales logs track demand but contain no stock-level snapshots, preventing low-stock monitoring or inventory-aware merchandising recommendations.
4. **Analytical Latency & Accessibility:** Executives and non-technical stakeholders need instant, trustworthy KPI access without writing complex multi-fact SQL queries or risking metric double-counting.

---

## Solution Overview

The platform resolves these challenges through five integrated pillars:

1. **Medallion PostgreSQL Data Architecture:** Strict separation of concerns across four schemas (`raw`, `staging`, `warehouse`, and `dq`), preserving raw lineage while exposing a Kimball star schema in the Gold layer.
2. **Non-Destructive Data Quality Governance:** Suspicious or incomplete records are explicitly flagged (`is_valid_item`, `is_valid_sale`, `is_delivered`) rather than silently deleted, backed by **38 raw profiling checks**, **25 staging assertions**, and **69 Gold-layer warehouse tests**.
3. **Synthetic Inventory & Timeline Extension:** A deterministic monthly inventory simulator (`warehouse.fact_inventory`) derived from real Olist sales, plus an optional synthetic order generator (`raw._source_file = 'synthetic_demo'`, `warehouse.is_synthetic = TRUE`) extending the timeline from late 2018 through September 2026 while keeping benchmark Olist records strictly isolated.
4. **High-Performance Serving Layer:** A FastAPI service powered by `psycopg2.pool.ThreadedConnectionPool`, single-round-trip CTE queries, and a 1-hour in-memory TTL cache pre-warmed on startup.
5. **Interactive Web & AI Interfaces:** A responsive Executive Dashboard (`index.html`), a bilingual SQL-grounded AI Analytics Assistant (`chat.html`), an Inventory-Aware Recommendation API (`/api/recommendations/*`), and a shared UX enhancement layer (`enhance.js`).

---

## Source Dataset Overview

The foundation dataset consists of 9 CSV files placed under `data/raw/` (excluded from Git):

| Source CSV File | Raw Table (`raw.*`) | Expected Rows | Domain |
|---|---|---:|---|
| `olist_customers_dataset.csv` | `raw.customers` | 99,441 | Per-order customer IDs, unique customer IDs, locations |
| `olist_geolocation_dataset.csv` | `raw.geolocation` | 1,000,163 | Brazilian zip-code prefixes and lat/lng coordinates |
| `olist_order_items_dataset.csv` | `raw.order_items` | 112,650 | Item-level pricing, freight, product, seller, shipping limit |
| `olist_order_payments_dataset.csv` | `raw.order_payments` | 103,886 | Payment sequences, payment types, installments, values |
| `olist_order_reviews_dataset.csv` | `raw.order_reviews` | 99,224 | Customer review scores (1–5), comments, timestamps |
| `olist_orders_dataset.csv` | `raw.orders` | 99,441 | Order lifecycle timestamps and fulfillment status |
| `olist_products_dataset.csv` | `raw.products` | 32,951 | Product catalog attributes, Portuguese categories, dimensions |
| `olist_sellers_dataset.csv` | `raw.sellers` | 3,095 | Merchant locations and identifiers |
| `product_category_name_translation.csv` | `raw.product_category_translation` | 71 | Portuguese-to-English category lookup |

---

## Technology Stack

| Layer | Technologies & Libraries | Role |
|---|---|---|
| **Database** | PostgreSQL 16 (Docker locally), Azure Database for PostgreSQL Flexible Server | Relational storage for `raw`, `staging`, `warehouse`, and `dq` schemas |
| **ETL & Quality** | Python (`psycopg2-binary==2.9.10`, `python-dotenv==1.0.1`), PostgreSQL SQL | Chunked `COPY` ingestion, SQL transformations, profiling, DQ checks, simulation |
| **Backend API** | FastAPI (`0.162.7`), Uvicorn (`0.54.0`), `ThreadedConnectionPool` | REST API, analytical caching, hybrid recommendations, AI intent router |
| **Frontend UI** | HTML5, Tailwind CSS, Chart.js, Vanilla JavaScript (`enhance.js`) | Landing page, executive dashboard, bilingual chat UI, CSV/PDF/PNG export |
| **DevOps & Cloud** | Docker (`python:3.11-slim`), Docker Compose, GitHub Actions, GHCR, Azure Container Apps | Automated container builds, registry publishing, and cloud hosting |

---

## Repository Structure

```text
ecommerce-data-engine/
├── .github/workflows/
│   └── docker-publish.yml          # CI/CD workflow building & pushing Docker images to GHCR
├── api/
│   ├── main.py                     # FastAPI entry point, static routes, CORS, /api/health
│   ├── db.py                       # ThreadedConnectionPool, query helpers, SQL query loader
│   └── routers/
│       ├── analytics.py            # /api/analytics/kpis, /api/analytics/dashboard, TTL cache
│       ├── recommendations.py      # /api/recommendations/* inventory-aware hybrid engine
│       └── chat.py                 # POST /api/chat bilingual SQL-grounded assistant
├── data/raw/                       # Local Olist CSV files (not tracked in Git)
├── docs/                           # Technical documentation, ERD, DQ reports, screenshots
├── ingestion/
│   └── ingest_olist.py             # Chunked COPY ingestion into raw.*
├── profiling/
│   └── profile_raw.py              # Column profiling + 38 raw DQ checks
├── scripts/
│   ├── run_pipeline.py             # Single-command end-to-end pipeline orchestrator
│   ├── run_queries.py              # CLI runner for all 21 Gold-layer analytical queries
│   ├── simulate_db_orders .py      # Optional synthetic order generator (2018–2026)
│   └── test_connection.py          # PostgreSQL connectivity smoke test
├── sql/
│   ├── init/01_schemas.sql         # Medallion schema initialization (raw, staging, warehouse, dq)
│   ├── staging/                    # 00_extensions.sql .. 03_facts.sql
│   └── warehouse/                  # 01_dimensions.sql .. 06_inventory.sql, checks.sql
├── staging/run_staging.py          # Staging SQL executor + 25 validation assertions
├── warehouse/
│   ├── run_ddl.py                  # Gold-layer DDL runner
│   ├── run_etl.py                  # Gold-layer dimension/fact loader + 31 inline checks
│   ├── generate_inventory.py       # Deterministic synthetic monthly inventory simulator
│   └── run_dq_checks.py            # 69 independent Gold-layer DQ tests + Markdown report
├── landing.html                    # Site entry page with live headline KPIs
├── index.html                      # Executive analytics dashboard
├── chat.html                       # AI analytics assistant interface
├── enhance.js                      # Non-invasive shared UX enhancement layer
├── Dockerfile                      # Production container definition (port 8080)
├── docker-compose.yml              # Local PostgreSQL 16 service with healthcheck
├── .env.example                    # Environment variable template
└── requirements.txt                # Pinned Python runtime dependencies
```

---

## Documentation Map

- [02. System Architecture](02_system_architecture.md)
- [03. Data Pipeline & ETL](03_data_pipeline.md)
- [04. Data Warehouse Design](04_data_warehouse.md)
- [05. Data Quality Framework](05_data_quality.md)
- [06. API Documentation](06_api_documentation.md)
- [07. AI Analytics Assistant](07_ai_assistant.md)
- [08. Setup & Installation](08_setup_and_installation.md)
- [09. Deployment Guide](09_deployment_guide.md)
