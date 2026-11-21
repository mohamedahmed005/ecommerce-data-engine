# 02. System Architecture

## Architectural Diagram

![System Architecture](images/architecture.png)

---

## High-Level Data Flow

```text
Olist CSVs (9 files) ──┐
                       ├──► raw (Bronze) ──► staging (Silver) ──► warehouse (Gold Star Schema)
Synthetic Simulator ───┘         │                 │                        │
                                 └─────────────────┴────────────────────────┴──► dq (Quality Audits)
                                                                            │
                                                                            ▼
                                                              FastAPI Backend (api/main.py)
                                                            ├── ThreadedConnectionPool (2–10)
                                                            ├── 1-Hour In-Memory Cache + Pre-warmer
                                                            ├── /api/analytics/*
                                                            ├── /api/recommendations/*
                                                            ├── /api/chat (EN/AR Intent Router)
                                                            └── /api/health
                                                                            │
                                                                            ▼
                                                    Presentation Layer (landing, dashboard, chat, /docs)
```

---

## Architectural Layers

### 1. Data Source Layer
- **Primary Source:** 9 Olist Brazilian E-Commerce CSV files stored locally in `data/raw/` (~1.55 million rows across all tables).
- **Optional Timeline Extension:** `scripts/simulate_db_orders .py` injects realistic synthetic transactions directly into `raw.*` covering late 2018 through September 2026, tagged with `_source_file = 'synthetic_demo'` so original benchmark records are never altered.

### 2. PostgreSQL Data Platform (Medallion Architecture)
Initialized via `sql/init/01_schemas.sql`, the database isolates data lifecycle stages into four schemas:

| Schema | Medallion Tier | Responsibility | Key Characteristics |
|---|---|---|---|
| `raw` | Bronze | Lossless source landing zone | All source columns loaded as `TEXT` via chunked `COPY`; appends `_source_file` and `_ingested_at` audit columns |
| `staging` | Silver | Cleaning, typing, deduplication | Enforces PostgreSQL types, normalizes text with `unaccent`, validates coordinates, creates anomaly flags and generated columns |
| `warehouse` | Gold | Analytics-ready dimensional model | Kimball star schema (5 dimensions, 3 core fact tables, 1 synthetic inventory fact table) with surrogate keys and indexes |
| `dq` | Governance | Observability & audit trail | Persists column profiles (`dq.column_profile`), raw checks (`dq.check_results`), and warehouse checks (`dq.warehouse_check_results`) |

### 3. Application Tier (FastAPI)
Served by Uvicorn (`api.main:app`), the backend connects exclusively to the `warehouse` schema (plus `information_schema` for `/api/health`) and exposes modular routers:
- **`api/db.py`:** Manages a global `psycopg2.pool.ThreadedConnectionPool` (`minconn=2`, `maxconn=10`, `connect_timeout=30`), returns dictionaries via `RealDictCursor`, automatically commits/rolls back transactions, closes broken connections on error, and parses numbered SQL queries directly from `sql/warehouse/05_analytical_queries.sql`.
- **`api/routers/analytics.py`:** Serves executive KPIs and multi-panel dashboard payloads with year filtering and data-scope switching (`include_synthetic`).
- **`api/routers/recommendations.py`:** Executes SQL-based hybrid scoring combining co-purchase history, category affinity, customer reviews, order velocity, price proximity, and live inventory availability.
- **`api/routers/chat.py`:** Routes natural-language English and Arabic queries to approved Gold-layer SQL reports, inventory-aware product recommendations, or executive KPI summaries.

### 4. Presentation Layer
Served directly by FastAPI `FileResponse` endpoints with zero frontend build pipeline required:
- **`/` (`landing.html`):** Entry point presenting project context and live headline KPIs.
- **`/dashboard` (`index.html`):** Executive analytics dashboard using Tailwind CSS and Chart.js with time exploration, year/scope filters, geographic and seller rankings, payment breakdown, inventory alerts, and CSV/PDF export.
- **`/chat` (`chat.html`):** Conversational AI Analytics Copilot rendering structured KPI summaries, tabular query outputs, and product recommendation cards.
- **`/enhance.js`:** Non-invasive progressive UX layer wrapped across all three pages (loading skeletons, animated counters, MoM/YoY deltas, 60s auto-refresh, chart PNG download, sortable/searchable tables, keyboard navigation, chat history persistence, RTL/LTR detection, and `.txt` export).
- **`/docs`:** Auto-generated OpenAPI/Swagger interactive API explorer.

### 5. Orchestration, CI/CD & Cloud Infrastructure
- **Local Pipeline Runner:** `scripts/run_pipeline.py` orchestrates Docker startup, ingestion, profiling, optional demo generation, staging, warehouse DDL/ETL, inventory simulation, DQ verification, and analytical query execution.
- **CI/CD Pipeline:** GitHub Actions (`.github/workflows/docker-publish.yml`) automatically builds the `Dockerfile` on pushes to `main` and publishes both `:latest` and `:<commit-sha>` tags to GitHub Container Registry (GHCR).
- **Cloud Hosting:** Azure Container Apps (`francecentral`, container port `8080`) runs the FastAPI image connected over TLS (`PGSSLMODE=require`) to Azure Database for PostgreSQL Flexible Server (`ecom`).

---

## Performance & Scalability Engineering

1. **High-Throughput Ingestion:** `ingestion/ingest_olist.py` disables `synchronous_commit`, creates `UNLOGGED` tables during bulk loading, streams CSV batches of `3,000` rows via `COPY ... FROM STDIN`, and converts tables back to `LOGGED` upon completion.
2. **Connection Pooling:** `ThreadedConnectionPool(minconn=2, maxconn=10)` avoids per-request TCP/TLS handshake overhead against Azure PostgreSQL.
3. **Single-Round-Trip KPI Aggregation:** `GET /api/analytics/kpis` executes a unified CTE query (`valid_items` → `orders_agg` → `rev_agg`) to compute sales, delivery, and review KPIs in a single database call.
4. **In-Memory TTL Caching & Background Pre-Warming:** `api/routers/analytics.py` caches results in `_CACHE` for **3,600 seconds (1 hour)** keyed by `(endpoint, include_synthetic, year)`. A daemon thread (`_warm_cache_background`) pre-warms the full-timeline overview, every individual calendar year, and the original Olist summary on application startup so UI filter switching responds near-instantly.
5. **Indexed Star Schema:** Dedicated B-tree indexes on `fact_sales` (`order_id`, `customer_key`, `product_key`, `seller_key`, `purchase_date_key`), `fact_payments` (`customer_key`, `payment_date_key`), `fact_reviews` (`order_id`, `customer_key`), and `fact_inventory` (`snapshot_date_key`).

---

## Security & Governance Design Decisions

- **Credential Isolation:** Database credentials are injected exclusively via `.env` locally or Azure Container Apps secret environment variables in production; `.env` is excluded via `.gitignore`.
- **Encrypted Transport:** `api/db.py` defaults to `PGSSLMODE=require` to enforce TLS encryption against Azure Database for PostgreSQL.
- **Zero Arbitrary SQL Generation:** The AI assistant (`api/routers/chat.py`) never sends user text to an LLM to synthesize raw SQL. Instead, it dispatches only pre-validated SQL queries from `sql/warehouse/05_analytical_queries.sql` or parameterized endpoint functions, eliminating SQL injection and numerical hallucination risks.
- **Non-Destructive Lineage:** Source anomalies are preserved and flagged rather than silently dropped, enabling exact cent-for-cent financial reconciliation between `staging` and `warehouse`.
