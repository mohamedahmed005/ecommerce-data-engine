"""Run the whole pipeline with one command.

Default steps (in order), from the project root:
    python scripts/run_pipeline.py

    staging    -> staging/run_staging.py            (raw -> staging)
    ddl        -> warehouse/run_ddl.py              (create the warehouse tables)
    etl        -> warehouse/run_etl.py              (staging -> warehouse)
    inventory  -> warehouse/generate_inventory.py   (synthetic stock table)
    dq         -> warehouse/run_dq_checks.py        (data quality checks + report)
    queries    -> scripts/run_queries.py            (analytical queries)

Options:
    --docker          start the database with "docker compose up -d" first (and wait for it)
    --ingest          also run the raw loader and the profiling first
                      (ingestion/ingest_olist.py, profiling/profile_raw.py)
    --demo N          add N synthetic demo orders (keeps existing data)
    --replace-demo N  replace existing synthetic demo orders with N new ones
    --remove-demo     remove the synthetic demo orders first (original Olist data only)
    --batch-size N    orders per DB round-trip when generating demo data (default: 5000)
    --from STEP       start at STEP (staging, ddl, etl, inventory, dq, queries)
    --only STEP       run a single step
    --keep-going      do not stop when a step fails
    --quiet           hide the output of steps that succeed
    --dry-run         only print what would run
    --list            show the available steps

Examples:
    python scripts/run_pipeline.py --docker
    python scripts/run_pipeline.py --demo 360000 --batch-size 5000
    python scripts/run_pipeline.py --replace-demo 360000
    python scripts/run_pipeline.py --from etl
    python scripts/run_pipeline.py --only dq
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
PY = sys.executable

CORE_STEPS = [
    ("staging", "staging/run_staging.py", []),
    ("ddl", "warehouse/run_ddl.py", []),
    ("etl", "warehouse/run_etl.py", []),
    ("inventory", "warehouse/generate_inventory.py", []),
    ("dq", "warehouse/run_dq_checks.py", []),
    ("queries", "scripts/run_queries.py", []),
]
STEP_NAMES = [name for name, _, _ in CORE_STEPS]


def load_env(path):
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


def db_is_up():
    """True if PostgreSQL accepts a connection with the settings of .env."""
    try:
        import psycopg2
    except ImportError:
        return True
    env = load_env(ENV_FILE)
    try:
        conn = psycopg2.connect(
            host=env.get("POSTGRES_HOST", "127.0.0.1"),
            port=int(env.get("POSTGRES_PORT", 5432)),
            user=env["POSTGRES_USER"],
            password=env["POSTGRES_PASSWORD"],
            dbname=env["POSTGRES_DB"],
            connect_timeout=5,
        )
        conn.close()
        return True
    except Exception:
        return False


def start_docker(timeout=90):
    print("Starting the database: docker compose up -d")
    result = subprocess.run(["docker", "compose", "up", "-d"], cwd=ROOT)
    if result.returncode != 0:
        sys.exit("ERROR: 'docker compose up -d' failed. Is Docker Desktop running?")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if db_is_up():
            print("Database is ready.\n")
            return
        time.sleep(3)
    sys.exit(f"ERROR: the database did not become ready within {timeout} seconds.")


def build_steps(args):
    steps = []
    if args.ingest:
        steps.append(("ingest", "ingestion/ingest_olist.py", []))
        steps.append(("profile", "profiling/profile_raw.py", []))
    if args.demo is not None:
        steps.append(
            ("demo", "scripts/simulate_db_orders .py",
             ["--orders", str(args.demo),
              "--batch-size", str(args.batch_size)])
        )
    elif args.replace_demo is not None:
        steps.append(
            ("demo", "scripts/simulate_db_orders .py",
             ["--orders", str(args.replace_demo),
              "--replace",
              "--batch-size", str(args.batch_size)],)
        )
    elif args.remove_demo:
        steps.append(("demo", "scripts/simulate_db_orders .py", ["--remove"]))

    core = list(CORE_STEPS)
    if args.only:
        core = [s for s in core if s[0] == args.only]
        steps = [s for s in steps if s[0] == args.only]
    elif args.from_step:
        start = STEP_NAMES.index(args.from_step)
        core = core[start:]
        steps = []
    return steps + core


def run_step(name, script, extra, quiet):
    cmd = [PY, script] + extra
    start = time.time()
    if quiet:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
    else:
        result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode, time.time() - start


def main():
    parser = argparse.ArgumentParser(
        description="Run the whole pipeline with one command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Options:")[0],
    )
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--ingest", action="store_true")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--demo", type=int, metavar="N")
    group.add_argument("--replace-demo", type=int, metavar="N")
    group.add_argument("--remove-demo", action="store_true")
    parser.add_argument(
        "--batch-size", type=int, default=5000, metavar="N",
        help="orders per DB round-trip when generating demo data (default: 5000)",
    )
    parser.add_argument("--from", dest="from_step", choices=STEP_NAMES)
    parser.add_argument("--only", choices=STEP_NAMES + ["ingest", "profile", "demo"])
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        print(
            "Optional steps: ingest, profile (--ingest), "
            "demo (--demo N / --replace-demo N / --remove-demo)"
        )
        print("Core steps:", ", ".join(STEP_NAMES))
        return
    if args.from_step and args.only:
        sys.exit("ERROR: use either --from or --only, not both.")
    if args.demo is not None and args.demo <= 0:
        sys.exit("ERROR: --demo N must be a positive integer.")
    if args.replace_demo is not None and args.replace_demo <= 0:
        sys.exit("ERROR: --replace-demo N must be a positive integer.")

    steps = build_steps(args)
    if not steps:
        sys.exit("ERROR: nothing to run (check --only / --from).")

    missing = [s for _, s, _ in steps if not (ROOT / s).exists()]
    if missing:
        sys.exit("ERROR: missing files:\n  " + "\n  ".join(missing))

    if args.dry_run:
        print("Would run (from", ROOT, "):")
        for name, script, extra in steps:
            print(f"  [{name}] python {script} {' '.join(extra)}".rstrip())
        return

    if args.docker:
        start_docker()
    elif not db_is_up():
        sys.exit(
            "ERROR: cannot connect to the database. Start it with "
            "'docker compose up -d' (or run this script with --docker)."
        )

    results = []
    total_start = time.time()
    for i, (name, script, extra) in enumerate(steps, 1):
        print("=" * 70)
        print(f"STEP {i}/{len(steps)}: {name}   ({script} {' '.join(extra)})".rstrip())
        print("=" * 70, flush=True)
        code, seconds = run_step(name, script, extra, args.quiet)
        results.append((name, code, seconds))
        print(
            f"-> {name}: {'OK' if code == 0 else f'FAILED (exit code {code})'} "
            f"in {seconds:.1f}s\n",
            flush=True,
        )
        if code != 0 and not args.keep_going:
            break

    print("=" * 70)
    print("PIPELINE SUMMARY")
    print("=" * 70)
    for name, code, seconds in results:
        print(f"  {'OK    ' if code == 0 else 'FAILED'}  {name:<10} {seconds:6.1f}s")
    skipped = [s[0] for s in steps[len(results):]]
    if skipped:
        print("  NOT RUN:", ", ".join(skipped))
    failed = [name for name, code, _ in results if code != 0]
    print(f"\nTotal time: {time.time() - total_start:.1f}s")
    if failed:
        print("Failed steps:", ", ".join(failed))
        sys.exit(1)
    print("All steps finished successfully.")


if __name__ == "__main__":
    main()