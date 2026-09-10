import html
import os
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from xml.etree import ElementTree

import tornado.web
from streamlit import file_util
from tornado.httputil import HTTPHeaders
from tornado.testing import AsyncHTTPTestCase

from seo import ABOUT_HTML, CANONICAL_URL, TITLE, render_index, robots_txt, sitemap_xml
from seo_server import PublicDocumentHandler, SearchableServer, install_public_routes


class _DocumentParser(HTMLParser):
    """Collect the small amount of document structure relevant to SEO tests."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titles = []
        self.meta = []
        self.links = []
        self.text = []
        self._in_title = False
        self._title_text = []

    def handle_starttag(self, tag, attrs):
        attrs = {key.lower(): value for key, value in attrs}
        if tag.lower() == "title":
            self._in_title = True
            self._title_text = []
        elif tag.lower() == "meta":
            self.meta.append(attrs)
        elif tag.lower() == "link":
            self.links.append(attrs)

    def handle_endtag(self, tag):
        if tag.lower() == "title" and self._in_title:
            self.titles.append("".join(self._title_text))
            self._in_title = False

    def handle_data(self, data):
        self.text.append(data)
        if self._in_title:
            self._title_text.append(data)


def _parse_document(document):
    parser = _DocumentParser()
    parser.feed(document)
    parser.close()
    return parser


def _normalise_text(document):
    return " ".join(" ".join(_parse_document(document).text).split())


class SeoDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell_path = Path(file_util.get_static_dir()) / "index.html"
        cls.shell = cls.shell_path.read_text()

    def test_installed_streamlit_shell_is_compatible(self):
        """The patch is tested against the installed shell, not a copied fixture."""
        self.assertTrue(self.shell_path.is_file())
        self.assertEqual(self.shell.count("<title>"), 1)
        self.assertEqual(self.shell.count("</title>"), 1)
        self.assertEqual(self.shell.count('<div id="root"></div>'), 1)
        self.assertEqual(self.shell.count("</head>"), 1)

        for production in (True, False):
            rendered = render_index(self.shell, production=production)
            self.assertEqual(rendered.count('<div id="root"><main>'), 1)
            self.assertEqual(rendered.count("</head>"), 1)

    def test_metadata_has_one_title_verification_and_canonical(self):
        rendered = render_index(self.shell, production=True)
        parsed = _parse_document(rendered)

        self.assertEqual(parsed.titles, [TITLE])
        verification = [
            attrs.get("content")
            for attrs in parsed.meta
            if attrs.get("name", "").lower() == "google-site-verification"
        ]
        self.assertEqual(len(verification), 1)
        self.assertTrue(verification[0])

        canonical = [
            attrs.get("href")
            for attrs in parsed.links
            if attrs.get("rel", "").lower() == "canonical"
        ]
        self.assertEqual(canonical, [CANONICAL_URL])

        # The installed shell already contains a verification tag in some
        # Streamlit releases.  There must still be exactly one after rendering.
        self.assertEqual(
            len(re.findall(r"google-site-verification", rendered, flags=re.I)), 1
        )
        self.assertEqual(len(re.findall(r'rel="canonical"', rendered, flags=re.I)), 1)
        self.assertEqual(html.unescape(parsed.titles[0]), TITLE)

    def test_initial_html_contains_the_factual_about_copy(self):
        rendered = render_index(self.shell, production=True)
        about_text = _normalise_text(ABOUT_HTML)
        initial_text = _normalise_text(rendered)

        self.assertIn(about_text, initial_text)
        self.assertIn(
            "SOXL Pro is a research app for SOXL, the Direxion Daily Semiconductor Bull 3X Shares ETF.",
            initial_text,
        )
        self.assertIn(
            "SOXL Pro provides educational research tools, not investment advice.",
            initial_text,
        )
        self.assertIn("Leveraged ETFs and options can produce substantial losses.", initial_text)

    def test_robots_are_explicitly_environment_specific(self):
        self.assertEqual(robots_txt(production=False), "User-agent: *\nDisallow: /\n")

        production = robots_txt(production=True)
        self.assertIn("User-agent: *\nAllow: /\n", production)
        self.assertIn("Disallow: /_stcore/\n", production)
        self.assertIn("Disallow: /auth/\n", production)
        self.assertIn("Disallow: /oauth2callback\n", production)
        self.assertIn("Disallow: /component/\n", production)
        self.assertIn("Disallow: /*?\n", production)
        self.assertIn(f"Sitemap: {CANONICAL_URL}sitemap.xml\n", production)
        self.assertNotIn("noindex", production.lower())

    def test_sitemap_xml_parses_and_contains_only_verified_canonical(self):
        namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
        root = ElementTree.fromstring(sitemap_xml())
        self.assertEqual(root.tag, f"{{{namespace}}}urlset")

        locations = [
            element.text
            for element in root.findall(f"{{{namespace}}}url/{{{namespace}}}loc")
        ]
        self.assertEqual(locations, [CANONICAL_URL])
        self.assertEqual(len(locations), 1)

        parsed = urlsplit(locations[0])
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "soxlpro.xyz")
        self.assertEqual(parsed.path, "/")
        self.assertEqual(parsed.query, "")
        self.assertEqual(parsed.fragment, "")


class _NativeRouteHandler(tornado.web.RequestHandler):
    def initialize(self, marker):
        self.marker = marker

    def get(self, *args):
        self.set_header("Content-Type", "text/plain; charset=utf-8")
        self.finish(self.marker)


def _fake_native_application(*, production):
    application = tornado.web.Application(
        [
            (r"/oauth2callback", _NativeRouteHandler, {"marker": "native-oauth"}),
            (r"/auth/login", _NativeRouteHandler, {"marker": "native-auth-login"}),
            (r"/auth/logout", _NativeRouteHandler, {"marker": "native-auth-logout"}),
            (r"/_stcore/stream", _NativeRouteHandler, {"marker": "native-websocket"}),
            (r"/component/(.*)", _NativeRouteHandler, {"marker": "native-component"}),
            (
                r"/_stcore/bidi-components/(.*)",
                _NativeRouteHandler,
                {"marker": "native-bidi-component"},
            ),
            (r"/(.*)", _NativeRouteHandler, {"marker": "native-fallback"}),
        ]
    )
    return install_public_routes(application, production=production)


class PublicRoutesHTTPTests(AsyncHTTPTestCase):
    def get_app(self):
        return _fake_native_application(production=True)

    def test_public_documents_support_get_and_head_with_safe_headers(self):
        expected_types = {
            "/": "text/html; charset=utf-8",
            "/robots.txt": "text/plain; charset=utf-8",
            "/sitemap.xml": "application/xml; charset=utf-8",
        }
        for path, content_type in expected_types.items():
            with self.subTest(path=path):
                get_response = self.fetch(path)
                self.assertEqual(get_response.code, 200)
                self.assertEqual(get_response.headers.get("Content-Type"), content_type)
                self.assertEqual(get_response.headers.get("Cache-Control"), "no-cache")
                self.assertEqual(
                    get_response.headers.get("X-Content-Type-Options"), "nosniff"
                )
                self.assertIsNone(get_response.headers.get("X-Robots-Tag"))
                self.assertTrue(get_response.body)

                head_response = self.fetch(path, method="HEAD")
                self.assertEqual(head_response.code, 200)
                self.assertEqual(head_response.body, b"")
                self.assertEqual(head_response.headers.get("Content-Type"), content_type)
                self.assertEqual(head_response.headers.get("Cache-Control"), "no-cache")
                self.assertEqual(
                    head_response.headers.get("X-Content-Type-Options"), "nosniff"
                )

    def test_malicious_host_cannot_change_the_canonical_origin(self):
        headers = HTTPHeaders({"Host": "attacker.example.invalid"})
        for path in ("/", "/sitemap.xml"):
            with self.subTest(path=path):
                response = self.fetch(path, headers=headers)
                self.assertEqual(response.code, 200)
                self.assertIn(CANONICAL_URL.encode(), response.body)
                self.assertNotIn(b"attacker.example.invalid", response.body)

    def test_only_exact_seo_paths_override_native_fallback(self):
        native_paths = {
            "/oauth2callback": b"native-oauth",
            "/auth/login": b"native-auth-login",
            "/auth/logout": b"native-auth-logout",
            "/_stcore/stream": b"native-websocket",
            "/component/example/main.js": b"native-component",
            "/_stcore/bidi-components/example": b"native-bidi-component",
            "/robots.txt/": b"native-fallback",
            "/sitemap.xml/": b"native-fallback",
        }
        for path, expected_body in native_paths.items():
            with self.subTest(path=path):
                response = self.fetch(path)
                self.assertEqual(response.code, 200)
                self.assertEqual(response.body, expected_body)


class DevelopmentPublicRoutesHTTPTests(AsyncHTTPTestCase):
    def get_app(self):
        return _fake_native_application(production=False)

    def test_development_robots_and_headers_are_non_indexable(self):
        response = self.fetch("/robots.txt")
        self.assertEqual(response.code, 200)
        self.assertEqual(response.body, b"User-agent: *\nDisallow: /\n")
        self.assertEqual(response.headers.get("Content-Type"), "text/plain; charset=utf-8")
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache")
        self.assertEqual(response.headers.get("X-Robots-Tag"), "noindex, nofollow")

        index = self.fetch("/")
        self.assertEqual(index.headers.get("X-Robots-Tag"), "noindex, nofollow")
        self.assertIn(b'<meta name="robots" content="noindex, nofollow">', index.body)


class SearchableServerContractTests(unittest.TestCase):
    def test_create_app_puts_three_public_routes_before_stream_oauth_and_components(self):
        # Server construction and _create_app only create in-memory handlers; no
        # app secrets, browser session, or external service is needed here.
        with patch.dict(os.environ, {"REPLIT_DEPLOYMENT": "1"}):
            application = SearchableServer(
                str(Path(__file__).resolve().parents[1] / "app.py"), False
            )._create_app()

        top_level_rules = application.default_router.rules
        self.assertGreaterEqual(len(top_level_rules), 2)
        public_rules = top_level_rules[0].target.rules
        self.assertEqual(len(public_rules), 3)
        self.assertTrue(all(rule.target is PublicDocumentHandler for rule in public_rules))

        public_patterns = [
            rule.matcher.regex.pattern
            for rule in public_rules
        ]
        self.assertTrue(public_patterns[0].endswith("/$"))
        self.assertTrue(public_patterns[1].endswith(r"/robots\.txt$"))
        self.assertTrue(public_patterns[2].endswith(r"/sitemap\.xml$"))
        self.assertTrue(all(rule.target_kwargs["production"] for rule in public_rules))

        native_rules = top_level_rules[1].target.rules

        def native_target_for(path_fragment):
            rule = next(
                rule
                for rule in native_rules
                if path_fragment in getattr(rule.matcher.regex, "pattern", "")
            )
            return rule.target.__name__

        self.assertEqual(native_target_for("_stcore/stream"), "BrowserWebSocketHandler")
        self.assertEqual(native_target_for("/component/"), "ComponentRequestHandler")
        self.assertEqual(native_target_for("oauth2callback"), "AuthCallbackHandler")


if __name__ == "__main__":
    unittest.main()