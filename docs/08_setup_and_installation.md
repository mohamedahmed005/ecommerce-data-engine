# 08. Setup & Installation Guide

## Prerequisites

- **Python:** 3.11+ (tested with Python 3.11 in Docker and Python 3.13 locally)
- **Git:** For cloning the repository
- **Docker & Docker Compose:** Required only for running the local PostgreSQL 16 database (`Option A`)
- **Olist Dataset CSVs:** Required only if building the database locally from scratch (download from [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce))

---

## Step 1: Clone Repository & Create Virtual Environment

```bash
git clone https://github.com/mohamedahmed005/ecommerce-data-engine.git
cd ecommerce-data-engine
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Pinned Dependencies (`requirements.txt`)
```text
psycopg2-binary==2.9.10
python-dotenv==1.0.1
fastapi==0.162.7
uvicorn==0.54.0
```

---

## Step 2: Configure Environment Variables

Copy the template file and edit `.env` (never commit `.env` to Git):

```bash
# macOS / Linux
cp .env.example .env

# Windows CMD
copy .env.example .env
```

### `.env` Variable Reference

| Variable | Local Docker Example | Azure PostgreSQL Example | Notes |
|---|---|---|---|
| `POSTGRES_HOST` | `localhost` | `<server>.postgres.database.azure.com` | Database hostname |
| `POSTGRES_PORT` | `5432` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `ecom` | `ecom` | Target database name |
| `POSTGRES_USER` | `ecom` | `<azure_admin_user>` | Database user |
| `POSTGRES_PASSWORD` | `ecom_pass` | `<secure_password>` | Database password |
| `PGSSLMODE` | `prefer` *(or `disable`)* | `require` | **Important:** `api/db.py` defaults to `require` if unset; set `PGSSLMODE=prefer` when running the FastAPI app against local Docker Postgres |

---

## Step 3: Database Setup (Choose Option A or Option B)

### Option A: Local PostgreSQL via Docker Compose (Full Local Build)

1. **Place the 9 Olist CSV files** inside `data/raw/`:
   - `olist_customers_dataset.csv`
   - `olist_geolocation_dataset.csv`
   - `olist_order_items_dataset.csv`
   - `olist_order_payments_dataset.csv`
   - `olist_order_reviews_dataset.csv`
   - `olist_orders_dataset.csv`
   - `olist_products_dataset.csv`
   - `olist_sellers_dataset.csv`
   - `product_category_name_translation.csv`

2. **Start PostgreSQL 16** (automatically runs `sql/init/01_schemas.sql` to create `raw`, `staging`, `warehouse`, and `dq`):
   ```bash
   docker compose up -d
   docker compose ps
   python scripts/test_connection.py
   ```
   Confirm container `ecom_postgres` reports status `healthy` and `test_connection.py` prints the PostgreSQL version.

3. **Run the Complete ETL Pipeline:**
   ```bash
   # Ingest raw CSVs, profile raw data, build staging + warehouse + inventory + DQ + queries
   python scripts/run_pipeline.py --ingest

   # Optional: also generate 380,000 synthetic demo orders (2018–2026) and rebuild layers
   python scripts/run_pipeline.py --replace-demo 380000 --batch-size 5000
   ```

4. **Resetting Local Database (Destructive):**
   ```bash
   docker compose down -v
   ```

### Option B: Connect to Existing Hosted Azure PostgreSQL

If you have credentials for the pre-loaded Azure Database for PostgreSQL (`ecom`), configure `.env` with the Azure host, credentials, and `PGSSLMODE=require`. Skip Docker and skip the pipeline—do **not** run DDL/rebuild scripts against the hosted database unless intentionally modifying production data.

---

## Step 4: Launch the Web Application Locally

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

### Local Verification Checklist

| Endpoint | Expected Result |
|---|---|
| `http://127.0.0.1:8000/api/health` | JSON with `"status": "ok"`, `"warehouse_ready": true`, `"raw_tables_uploaded_count": 9` |
| `http://127.0.0.1:8000/` | Landing page loads with populated live headline KPIs |
| `http://127.0.0.1:8000/dashboard` | Executive Dashboard renders charts, tables, year filter, and scope toggle |
| `http://127.0.0.1:8000/chat` | AI Assistant answers `"Top 10 categories by revenue"` with live table |
| `http://127.0.0.1:8000/docs` | Swagger UI displays Analytics, Recommendations, Chat, and Health endpoints |

---

## Common Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| `SSL connection has been closed unexpectedly` / `server does not support SSL` locally | `api/db.py` and `ingestion/ingest_olist.py` default `PGSSLMODE` to `require`, while local Docker Postgres does not enable SSL by default | Add `PGSSLMODE=prefer` (or `disable`) to your local `.env` |
| `Connection refused` on port `5432` | Docker container not running or port conflict with local Postgres | Run `docker compose up -d` and check `docker compose ps` |
| `Missing files in data/raw` | Olist CSVs not downloaded or placed in wrong subfolder | Extract all 9 Kaggle CSV files directly into `data/raw/` |
| `FileNotFoundError` running `simulate_db_orders.py` manually | The repository file name has a space before `.py` (`scripts/simulate_db_orders .py`) | Invoke via `scripts/run_pipeline.py --replace-demo ...` or quote the path: `python "scripts/simulate_db_orders .py" --orders 380000 --replace` |
| `warehouse/generate_inventory.py` or `warehouse/run_dq_checks.py` connects to `127.0.0.1` | Those two scripts default `host="127.0.0.1"` for local pipeline runs | Run them against the local Docker database or update `get_db_config()` to read `env.get("POSTGRES_HOST", "127.0.0.1")` before targeting a remote host |
