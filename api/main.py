from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api.db import fetch_all, fetch_one
from api.routers import analytics, chat, recommendations

app = FastAPI(
    title="E-Commerce Data Engine API",
    description="Unified Analytics, Inventory-Aware Recommendations, and AI Chatbot over Azure PostgreSQL",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analytics.router)
app.include_router(recommendations.router)
app.include_router(chat.router)

BASE_DIR = Path(__file__).resolve().parent.parent


@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/health")
def health_check():
    check = fetch_one("""
        SELECT
            current_database() AS db,
            to_regclass('warehouse.fact_sales') IS NOT NULL AS warehouse_ready,
            to_regclass('warehouse.fact_inventory') IS NOT NULL AS inventory_ready
    """)
    raw_tables = fetch_all("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'raw'
        ORDER BY table_name
    """)
    return {
        "status": "ok",
        "database": check["db"] if check else "unknown",
        "warehouse_ready": check["warehouse_ready"] if check else False,
        "raw_tables_uploaded_count": len(raw_tables),
        "raw_tables": [r["table_name"] for r in raw_tables],
    }