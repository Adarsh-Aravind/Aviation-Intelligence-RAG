"""Apply SQL migrations in order:  python -m app.db.migrate

Each file in backend/migrations/*.sql runs once; applied filenames are recorded in schema_migrations.
"""

import sys
from pathlib import Path

import psycopg

from app.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    with psycopg.connect(settings.database_url, autocommit=True, prepare_threshold=None) as conn:
        conn.execute(
            "create table if not exists schema_migrations "
            "(filename text primary key, applied_at timestamptz not null default now())"
        )
        conn.execute("alter table schema_migrations enable row level security")
        done = {r[0] for r in conn.execute("select filename from schema_migrations").fetchall()}
        for f in files:
            if f.name in done:
                print(f"  skip  {f.name}")
                continue
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("insert into schema_migrations (filename) values (%s)", (f.name,))
            print(f"  apply {f.name}")
    print("migrations up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
