"""Portable database selection, without opening connections or exposing secrets."""
import os


def database_url(environ=None):
    env = os.environ if environ is None else environ
    return (env.get("NEON_DATABASE_URL") or "").strip() or (
        env.get("DATABASE_URL") or ""
    ).strip()
