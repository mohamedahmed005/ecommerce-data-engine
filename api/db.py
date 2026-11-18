import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Dict
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

load_dotenv()

_pool = None


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            dbname=os.getenv("POSTGRES_DB", "ecom"),
            user=os.getenv("POSTGRES_USER", "ecom_admin"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            sslmode=os.getenv("PGSSLMODE", "require"),
            connect_timeout=30,
        )
    return _pool


@contextmanager
def get_cursor():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        try:
            pool.putconn(conn, close=True)
        except Exception:
            pass
        raise
    else:
        pool.putconn(conn)


def fetch_all(query: str, params=None):
    with get_cursor() as cur:
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def fetch_one(query: str, params=None):
    with get_cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


def load_analytical_queries():
    root = Path(__file__).resolve().parent.parent
    candidates = [
        root / "sql" / "warehouse" / "05_analytical_queries.sql",
        root / "sql" / "warehouse" / "04_analytical_queries.sql",
    ]
    sql_path = next((path for path in candidates if path.is_file()), None)
    if sql_path is None:
        matches = sorted(root.rglob("*_analytical_queries.sql"))
        sql_path = matches[0] if matches else None
    if sql_path is None:
        return {}

    text = sql_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    matches = list(re.finditer(r"(?m)^\s*--\s*(\d+)\.\s*(.+?)\s*$", text))
    queries = {}
    for i, match in enumerate(matches):
        query_id = int(match.group(1))
        title = match.group(2).strip()
        start = match.end() + 1
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sql_body = "\n".join(
            line for line in text[start:end].splitlines()
            if not line.lstrip().startswith("--")
        ).strip().rstrip(";")
        if sql_body:
            queries[query_id] = {
                "query_id": query_id,
                "title": title,
                "sql": sql_body,
            }
    return queries
