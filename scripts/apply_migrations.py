"""Apply versioned SQL migrations to the development database."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import get_conn


def main() -> None:
    connection = get_conn()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS app_schema_migrations (
                    migration_name TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            for path in sorted((ROOT / "migrations").glob("*.sql")):
                cursor.execute(
                    "SELECT 1 FROM app_schema_migrations WHERE migration_name = %s",
                    (path.name,),
                )
                if cursor.fetchone():
                    continue
                cursor.execute(path.read_text())
                cursor.execute(
                    "INSERT INTO app_schema_migrations (migration_name) VALUES (%s)",
                    (path.name,),
                )
                print(f"Applied {path.name}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()