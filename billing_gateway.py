"""Public gateway for Streamlit plus a raw-body Stripe webhook endpoint."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from urllib.parse import urlparse

import stripe
from aiohttp import ClientSession, WSMsgType, web

from billing import process_stripe_webhook


STREAMLIT_URL = "http://127.0.0.1:8501"
HOP_HEADERS = {
    "connection",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


async def stripe_webhook(request: web.Request) -> web.Response:
    signature = request.headers.get("Stripe-Signature")
    if not signature:
        return web.json_response({"error": "Missing Stripe-Signature"}, status=400)
    try:
        event_id = await asyncio.to_thread(
            process_stripe_webhook, await request.read(), signature
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return web.json_response({"error": "Invalid webhook"}, status=400)
    except Exception:
        return web.json_response({"error": "Webhook processing failed"}, status=500)
    return web.json_response({"received": True, "event_id": event_id})


def _proxy_headers(headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_HEADERS
        and key.lower() != "host"
        and not key.lower().startswith("sec-websocket-")
        and key.lower() != "origin"
    }


async def websocket_proxy(request: web.Request) -> web.WebSocketResponse:
    origin = request.headers.get("Origin", "")
    parsed_origin = urlparse(origin)
    allowed_hosts = {"127.0.0.1:5000", "localhost:5000"}
    if os.environ.get("REPLIT_DEV_DOMAIN"):
        allowed_hosts.add(os.environ["REPLIT_DEV_DOMAIN"])
    if os.environ.get("REPLIT_DEPLOYMENT") == "1":
        allowed_hosts = {"soxlpro.xyz"}
    if (
        parsed_origin.scheme not in {"http", "https"}
        or parsed_origin.netloc not in allowed_hosts
    ):
        return web.Response(text="Forbidden WebSocket origin", status=403)

    protocols = [
        value.strip()
        for value in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
        if value.strip()
    ]
    try:
        upstream = await request.app["client"].ws_connect(
            f"{STREAMLIT_URL}{request.rel_url}",
            headers=_proxy_headers(request.headers),
            protocols=protocols,
            origin=STREAMLIT_URL,
            heartbeat=30,
            max_msg_size=16 * 1024 * 1024,
        )
    except Exception:
        return web.Response(text="Application WebSocket unavailable", status=503)
    downstream = web.WebSocketResponse(protocols=protocols, heartbeat=30)
    await downstream.prepare(request)

    async def client_to_streamlit():
        async for message in downstream:
            if message.type == WSMsgType.TEXT:
                await upstream.send_str(message.data)
            elif message.type == WSMsgType.BINARY:
                await upstream.send_bytes(message.data)
            elif message.type == WSMsgType.CLOSE:
                await upstream.close()

    async def streamlit_to_client():
        async for message in upstream:
            if message.type == WSMsgType.TEXT:
                await downstream.send_str(message.data)
            elif message.type == WSMsgType.BINARY:
                await downstream.send_bytes(message.data)
            elif message.type == WSMsgType.CLOSE:
                await downstream.close()

    await asyncio.gather(client_to_streamlit(), streamlit_to_client())
    return downstream


async def streamlit_proxy(request: web.Request) -> web.StreamResponse:
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await websocket_proxy(request)
    try:
        upstream = await request.app["client"].request(
            request.method,
            f"{STREAMLIT_URL}{request.rel_url}",
            headers=_proxy_headers(request.headers),
            data=await request.read(),
            allow_redirects=False,
        )
    except Exception:
        return web.Response(text="Application is starting. Please refresh.", status=503)
    body = await upstream.read()
    return web.Response(
        body=body,
        status=upstream.status,
        headers=_proxy_headers(upstream.headers),
    )


async def startup(app: web.Application) -> None:
    app["client"] = ClientSession(auto_decompress=False)
    app["streamlit"] = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app.py",
        "--server.port",
        "8501",
        "--server.address",
        "127.0.0.1",
        "--server.headless",
        "true",
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


async def cleanup(app: web.Application) -> None:
    await app["client"].close()
    process = app.get("streamlit")
    if process and process.returncode is None:
        process.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError:
            process.kill()


def create_app() -> web.Application:
    app = web.Application(client_max_size=16 * 1024 * 1024)
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    app.router.add_post("/api/stripe/webhook", stripe_webhook)
    app.router.add_route("*", "/{path:.*}", streamlit_proxy)
    return app


if __name__ == "__main__":
    web.run_app(
        create_app(),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        access_log=None,
    )