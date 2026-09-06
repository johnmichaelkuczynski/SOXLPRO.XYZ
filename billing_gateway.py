"""Public gateway for Google OAuth, Streamlit, and live Stripe webhooks."""

from __future__ import annotations

import asyncio
import os
import secrets
import signal
import sys
import uuid
from time import time
from urllib.parse import urlencode, urlparse

import jwt
import stripe
from aiohttp import ClientSession, WSMsgType, web

from billing import process_stripe_webhook


STREAMLIT_URL = "http://127.0.0.1:8501"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
SESSION_COOKIE = "soxlpro_session"
STATE_COOKIE = "soxlpro_oauth_state"
ANONYMOUS_COOKIE = "soxlpro_visitor"
HOP_HEADERS = {
    "connection", "content-length", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade",
}


def google_oauth_configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_CLIENT_ID")
        and os.environ.get("GOOGLE_CLIENT_SECRET")
        and os.environ.get("SESSION_SECRET")
    )


def _session_secret() -> str:
    value = os.environ.get("SESSION_SECRET", "")
    if len(value) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
    return value


def _public_base_url() -> str:
    configured = os.environ.get("PUBLIC_APP_URL", "").strip().rstrip("/")
    if configured:
        parsed = urlparse(configured)
        if parsed.scheme == "https" and parsed.netloc:
            return configured
    if os.environ.get("REPLIT_DEPLOYMENT") == "1":
        return "https://soxlpro.xyz"
    return "https://soxlproxyz.replit.app"


def _encode(payload: dict, lifetime: int) -> str:
    now = int(time())
    return jwt.encode(
        {**payload, "iat": now, "exp": now + lifetime},
        _session_secret(),
        algorithm="HS256",
    )


def _decode(value: str | None, purpose: str) -> dict | None:
    if not value:
        return None
    try:
        return jwt.decode(
            value,
            _session_secret(),
            algorithms=["HS256"],
            audience=purpose,
        )
    except Exception:
        return None


def _secure_cookie(response: web.StreamResponse, name: str, value: str, max_age: int):
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/",
    )


def _safe_return_path(value: str | None) -> str:
    # SOXLPRO is a single-page app. Root-only returns eliminate redirect
    # normalization tricks involving encoded separators or backslashes.
    return "/"


async def google_login(request: web.Request) -> web.Response:
    if not google_oauth_configured():
        return web.Response(text="Google sign-in is unavailable.", status=503)
    nonce = secrets.token_urlsafe(24)
    subscribe = request.query.get("subscribe") == "1"
    state = _encode(
        {
            "aud": "google_oauth_state",
            "nonce": nonce,
            "return_to": _safe_return_path(request.query.get("return_to")),
            "subscribe": subscribe,
        },
        600,
    )
    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": f"{_public_base_url()}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
    }
    response = web.HTTPFound(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")
    _secure_cookie(response, STATE_COOKIE, state, 600)
    raise response


_google_jwks = jwt.PyJWKClient(GOOGLE_JWKS_URL, cache_keys=True, lifespan=300)


def _verify_google_id_token(id_token: str, expected_nonce: str) -> tuple[str, str]:
    key = _google_jwks.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        key.key,
        algorithms=["RS256"],
        audience=os.environ["GOOGLE_CLIENT_ID"],
        options={"verify_iss": False},
    )
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise ValueError("Invalid Google issuer")
    if (
        claims.get("nonce") != expected_nonce
        or not claims.get("sub")
        or not claims.get("email")
        or claims.get("email_verified") is not True
    ):
        raise ValueError("Invalid Google identity token")
    return f"google_{claims['sub']}", claims["email"]


async def google_callback(request: web.Request) -> web.Response:
    state_value = request.query.get("state")
    cookie_value = request.cookies.get(STATE_COOKIE)
    state = _decode(state_value, "google_oauth_state")
    cookie_state = _decode(cookie_value, "google_oauth_state")
    if (
        not google_oauth_configured()
        or not state
        or not cookie_state
        or state_value != cookie_value
        or request.query.get("error")
        or not request.query.get("code")
    ):
        raise web.HTTPFound("/?auth=failed")

    async with request.app["client"].post(
        GOOGLE_TOKEN_URL,
        data={
            "code": request.query["code"],
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": f"{_public_base_url()}/auth/google/callback",
            "grant_type": "authorization_code",
        },
    ) as token_response:
        token_data = await token_response.json()
    if token_response.status != 200 or not token_data.get("id_token"):
        raise web.HTTPFound("/?auth=failed")
    try:
        user_id, _verified_email = await asyncio.to_thread(
            _verify_google_id_token,
            token_data["id_token"],
            state["nonce"],
        )
    except Exception:
        raise web.HTTPFound("/?auth=failed")

    return_to = _safe_return_path(state.get("return_to"))
    separator = "&" if "?" in return_to else "?"
    destination = f"{return_to}{separator}auth=complete"
    if state.get("subscribe"):
        destination += "&subscribe=1"
    response = web.HTTPFound(destination)
    _secure_cookie(
        response,
        SESSION_COOKIE,
        _encode({"aud": "soxlpro_session", "sub": user_id}, 60 * 60 * 24 * 30),
        60 * 60 * 24 * 30,
    )
    response.del_cookie(STATE_COOKIE, path="/")
    raise response


async def google_logout(request: web.Request) -> web.Response:
    response = web.HTTPFound("/?auth=logged_out")
    response.del_cookie(SESSION_COOKIE, path="/")
    raise response


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
        key: value for key, value in headers.items()
        if key.lower() not in HOP_HEADERS
        and key.lower() != "host"
        and not key.lower().startswith("sec-websocket-")
        and key.lower() != "origin"
        and not key.lower().startswith("x-soxlpro-")
        and key.lower() not in {"x-forwarded-for", "cf-connecting-ip"}
    }


def _trusted_identity(request: web.Request) -> tuple[str | None, str, bool]:
    session = _decode(request.cookies.get(SESSION_COOKIE), "soxlpro_session")
    user_id = session.get("sub") if session else None
    visitor = _decode(request.cookies.get(ANONYMOUS_COOKIE), "anonymous_visitor")
    if visitor and visitor.get("sub"):
        return user_id, visitor["sub"], False
    return user_id, str(uuid.uuid4()), True


def _upstream_headers(request: web.Request, user_id: str | None, visitor_id: str):
    headers = _proxy_headers(request.headers)
    headers["X-Soxlpro-Anonymous-Id"] = visitor_id
    if user_id:
        headers["X-Soxlpro-User-Id"] = user_id
    return headers


def _valid_websocket_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin", "")
    parsed = urlparse(origin)
    if os.environ.get("REPLIT_DEPLOYMENT") == "1":
        return parsed.scheme == "https" and parsed.netloc in {
            "soxlpro.xyz", "www.soxlpro.xyz"
        }
    allowed = {"http://127.0.0.1:5000", "http://localhost:5000"}
    dev_domain = os.environ.get("REPLIT_DEV_DOMAIN")
    if dev_domain:
        allowed.add(f"https://{dev_domain}")
    return origin.rstrip("/") in allowed


async def websocket_proxy(request: web.Request) -> web.StreamResponse:
    if not _valid_websocket_origin(request):
        return web.Response(text="Forbidden WebSocket origin", status=403)
    if not _decode(
        request.cookies.get(ANONYMOUS_COOKIE), "anonymous_visitor"
    ):
        return web.Response(
            text="Load the application before opening its WebSocket.",
            status=428,
        )
    user_id, visitor_id, _ = _trusted_identity(request)
    protocols = [
        value.strip()
        for value in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
        if value.strip()
    ]
    try:
        upstream = await request.app["client"].ws_connect(
            f"{STREAMLIT_URL}{request.rel_url}",
            headers=_upstream_headers(request, user_id, visitor_id),
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
    user_id, visitor_id, new_visitor = _trusted_identity(request)
    try:
        upstream = await request.app["client"].request(
            request.method,
            f"{STREAMLIT_URL}{request.rel_url}",
            headers=_upstream_headers(request, user_id, visitor_id),
            data=await request.read(),
            allow_redirects=False,
        )
    except Exception:
        return web.Response(text="Application is starting. Please refresh.", status=503)
    response = web.Response(
        body=await upstream.read(),
        status=upstream.status,
        headers=_proxy_headers(upstream.headers),
    )
    if new_visitor:
        _secure_cookie(
            response,
            ANONYMOUS_COOKIE,
            _encode({"aud": "anonymous_visitor", "sub": visitor_id}, 60 * 60 * 24 * 365),
            60 * 60 * 24 * 365,
        )
    return response


async def startup(app: web.Application) -> None:
    app["client"] = ClientSession(auto_decompress=False)
    app["streamlit"] = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.port", "8501", "--server.address", "127.0.0.1",
        "--server.headless", "true", stdout=sys.stdout, stderr=sys.stderr,
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
    app.router.add_get("/auth/google/start", google_login)
    app.router.add_get("/auth/google/callback", google_callback)
    app.router.add_get("/auth/logout", google_logout)
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