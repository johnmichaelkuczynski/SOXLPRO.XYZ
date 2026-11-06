"""Initialize an external PostgreSQL database without changing existing records.

Run explicitly before deploying to a new database: python setup_database.py
"""
import db
from benchmark_quotes import SCHEMA as BENCHMARK_SCHEMA
from market_state_store import _SCHEMA as MARKET_SCHEMA
from stripe_webhook import SCHEMA as BILLING_SCHEMA

VISITOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS site_visitors (
    visitor_id UUID PRIMARY KEY,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    visit_count BIGINT NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS site_visit_sessions (
    session_id UUID PRIMARY KEY,
    visitor_id UUID NOT NULL REFERENCES site_visitors(visitor_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS site_visit_stats (
    counter_key TEXT PRIMARY KEY,
    total_visits BIGINT NOT NULL DEFAULT 0,
    unique_visitors BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
WORKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_worker_health (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    payload JSONB NOT NULL
);
"""


def initialize():
    connection = db.get_conn()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            for schema in (db._SCHEMA, MARKET_SCHEMA, WORKER_SCHEMA,
                           BENCHMARK_SCHEMA, BILLING_SCHEMA, VISITOR_SCHEMA):
                cursor.execute(schema)
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        initialize()
    except Exception as error:
        # Database exceptions may contain credentials; print the class only.
        print(f"Database setup failed: {type(error).__name__}")
        raise SystemExit(1) from None
    print("Database tables initialized. Existing records were preserved.")
