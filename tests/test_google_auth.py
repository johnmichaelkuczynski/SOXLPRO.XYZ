import unittest
from unittest.mock import patch

from auth import auth_settings, get_current_user, is_development_preview, redirect_uri, render_google_login


class GoogleAuthTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict("os.environ", {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_auto_login_only_in_development_preview(self):
        self.assertTrue(is_development_preview({"REPLIT_DEV_DOMAIN": "preview.example.com"}))
        self.assertFalse(is_development_preview({}))
        for flag in ("1", "true", "unexpected"):
            self.assertFalse(is_development_preview({
                "REPLIT_DEPLOYMENT": flag, "REPLIT_CONTAINER": "repl",
                "REPLIT_DEV_DOMAIN": "preview.example.com",
            }))

    @patch.dict("os.environ", {"REPLIT_DEV_DOMAIN": "preview.example.com"})
    @patch("auth.configure_google_auth")
    @patch("auth.st")
    def test_preview_stays_signed_in_without_google_or_signout(self, st, configure):
        for _ in range(2):
            self.assertTrue(get_current_user()["is_logged_in"])
            self.assertEqual(get_current_user()["auth_provider"], "development")
            render_google_login()
        configure.assert_not_called()
        st.login.assert_not_called()
        st.logout.assert_not_called()
        st.button.assert_not_called()
        st.caption.assert_called_with("Signed in · Development preview")

    @patch.dict("os.environ", {"REPLIT_DEPLOYMENT": "1", "REPLIT_DEV_DOMAIN": "preview.example.com"})
    @patch("auth.configure_google_auth")
    @patch("auth.st")
    def test_published_app_never_auto_logs_in(self, st, configure):
        st.user.is_logged_in = False
        st.button.return_value = True
        render_google_login()
        configure.assert_called_once()
        st.login.assert_called_once_with("google")
        st.caption.assert_not_called()

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