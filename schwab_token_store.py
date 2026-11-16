"""Shared PostgreSQL OAuth storage. No token cache and no filesystem fallback."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
import threading

import psycopg2


class TokenStorageError(ValueError):
    """Sanitized storage error; never include a DSN, SQL parameters or tokens."""


_initialized = set()
_schema_lock = threading.Lock()
_COLUMNS = """access_token, refresh_token, access_expires_at,
              refresh_expires_at, authorized_at, reauthorize, retry_after"""


def _stamp(value):
    return value.timestamp() if value else 0


def _date(value):
    return datetime.fromtimestamp(float(value), timezone.utc) if value else None


def _ensure_schema(connection, identity):
    if identity in _initialized:
        return
    with _schema_lock:
        if identity in _initialized:
            return
        # Serialize first-run DDL across web replicas and background workers.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (716491825309,))
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.schwab_oauth_tokens (
                    app_id TEXT PRIMARY KEY,
                    access_token TEXT,
                    refresh_token TEXT,
                    access_expires_at TIMESTAMPTZ,
                    refresh_expires_at TIMESTAMPTZ,
                    authorized_at TIMESTAMPTZ,
                    reauthorize BOOLEAN NOT NULL DEFAULT FALSE,
                    retry_after TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
        connection.commit()
        _initialized.add(identity)


@contextmanager
def _connection():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise TokenStorageError("Schwab token storage requires DATABASE_URL on this server.")
    connection = None
    try:
        connection = psycopg2.connect(
            url, connect_timeout=5,
            options="-c statement_timeout=15000 -c lock_timeout=12000")
        identity = hashlib.sha256(url.encode()).digest()
        _ensure_schema(connection, identity)
        with connection:
            yield connection
    except psycopg2.Error:
        raise TokenStorageError(
            "Schwab token database is temporarily unavailable; authorization has not been cleared."
        ) from None
    finally:
        if connection is not None:
            connection.close()


class Record:
    def __init__(self, connection, app_id):
        self.connection, self.app_id = connection, app_id

    def read(self):
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {_COLUMNS} FROM public.schwab_oauth_tokens WHERE app_id = %s",
                (self.app_id,))
            row = cursor.fetchone()
        if not row:
            return {}
        return {
            "access_token": row[0], "refresh_token": row[1],
            "expires_at": _stamp(row[2]), "refresh_expires_at": _stamp(row[3]),
            "authorized_at": row[4].isoformat() if row[4] else None,
            "reauthorize": row[5], "retry_after": _stamp(row[6]),
        }

    def write(self, value):
        authorized = value.get("authorized_at")
        if isinstance(authorized, str):
            authorized = datetime.fromisoformat(authorized)
        with self.connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO public.schwab_oauth_tokens
                    (app_id, access_token, refresh_token, access_expires_at,
                     refresh_expires_at, authorized_at, reauthorize, retry_after)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (app_id) DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    access_expires_at = EXCLUDED.access_expires_at,
                    refresh_expires_at = EXCLUDED.refresh_expires_at,
                    authorized_at = EXCLUDED.authorized_at,
                    reauthorize = EXCLUDED.reauthorize,
                    retry_after = EXCLUDED.retry_after,
                    updated_at = CURRENT_TIMESTAMP
            """, (self.app_id, value.get("access_token"), value.get("refresh_token"),
                  _date(value.get("expires_at")), _date(value.get("refresh_expires_at")),
                  authorized, bool(value.get("reauthorize")), _date(value.get("retry_after"))))


def read(app_id):
    with _connection() as connection:
        return Record(connection, app_id).read()


@contextmanager
def locked(app_id):
    with _connection() as connection:
        with connection.cursor() as cursor:
            # Transaction-scoped locks work with pooled PostgreSQL connections.
            # Include the empty-row case, where SELECT FOR UPDATE cannot lock.
            key = int.from_bytes(hashlib.sha256(app_id.encode()).digest()[:8], "big", signed=True)
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        yield Record(connection, app_id)
