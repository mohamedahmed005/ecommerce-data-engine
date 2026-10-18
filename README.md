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
├── staging/           # staging runner + validation
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
