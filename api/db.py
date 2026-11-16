"""
Database connection pool & SQL query loader for Azure PostgreSQL.
"""
import os
import re
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYTICAL_SQL_PATH = PROJECT_ROOT / "sql" / "warehouse" / "05_analytical_queries.sql"

_pool: Optional[pool.ThreadedConnectionPool] = None


def get_pool() -> pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            host=os.getenv("POSTGRES_HOST") or os.getenv("PGHOST", "localhost"),
            port=os.getenv("POSTGRES_PORT") or os.getenv("PGPORT", "5432"),
            dbname=os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE", "ecom"),
            user=os.getenv("POSTGRES_USER") or os.getenv("PGUSER", "ecom"),
            password=os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD", "ecom_pass"),
            sslmode=os.getenv("PGSSLMODE", "require"),
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
        )
    return _pool


@contextmanager
def get_cursor():
    conn_pool = get_pool()
    conn = conn_pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn_pool.putconn(conn)


def _serialize_value(val: Any) -> Any:
    if isinstance(val, Decimal):
        return float(val)
    return val


def fetch_all(sql_query: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(sql_query, params)
        rows = cur.fetchall()
        return [{k: _serialize_value(v) for k, v in dict(r).items()} for r in rows]


def fetch_one(sql_query: str, params: Optional[Tuple[Any, ...]] = None) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(sql_query, params)
        row = cur.fetchone()
        return {k: _serialize_value(v) for k, v in dict(row).items()} if row else None


def load_analytical_queries() -> Dict[int, Dict[str, Any]]:
    """
    Parses sql/warehouse/05_analytical_queries.sql into a dictionary keyed by query_id (1..21).
    """
    if not ANALYTICAL_SQL_PATH.exists():
        return {}

    content = ANALYTICAL_SQL_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r"--\s*(\d+)\.\s*([^\n]+)\n(.*?)(?=(?:\n--\s*\d+\.\s*)|\Z)",
        re.DOTALL,
    )

    queries: Dict[int, Dict[str, Any]] = {}
    for match in pattern.finditer(content):
        q_id = int(match.group(1))
        title = match.group(2).strip()
        raw_block = match.group(3)

        clean_lines = []
        for line in raw_block.splitlines():
            if line.strip().startswith("--"):
                continue
            clean_lines.append(line)
        sql_stmt = "\n".join(clean_lines).strip()

        if q_id <= 5:
            section = "reference_olist"
        elif q_id <= 17:
            section = "full_timeline"
        else:
            section = "inventory"

        queries[q_id] = {
            "query_id": q_id,
            "title": title,
            "section": section,
            "sql": sql_stmt,
        }
    return queries
