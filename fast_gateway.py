"""Small async gateway preserving Streamlit HTTP, cookies and WebSockets."""
import asyncio
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import tornado.httpclient
import tornado.web
import tornado.websocket

BACKEND = "http://127.0.0.1:8501"
state = None
ready = False


def saved_page(value):
    if not value:
        content = "<h1>SOXL Analysis</h1><p>Saved market data is temporarily unavailable. Background-update health is shown below.</p>"
    else:
        snapshot = value["snapshot"]
        signal = value["signal"]
        quote = snapshot.get("current_price")
        content = (
            "<h1>SOXL Analysis</h1><section><h2>SOXL Market Snapshot</h2>"
            f"<h2>${quote:,.2f}</h2>" if isinstance(quote, (int, float)) else
            "<h1>SOXL Analysis</h1><section><h2>SOXL Market Snapshot</h2>"
        )
        content += "<p>" + html.escape(snapshot.get("price_context", "")) + "</p></section>"
        content += "<section>" + " · ".join(
            html.escape(str(label)) + ": " + (f"{value:+.1f}%" if isinstance(value, (float, int)) else "N/A")
            for label, value in snapshot.get("returns", {}).items()
        ) + "</section>"
        from signal_config import SIGNAL_DISPLAY_LABELS
        rating = SIGNAL_DISPLAY_LABELS.get(signal["composite"]["signal"], signal["composite"]["signal"])
        content += (
            "<h2>SOXL Daily Signal</h2><div class='cards'><section>"
            "<p>Long-term signal (6–12 months)</p><h2>" + html.escape(rating) +
            "</h2></section><section><p>Short-term signal (1 month)</p><h2>" +
            html.escape(signal["short_rating"]) + "</h2></section></div><p>Saved results computed at " +
            html.escape(value["computed_at"]) + ". Close through " +
            html.escape(signal["close_date"]) + ".</p>"
        )
    from market_health import diagnostics_html
    from market_state_store import read_health
    content += diagnostics_html(value, read_health())
    return ("<!doctype html><html><head><meta charset='utf-8'><title>SOXL Analysis</title>"
            "<style>body{background:#f0f4fa;color:#172033;font:16px system-ui;padding:5%;}"
            "section{background:white;border:1px solid #ddd;border-radius:14px;padding:24px;margin:12px 0}"
            ".cards{display:flex;gap:24px}.cards section{flex:1}</style></head><body>" + content +
            "<p>Interactive chart and controls are starting. Saved results remain available.</p>"
            "<script>setInterval(async()=>{try{const r=await fetch('/_gateway/ready');"
            "if(r.ok)location.reload()}catch(e){}},750)</script></body></html>")


class Gateway(tornado.web.RequestHandler):
    async def get(self, path=""):
        await self.forward()

    async def post(self, path=""):
        await self.forward()

    async def head(self, path=""):
        await self.forward()

    async def options(self, path=""):
        await self.forward()

    async def forward(self):
        if self.request.path == "/_gateway/ready":
            self.set_status(200 if ready else 503)
            self.finish("ready" if ready else "starting")
            return
        if self.request.path == "/_stcore/health" and not ready:
            self.finish("ok")
            return
        # Existing preview tabs request this while Streamlit restarts. An
        # immediate 503 can strand the browser's bootstrap/reconnect sequence.
        if self.request.path == "/_stcore/host-config" and not ready:
            for _ in range(450):
                if ready or self.request.connection.stream.closed():
                    break
                await asyncio.sleep(0.1)
            if self.request.connection.stream.closed():
                return
        if self.request.path == "/" and not ready:
            # Database access has a bounded budget; never wait for a provider.
            global state
            # Recheck on every fallback request, even when a snapshot is cached.
            # load_state owns the bounded read and records failures independently.
            from market_state_store import load_state
            state = await asyncio.to_thread(load_state) or state
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.set_header("Cache-Control", "no-store")
            from market_state_store import read_health
            await asyncio.to_thread(read_health, refresh=True)
            self.finish(saved_page(state))
            return
        headers = self.request.headers.copy()
        headers.pop("Connection", None)
        headers["X-Forwarded-Proto"] = self.request.headers.get("X-Forwarded-Proto", self.request.protocol)
        headers["X-Forwarded-Host"] = self.request.host
        try:
            result = await tornado.httpclient.AsyncHTTPClient().fetch(
                BACKEND + self.request.uri, method=self.request.method, headers=headers,
                body=self.request.body if self.request.method not in ("GET", "HEAD") else None,
                follow_redirects=False, raise_error=False, request_timeout=120)
            self.set_status(result.code)
            for key, value in result.headers.get_all():
                if key.lower() not in ("transfer-encoding", "connection", "content-length", "content-encoding"):
                    if key.lower() == "set-cookie":
                        self.add_header(key, value)
                    else:
                        self.set_header(key, value)
            if result.code in (204, 304) or self.request.method == "HEAD":
                self.finish()
            else:
                self.finish(result.body)
        except Exception as exc:
            print("Gateway upstream failure:", type(exc).__name__, flush=True)
            self.set_status(503)
            self.finish("Interactive service is starting. Please retry shortly.")


class Socket(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        from urllib.parse import urlparse
        return urlparse(origin).netloc == self.request.host

    def select_subprotocol(self, protocols):
        return "streamlit" if "streamlit" in protocols else None

    async def open(self, path):
        headers = self.request.headers.copy()
        for key in ("Upgrade", "Connection", "Sec-Websocket-Key", "Sec-Websocket-Version",
                    "Sec-Websocket-Protocol", "Sec-Websocket-Extensions"):
            headers.pop(key, None)
        request = tornado.httpclient.HTTPRequest(
            BACKEND.replace("http:", "ws:") + self.request.uri, headers=headers)
        self.pending = []
        try:
            self.upstream = await tornado.websocket.websocket_connect(
                request, subprotocols=self.request.headers.get("Sec-WebSocket-Protocol", "").split(", "),
                max_message_size=200 * 1024 * 1024)
            for message in self.pending:
                await self.upstream.write_message(message, binary=isinstance(message, bytes))
            asyncio.create_task(self.relay())
        except Exception:
            self.close(1011, "Backend unavailable")

    async def relay(self):
        while True:
            message = await self.upstream.read_message()
            if message is None:
                self.close()
                break
            await self.write_message(message, binary=isinstance(message, bytes))

    async def on_message(self, message):
        if hasattr(self, "upstream"):
            await self.upstream.write_message(message, binary=isinstance(message, bytes))
        else:
            self.pending.append(message)

    def on_close(self):
        if getattr(self, "upstream", None):
            self.upstream.close()


async def run(port):
    global ready, state
    from stripe_webhook import StripeWebhook
    application = tornado.web.Application([
        (r"/api/stripe/webhook", StripeWebhook),
        (r"/(_stcore/stream)", Socket), (r"/(.*)", Gateway)
    ], websocket_max_message_size=200 * 1024 * 1024)
    application.listen(port, address="0.0.0.0")
    print(f"SOXL public listener ready on {port}", flush=True)
    scripts = ["streamlit_backend.py", "stripe_webhook.py"]
    if os.environ.get("SOXL_DISABLE_WORKER") != "1":
        scripts += ["market_state_worker.py", "benchmark_quotes.py"]
    processes = [subprocess.Popen([sys.executable, script]) for script in scripts]
    try:
        while True:
            try:
                response = await tornado.httpclient.AsyncHTTPClient().fetch(BACKEND + "/_stcore/health")
                ready = response.code == 200
            except Exception:
                ready = False
            for idx, process in enumerate(processes):
                if process.poll() is not None:
                    script = scripts[idx]
                    processes[idx] = subprocess.Popen([sys.executable, script])
            await asyncio.sleep(1)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def serve(port=5000):
    import signal
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = loop.create_task(run(port))
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()
