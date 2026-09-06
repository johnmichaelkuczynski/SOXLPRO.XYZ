from types import SimpleNamespace

import auth
import auth_gateway


class _Request:
    def __init__(self, host, forwarded_host=None):
        self.host = host
        self.headers = {}
        if forwarded_host:
            self.headers["X-Forwarded-Host"] = forwarded_host


def test_production_callback_uses_registered_custom_domain(monkeypatch):
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    request = _Request("127.0.0.1", "soxlpro.xyz")

    assert (
        auth_gateway._public_base_url(request)
        == "https://soxlpro.xyz"
    )


def test_production_callback_accepts_registered_replit_domain(monkeypatch):
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    request = _Request("soxlproxyz.replit.app")

    assert (
        auth_gateway._public_base_url(request)
        == "https://soxlproxyz.replit.app"
    )


def test_unrecognized_production_host_cannot_control_callback(monkeypatch):
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    request = _Request("attacker.example")

    assert auth_gateway._public_base_url(request) == "https://soxlpro.xyz"


def test_signed_session_round_trip(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "x" * 48)
    token = auth_gateway._encode(
        {
            "aud": "soxlpro_session",
            "sub": "google_123456",
            "email": "user@example.com",
        },
        60,
    )

    assert auth_gateway._decode(token, "soxlpro_session") == {
        "aud": "soxlpro_session",
        "sub": "google_123456",
        "email": "user@example.com",
        "iat": auth_gateway._decode(token, "soxlpro_session")["iat"],
        "exp": auth_gateway._decode(token, "soxlpro_session")["exp"],
    }
    assert auth_gateway._decode(token, "google_oauth_state") is None


def test_workspace_preview_bypasses_oauth(monkeypatch):
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.setenv("REPLIT_DEV_DOMAIN", "preview.example")

    assert auth._is_dev_env() is True


def test_production_mode_preview_origin_is_allowed_for_verification(monkeypatch):
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    monkeypatch.setenv("REPLIT_DEV_DOMAIN", "preview.example")
    request = _Request("preview.example")
    request.headers["Origin"] = "https://preview.example"

    assert auth_gateway._valid_websocket_origin(request) is True


def test_production_user_rejects_untrusted_identity(monkeypatch):
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    monkeypatch.setattr(auth, "_trusted_header", lambda _name: None)

    assert auth._production_user() is None


def test_production_user_accepts_gateway_identity(monkeypatch):
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    headers = {
        "X-Soxlpro-User-Id": "google_123456",
        "X-Soxlpro-User-Email": "user@example.com",
    }
    monkeypatch.setattr(auth, "_trusted_header", headers.get)

    assert auth._production_user() == SimpleNamespace(
        is_logged_in=True,
        id="google_123456",
        name="user",
        email="user@example.com",
    )