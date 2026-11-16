"""Explicit real-Postgres check using only an isolated fake connection record.

Run: python -m tests.schwab_postgres_check (or with PYTHONPATH=.).
Does not call Schwab, read real tokens, or change existing connection rows.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import subprocess
import sys
import threading
import time
import uuid
from unittest.mock import patch

import schwab_market_data as provider
import schwab_token_store as store


def main():
    client = "isolated-storage-check-" + uuid.uuid4().hex
    with patch.dict(provider.os.environ, {
            "SCHWAB_CLIENT_ID": client, "SCHWAB_CLIENT_SECRET": "test-only-not-a-real-secret"}):
        app = provider._fingerprint()
        deadline = time.time() + 6 * 86400
        try:
            with store.locked(app) as record:
                record.write({
                    "access_token": "test-only-old-access", "refresh_token": "test-only-refresh",
                    "expires_at": time.time() + 90, "refresh_expires_at": deadline,
                    "authorized_at": datetime.now(timezone.utc).isoformat()})
            count = 0
            count_lock = threading.Lock()

            def fake_refresh(form):
                nonlocal count
                assert form["refresh_token"] == "test-only-refresh"
                with count_lock:
                    count += 1
                time.sleep(.1)
                return {"access_token": "test-only-new-access",
                        "refresh_token": "test-only-rotated", "expires_at": time.time() + 1800}

            with patch.object(provider, "_token_request", side_effect=fake_refresh):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    values = list(pool.map(lambda _: provider.access_token(), range(4)))
            assert values == ["test-only-new-access"] * 4
            assert count == 1, "Concurrent workers refreshed more than once"
            assert abs(store.read(app)["refresh_expires_at"] - deadline) < .00001
            # A separate Python process has no access to parent-process state.
            subprocess.run([sys.executable, "-c",
                "import sys,time; from schwab_token_store import read; "
                "row=read(sys.argv[1]); "
                "assert row['access_token']=='test-only-new-access'; "
                "assert row['refresh_token']=='test-only-rotated'; "
                "assert row['refresh_expires_at']>time.time()+5*86400", app],
                check=True, capture_output=True)
            print("Postgres passed: cross-process persistence, four concurrent workers, one refresh and retained expiry.")
        finally:
            with store.locked(app) as record:
                with record.connection.cursor() as cursor:
                    cursor.execute("DELETE FROM public.schwab_oauth_tokens WHERE app_id = %s", (app,))


if __name__ == "__main__":
    main()
