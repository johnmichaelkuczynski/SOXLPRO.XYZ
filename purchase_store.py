"""Durable checkout attempts and purchases backed by the existing Neon DB.

This module deliberately contains no provider code.  Stripe objects are kept in
the application-owned table so a successful payment can be found on a later
login, even when the customer never returns from Checkout.
"""

from __future__ import annotations

import uuid
from threading import Lock
from typing import Any

import psycopg2.extras

import db


class PurchaseStoreError(RuntimeError):
    """A database failure while reading or writing billing state."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS purchase_checkouts (
    id                   BIGSERIAL PRIMARY KEY,
    attempt_id           TEXT NOT NULL UNIQUE,
    user_identity_hash   TEXT NOT NULL,
    price_id             TEXT NOT NULL,
    expected_amount      INTEGER NOT NULL,
    expected_currency    TEXT NOT NULL,
    stripe_session_id    TEXT UNIQUE,
    checkout_url         TEXT,
    status               TEXT NOT NULL DEFAULT 'pending',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS purchase_checkouts_user_price_idx
    ON purchase_checkouts (user_identity_hash, price_id, created_at DESC);
CREATE INDEX IF NOT EXISTS purchase_checkouts_session_idx
    ON purchase_checkouts (stripe_session_id);
"""

_COLUMNS = (
    "id, attempt_id, user_identity_hash, price_id, expected_amount, "
    "expected_currency, stripe_session_id, checkout_url, status, "
    "created_at, updated_at, paid_at"
)
_initialized = False
_init_lock = Lock()


def _record(row: Any) -> dict | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    # This fallback is useful with lightweight test cursors and ordinary
    # psycopg2 cursors.  Production uses RealDictCursor below.
    if hasattr(row, "_asdict"):
        return dict(row._asdict())
    return dict(row)


def _cursor(conn):
    try:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    except TypeError:
        return conn.cursor()


def initialize_store() -> None:
    """Create the app-owned checkout table if needed."""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        conn = db.get_conn()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(_SCHEMA)
            _initialized = True
        except Exception as exc:
            raise PurchaseStoreError(
                "The purchase database is temporarily unavailable."
            ) from exc
        finally:
            conn.close()


def reserve_checkout(
    user_identity_hash: str,
    price_id: str,
    expected_amount: int,
    expected_currency: str,
) -> dict:
    """Return an existing usable attempt or atomically create a new one.

    The row is inserted before Stripe Checkout is requested.  Its attempt ID
    is also the Stripe idempotency key, so retries after a network failure do
    not create a second session or a second payment.
    """
    initialize_store()
    conn = db.get_conn()
    try:
        with conn, _cursor(conn) as cur:
            # A SELECT ... FOR UPDATE cannot lock a row that does not yet
            # exist.  Serialize the first insert for this identity/price pair
            # as well, so concurrent Buy clicks cannot create two attempts.
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{user_identity_hash}:{price_id}",),
            )
            cur.execute(
                f"SELECT {_COLUMNS} FROM purchase_checkouts "
                "WHERE user_identity_hash = %s AND price_id = %s "
                "AND status IN ('pending', 'open', 'paid', 'review') "
                "ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
                (user_identity_hash, price_id),
            )
            row = _record(cur.fetchone())
            if row is not None:
                return row
            attempt_id = "soxlpro-" + uuid.uuid4().hex
            cur.execute(
                "INSERT INTO purchase_checkouts "
                "(attempt_id, user_identity_hash, price_id, expected_amount, "
                "expected_currency, status) VALUES (%s, %s, %s, %s, %s, "
                "'pending') RETURNING " + _COLUMNS,
                (
                    attempt_id,
                    user_identity_hash,
                    price_id,
                    int(expected_amount),
                    str(expected_currency).lower(),
                ),
            )
            created = _record(cur.fetchone())
            if created is None:
                raise PurchaseStoreError("The purchase attempt was not created.")
            return created
    except PurchaseStoreError:
        raise
    except Exception as exc:
        raise PurchaseStoreError(
            "The purchase database is temporarily unavailable."
        ) from exc
    finally:
        conn.close()


def attach_session(attempt_id: str, session_id: str, checkout_url: str) -> dict:
    """Associate a Stripe session with the already durable attempt."""
    initialize_store()
    conn = db.get_conn()
    try:
        with conn, _cursor(conn) as cur:
            cur.execute(
                "UPDATE purchase_checkouts SET stripe_session_id = %s, "
                "checkout_url = %s, status = 'open', updated_at = now() "
                "WHERE attempt_id = %s AND status IN ('pending', 'open')",
                (session_id, checkout_url, attempt_id),
            )
            if cur.rowcount == 0:
                cur.execute(
                    f"SELECT {_COLUMNS} FROM purchase_checkouts "
                    "WHERE attempt_id = %s FOR UPDATE",
                    (attempt_id,),
                )
            else:
                cur.execute(
                    f"SELECT {_COLUMNS} FROM purchase_checkouts "
                    "WHERE attempt_id = %s",
                    (attempt_id,),
                )
            row = _record(cur.fetchone())
            if row is None:
                raise PurchaseStoreError("The purchase attempt no longer exists.")
            return row
    except PurchaseStoreError:
        raise
    except Exception as exc:
        raise PurchaseStoreError(
            "The purchase database is temporarily unavailable."
        ) from exc
    finally:
        conn.close()


def find_checkout(user_identity_hash: str, session_id: str) -> dict | None:
    """Find a session only when it belongs to this hashed Google identity."""
    initialize_store()
    conn = db.get_conn()
    try:
        with conn, _cursor(conn) as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM purchase_checkouts "
                "WHERE user_identity_hash = %s AND stripe_session_id = %s",
                (user_identity_hash, session_id),
            )
            return _record(cur.fetchone())
    except Exception as exc:
        raise PurchaseStoreError(
            "The purchase database is temporarily unavailable."
        ) from exc
    finally:
        conn.close()


def list_checkouts(user_identity_hash: str, price_id: str) -> list[dict]:
    """List this user's attempts for the configured price, newest first."""
    initialize_store()
    conn = db.get_conn()
    try:
        with conn, _cursor(conn) as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM purchase_checkouts "
                "WHERE user_identity_hash = %s AND price_id = %s "
                "ORDER BY created_at DESC",
                (user_identity_hash, price_id),
            )
            return [_record(row) for row in cur.fetchall()]
    except Exception as exc:
        raise PurchaseStoreError(
            "The purchase database is temporarily unavailable."
        ) from exc
    finally:
        conn.close()


def mark_paid(user_identity_hash: str, session_id: str) -> dict:
    """Durably record a verified payment for this identity and session."""
    initialize_store()
    conn = db.get_conn()
    try:
        with conn, _cursor(conn) as cur:
            cur.execute(
                "UPDATE purchase_checkouts SET status = 'paid', "
                "paid_at = COALESCE(paid_at, now()), updated_at = now() "
                "WHERE user_identity_hash = %s AND stripe_session_id = %s "
                "AND status NOT IN ('cancelled', 'failed')",
                (user_identity_hash, session_id),
            )
            cur.execute(
                f"SELECT {_COLUMNS} FROM purchase_checkouts "
                "WHERE user_identity_hash = %s AND stripe_session_id = %s",
                (user_identity_hash, session_id),
            )
            row = _record(cur.fetchone())
            if row is None:
                raise PurchaseStoreError("The purchase attempt no longer exists.")
            return row
    except PurchaseStoreError:
        raise
    except Exception as exc:
        raise PurchaseStoreError(
            "The purchase database is temporarily unavailable."
        ) from exc
    finally:
        conn.close()


def mark_status(user_identity_hash: str, session_id: str, status: str) -> None:
    """Record a provider-confirmed non-paid state without granting access."""
    allowed = {"pending", "open", "cancelled", "failed", "revoked", "expired", "review"}
    if status not in allowed:
        raise ValueError("invalid purchase status")
    initialize_store()
    conn = db.get_conn()
    try:
        with conn, _cursor(conn) as cur:
            cur.execute(
                "UPDATE purchase_checkouts SET status = %s, updated_at = now() "
                "WHERE user_identity_hash = %s AND stripe_session_id = %s",
                (status, user_identity_hash, session_id),
            )
    except Exception as exc:
        raise PurchaseStoreError(
            "The purchase database is temporarily unavailable."
        ) from exc
    finally:
        conn.close()