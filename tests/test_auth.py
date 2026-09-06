import auth


def test_production_redirect_uses_public_domain(monkeypatch):
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    monkeypatch.delenv("PUBLIC_APP_URL", raising=False)
    monkeypatch.setenv("REPLIT_DEV_DOMAIN", "preview.example")

    assert auth._redirect_uri() == "https://soxlpro.xyz/oauth2callback"
    assert auth._is_dev_env() is False


def test_workspace_preview_bypasses_oauth(monkeypatch):
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.setenv("REPLIT_DEV_DOMAIN", "preview.example")

    assert auth._is_dev_env() is True


def test_auth_requires_both_google_credentials(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert auth.auth_configured() is False

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    assert auth.auth_configured() is False

    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    assert auth.auth_configured() is True