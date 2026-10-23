import re
import sys
from pathlib import Path

try:
    import psycopg2 as pg
except ImportError:
    import psycopg as pg

# Project root = parent of the "scripts" folder (works from any working directory)
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
SQL_FILE = BASE_DIR / "sql" / "warehouse" / "05_analytical_queries.sql"
if len(sys.argv) > 1:
    SQL_FILE = Path(sys.argv[1])


def load_env(path):
    """Minimal .env reader (KEY=VALUE lines, # comments, optional quotes)."""
    env = {}
    if not path.exists():
        sys.exit(f"ERROR: .env not found at {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def get_db_config():
    env = load_env(ENV_FILE)
    missing = [k for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB") if k not in env]
    if missing:
        sys.exit(f"ERROR: missing in .env: {', '.join(missing)}")
    return dict(
        host="127.0.0.1",  # avoids the IPv6 (::1) lookup of "localhost"
        port=int(env.get("POSTGRES_PORT", 5432)),
        dbname=env["POSTGRES_DB"],
        user=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
    )


def load_queries(path):
    """Split the .sql file into (title, query) pairs using the '-- N. Title' headers."""
    queries, title, buf = [], None, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^--\s*(\d+)\.\s*(.+)", line)
            if m:
                if title and buf:
                    queries.append((title, "\n".join(buf).strip().rstrip(";")))
                title, buf = f"{m.group(1)}. {m.group(2).strip()}", []
            elif line.lstrip().startswith("--"):
                continue
            else:
                buf.append(line.rstrip("\n"))
    if title and buf:
        queries.append((title, "\n".join(buf).strip().rstrip(";")))
    return queries


def print_table(cols, rows, max_rows=30):
    shown = rows[:max_rows]
    widths = [
        max(len(str(c)), *(len(str(r[i])) for r in shown)) if shown else len(str(c))
        for i, c in enumerate(cols)
    ]
    print(" | ".join(str(c).ljust(w) for c, w in zip(cols, widths)))
    print("-+-".join("-" * w for w in widths))
    for r in shown:
        print(" | ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    if len(rows) > max_rows:
        print(f"... ({len(rows) - max_rows} more rows)")


def main():
    queries = load_queries(SQL_FILE)
    print(f"Loaded {len(queries)} queries from {SQL_FILE}\n")
    conn = pg.connect(**get_db_config())
    try:
        for title, sql in queries:
            print("=" * 70)
            print(title)
            print("=" * 70)
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cols = [d[0] for d in cur.description]
                    print_table(cols, cur.fetchall())
            except Exception as e:
                conn.rollback()
                print(f"ERROR: {e}")
            print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
