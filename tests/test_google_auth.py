import unittest
from unittest.mock import patch

from auth import auth_settings, redirect_uri, render_google_login


class GoogleAuthTests(unittest.TestCase):
    def test_production_uses_public_origin_even_with_workspace_markers(self):
        self.assertEqual(redirect_uri({
            "REPLIT_DEPLOYMENT": "1", "REPLIT_CONTAINER": "repl",
            "REPLIT_DEV_DOMAIN": "workspace.example.com",
            "PUBLIC_APP_URL": "https://app.example.com/",
        }), "https://app.example.com/oauth2callback")

    def test_preview_returns_to_preview_without_mock_identity(self):
        self.assertEqual(redirect_uri({
            "REPLIT_DEV_DOMAIN": "workspace.example.com",
            "PUBLIC_APP_URL": "https://app.example.com",
        }), "https://workspace.example.com/oauth2callback")

    def test_missing_configuration_fails_explicitly(self):
        with self.assertRaises(ValueError):
            auth_settings({})
        with self.assertRaises(ValueError):
            redirect_uri({"REPLIT_DEPLOYMENT": "1"})

    def test_unsafe_origins_rejected(self):
        for origin in ("http://app.example.com", "https://u:p@app.example.com",
                       "https://app.example.com/other", "https://app.example.com?redirect=x"):
            with self.assertRaises(ValueError):
                redirect_uri({"PUBLIC_APP_URL": origin})

    def test_google_oidc_minimum_identity_scopes(self):
        settings = auth_settings({
            "PUBLIC_APP_URL": "https://app.example.com",
            "GOOGLE_CLIENT_ID": "test-client", "GOOGLE_CLIENT_SECRET": "test-only",
            "SESSION_SECRET": "test-cookie",
        })
        self.assertEqual(settings["google"]["client_kwargs"]["scope"], "openid email profile")
        self.assertEqual(settings["cookie_secret"], "test-cookie")

    @patch("auth.configure_google_auth")
    @patch("auth.st")
    def test_login_invokes_google_provider(self, st, configure):
        st.user.is_logged_in = False
        st.button.return_value = True
        render_google_login()
        st.login.assert_called_once_with("google")
        st.logout.assert_not_called()

    @patch("auth.configure_google_auth")
    @patch("auth.st")
    def test_logout_clears_session_and_uses_native_logout(self, st, configure):
        st.user.is_logged_in = True
        st.button.return_value = True
        render_google_login()
        st.session_state.clear.assert_called_once()
        st.logout.assert_called_once()

    @patch("auth.configure_google_auth", side_effect=ValueError("private configuration"))
    @patch("auth.st")
    def test_errors_never_echo_configuration(self, st, configure):
        render_google_login()
        st.login.assert_not_called()
        self.assertNotIn("private configuration", str(st.error.call_args))


if __name__ == "__main__":
    unittest.main()