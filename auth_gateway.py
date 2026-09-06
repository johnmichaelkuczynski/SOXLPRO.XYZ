"""Public Google OAuth gateway and reverse proxy for the Streamlit app."""

from __future__ import annotations

import asyncio
import os
import secrets
import signal
import sys
from time import time
from urllib.parse import urlencode, urlparse

import jwt
from aiohttp import ClientSession, WSMsgType, web


STREAMLIT_URL = "http://127.0.0.1:8501"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
SESSION_COOKIE = "soxlpro_session"
STATE_COOKIE = "soxlpro_oauth_state"
SESSION_LIFETIME = 60 * 60 * 24 * 30
ALLOWED_PRODUCTION_HOSTS = {
    "soxlpro.xyz",
    "soxlproxyz.replit.app",
}
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


def google_oauth_configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_CLIENT_ID")
        and os.environ.get("GOOGLE_CLIENT_SECRET")
        and len(os.environ.get("SESSION_SECRET", "")) >= 32
    )


def _session_secret() -> str:
    value = os.environ.get("SESSION_SECRET", "")
    if len(value) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
    return value


def _request_host(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-Host", "")
    host = (forwarded.split(",", 1)[0] or request.host).strip().lower()
    return host.split(":", 1)[0]


def _public_base_url(request: web.Request) -> str:
    host = _request_host(request)
    if os.environ.get("REPLIT_DEPLOYMENT") == "1":
        if host not in ALLOWED_PRODUCTION_HOSTS:
            host = "soxlpro.xyz"
        return f"https://{host}"

    dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "").strip().lower()
    if dev_domain and host == dev_domain:
        return f"https://{dev_domain}"
    return "http://localhost:5000"


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


def _secure_cookie(
    response: web.StreamResponse,
    name: str,
    value: str,
    max_age: int,
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        secure=os.environ.get("REPLIT_DEPLOYMENT") == "1",
        httponly=True,
        samesite="Lax",
        path="/",
    )


async def google_login(request: web.Request) -> web.Response:
    if not google_oauth_configured():
        return web.Response(text="Google sign-in is unavailable.", status=503)

    nonce = secrets.token_urlsafe(24)
    redirect_uri = f"{_public_base_url(request)}/auth/google/callback"
    state = _encode(
        {
            "aud": "google_oauth_state",
            "nonce": nonce,
            "redirect_uri": redirect_uri,
        },
        600,
    )
    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
    }
    response = web.HTTPFound(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")
    _secure_cookie(response, STATE_COOKIE, state, 600)
    raise response


_google_jwks = jwt.PyJWKClient(
    GOOGLE_JWKS_URL,
    cache_keys=True,
    lifespan=300,
)


def _verify_google_id_token(
    id_token: str,
    expected_nonce: str,
) -> tuple[str, str]:
    key = _google_jwks.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        key.key,
        algorithms=["RS256"],
        audience=os.environ["GOOGLE_CLIENT_ID"],
        options={"verify_iss": False},
    )
    if claims.get("iss") not in {
        "accounts.google.com",
        "https://accounts.google.com",
    }:
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

    expected_redirect = f"{_public_base_url(request)}/auth/google/callback"
    redirect_uri = state.get("redirect_uri")
    if redirect_uri != expected_redirect:
        raise web.HTTPFound("/?auth=failed")

    async with request.app["client"].post(
        GOOGLE_TOKEN_URL,
        data={
            "code": request.query["code"],
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    ) as token_response:
        token_data = await token_response.json()
    if token_response.status != 200 or not token_data.get("id_token"):
        raise web.HTTPFound("/?auth=failed")

    try:
        user_id, email = await asyncio.to_thread(
            _verify_google_id_token,
            token_data["id_token"],
            state["nonce"],
        )
    except Exception:
        raise web.HTTPFound("/?auth=failed")

    response = web.HTTPFound("/?auth=complete")
    _secure_cookie(
        response,
        SESSION_COOKIE,
        _encode(
            {
                "aud": "soxlpro_session",
                "sub": user_id,
                "email": email,
            },
            SESSION_LIFETIME,
        ),
        SESSION_LIFETIME,
    )
    response.del_cookie(STATE_COOKIE, path="/")
    raise response


async def google_logout(request: web.Request) -> web.Response:
    response = web.HTTPFound("/?auth=logged_out")
    response.del_cookie(SESSION_COOKIE, path="/")
    raise response


async def auth_status(request: web.Request) -> web.Response:
    """Expose non-secret deployment evidence for authentication diagnostics."""
    user_id, _email = _trusted_identity(request)
    return web.json_response(
        {
            "service": "soxlpro-google-auth",
            "callback_path": "/auth/google/callback",
            "oauth_configured": google_oauth_configured(),
            "authenticated": bool(user_id),
        }
    )


def _proxy_headers(headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_HEADERS
        and key.lower() != "host"
        and not key.lower().startswith("sec-websocket-")
        and key.lower() != "origin"
        and not key.lower().startswith("x-soxlpro-")
        and key.lower() not in {"x-forwarded-for", "cf-connecting-ip"}
    }


def _trusted_identity(request: web.Request) -> tuple[str | None, str | None]:
    session = _decode(request.cookies.get(SESSION_COOKIE), "soxlpro_session")
    if not session:
        return None, None
    user_id = session.get("sub")
    email = session.get("email")
    if (
        not isinstance(user_id, str)
        or not user_id.startswith("google_")
        or not isinstance(email, str)
        or "@" not in email
    ):
        return None, None
    return user_id, email


def _upstream_headers(
    request: web.Request,
    user_id: str | None,
    email: str | None,
) -> dict[str, str]:
    headers = _proxy_headers(request.headers)
    if user_id and email:
        headers["X-Soxlpro-User-Id"] = user_id
        headers["X-Soxlpro-User-Email"] = email
    return headers


def _valid_websocket_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin", "")
    parsed = urlparse(origin)
    if os.environ.get("REPLIT_DEPLOYMENT") == "1":
        allowed_hosts = set(ALLOWED_PRODUCTION_HOSTS)
        dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "").strip()
        if dev_domain:
            allowed_hosts.add(dev_domain)
        return parsed.scheme == "https" and parsed.netloc in allowed_hosts

    allowed = {"http://127.0.0.1:5000", "http://localhost:5000"}
    dev_domain = os.environ.get("REPLIT_DEV_DOMAIN")
    if dev_domain:
        allowed.add(f"https://{dev_domain}")
    return origin.rstrip("/") in allowed


async def websocket_proxy(request: web.Request) -> web.StreamResponse:
    if not _valid_websocket_origin(request):
        return web.Response(text="Forbidden WebSocket origin", status=403)

    user_id, email = _trusted_identity(request)
    protocols = [
        value.strip()
        for value in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
        if value.strip()
    ]
    try:
        upstream = await request.app["client"].ws_connect(
            f"{STREAMLIT_URL}{request.rel_url}",
            headers=_upstream_headers(request, user_id, email),
            protocols=protocols,
            origin=STREAMLIT_URL,
            heartbeat=30,
            max_msg_size=16 * 1024 * 1024,
        )
    except Exception:
        return web.Response(text="Application WebSocket unavailable", status=503)

    downstream = web.WebSocketResponse(protocols=protocols, heartbeat=30)
    await downstream.prepare(request)

    async def client_to_streamlit() -> None:
        async for message in downstream:
            if message.type == WSMsgType.TEXT:
                await upstream.send_str(message.data)
            elif message.type == WSMsgType.BINARY:
                await upstream.send_bytes(message.data)
            elif message.type == WSMsgType.CLOSE:
                await upstream.close()

    async def streamlit_to_client() -> None:
        async for message in upstream:
            if message.type == WSMsgType.TEXT:
                await downstream.send_str(message.data)
            elif message.type == WSMsgType.BINARY:
                await downstream.send_bytes(message.data)
            elif message.type == WSMsgType.CLOSE:
                await downstream.close()

    try:
        await asyncio.gather(client_to_streamlit(), streamlit_to_client())
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        await upstream.close()
    return downstream


async def streamlit_proxy(request: web.Request) -> web.StreamResponse:
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await websocket_proxy(request)

    user_id, email = _trusted_identity(request)
    try:
        upstream = await request.app["client"].request(
            request.method,
            f"{STREAMLIT_URL}{request.rel_url}",
            headers=_upstream_headers(request, user_id, email),
            data=await request.read(),
            allow_redirects=False,
        )
    except Exception:
        return web.Response(text="Application is starting. Please refresh.", status=503)
    return web.Response(
        body=await upstream.read(),
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
    app.router.add_get("/auth/google/start", google_login)
    app.router.add_get("/auth/google/callback", google_callback)
    app.router.add_get("/auth/logout", google_logout)
    app.router.add_get("/auth/status", auth_status)
    app.router.add_route("*", "/{path:.*}", streamlit_proxy)
    return app


if __name__ == "__main__":
    web.run_app(
        create_app(),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        access_log=None,
    )