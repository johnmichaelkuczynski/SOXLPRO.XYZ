import hashlib
import hmac
import os
import uuid

import psycopg2
import streamlit as st


def normalize_visitor_id(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def anonymous_visitor_id(headers, secret=None):
    """Create a stable one-way browser/network estimate without storing raw data."""
    normalized_headers = {
        str(key).lower(): str(value) for key, value in dict(headers or {}).items()
    }
    forwarded = normalized_headers.get("x-forwarded-for", "")
    network = (
        normalized_headers.get("cf-connecting-ip")
        or (forwarded.split(",")[0].strip() if forwarded else "")
        or normalized_headers.get("x-real-ip")
        or "unknown-network"
    )
    browser = normalized_headers.get("user-agent", "unknown-browser")
    language = normalized_headers.get("accept-language", "")
    raw = f"{network}|{browser}|{language}".encode("utf-8")
    signing_key = (
        secret or os.environ.get("SESSION_SECRET") or "soxlpro-counter-v1"
    ).encode("utf-8")
    digest = hmac.new(signing_key, raw, hashlib.sha256).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))


def _connect():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Database connection is unavailable")
    return psycopg2.connect(database_url, connect_timeout=4)


def get_visit_counts():
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT total_visits, unique_visitors
                FROM site_visit_stats
                WHERE counter_key = 'public'
                """
            )
            row = cursor.fetchone()
    return (int(row[0]), int(row[1])) if row else (0, 0)


def record_visit(visitor_id, session_id):
    visitor_id = normalize_visitor_id(visitor_id)
    session_id = normalize_visitor_id(session_id)
    if visitor_id is None or session_id is None:
        raise ValueError("Invalid anonymous visit identifier")
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO site_visitors (visitor_id)
                VALUES (%s)
                ON CONFLICT (visitor_id) DO NOTHING
                RETURNING visitor_id
                """,
                (visitor_id,),
            )
            is_unique_visitor = cursor.fetchone() is not None
            if not is_unique_visitor:
                cursor.execute(
                    """
                    UPDATE site_visitors
                    SET last_seen = NOW(), visit_count = visit_count + 1
                    WHERE visitor_id = %s
                    """,
                    (visitor_id,),
                )
            cursor.execute(
                """
                INSERT INTO site_visit_sessions (session_id, visitor_id)
                VALUES (%s, %s)
                ON CONFLICT (session_id) DO NOTHING
                RETURNING session_id
                """,
                (session_id, visitor_id),
            )
            is_new_visit = cursor.fetchone() is not None
            cursor.execute(
                """
                INSERT INTO site_visit_stats
                    (counter_key, total_visits, unique_visitors, updated_at)
                VALUES ('public', %s, %s, NOW())
                ON CONFLICT (counter_key) DO UPDATE
                SET total_visits = site_visit_stats.total_visits
                        + EXCLUDED.total_visits,
                    unique_visitors = site_visit_stats.unique_visitors
                        + EXCLUDED.unique_visitors,
                    updated_at = NOW()
                RETURNING total_visits, unique_visitors
                """,
                (1 if is_new_visit else 0, 1 if is_unique_visitor else 0),
            )
            row = cursor.fetchone()
    return int(row[0]), int(row[1])


def render_visitor_counter():
    try:
        headers = st.context.headers
    except Exception:
        headers = {}
    visitor_id = anonymous_visitor_id(headers)
    if "_public_visit_session_id" not in st.session_state:
        st.session_state._public_visit_session_id = str(uuid.uuid4())
    session_id = st.session_state._public_visit_session_id
    counted = st.session_state.get("_visitor_counted_session")
    counts = st.session_state.get("_public_visit_counts")
    try:
        if visitor_id and session_id and counted != session_id:
            counts = record_visit(visitor_id, session_id)
            st.session_state._visitor_counted_session = session_id
            st.session_state._public_visit_counts = counts
        elif counts is None:
            counts = get_visit_counts()
            st.session_state._public_visit_counts = counts
    except Exception:
        counts = None

    if counts is not None:
        total, unique = counts
        st.markdown(
            f"""
            <div style="text-align:right;color:#64748b;font-size:.76rem;
                        margin:-4px 2px 2px 0;letter-spacing:.01em;">
              <span title="Anonymous visit sessions; Streamlit reruns are not counted again.">
              Total visits: <strong>{total:,}</strong></span>
              <span style="color:#cbd5e1;padding:0 .38rem;">•</span>
              <span title="Anonymous browser estimate; no names or contact details are stored.">
              Unique visitors: <strong>{unique:,}</strong></span>
            </div>
            """,
            unsafe_allow_html=True,
        )