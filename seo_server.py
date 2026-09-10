"""Start the existing Streamlit app with three public HTTP document handlers.

No reverse proxy, alternate app, package-file edits, or user-agent detection.
Streamlit continues to own WebSockets, OAuth, cookies, components and downloads.
The small Server integration uses Streamlit's Tornado backend; compatibility is
checked at startup and by tests because _create_app is an internal API.
"""
import os
from pathlib import Path

from streamlit import config, file_util
from streamlit.web import bootstrap
from streamlit.web.server.server import Server
from tornado.web import RequestHandler

from seo import render_index, robots_txt, sitemap_xml


class PublicDocumentHandler(RequestHandler):
    def initialize(self, body: str, content_type: str, production: bool):
        self.body = body
        self.content_type = content_type
        self.production = production

    def get(self):
        self.set_header("Content-Type", self.content_type)
        self.set_header("Cache-Control", "no-cache")
        self.set_header("X-Content-Type-Options", "nosniff")
        if not self.production:
            self.set_header("X-Robots-Tag", "noindex, nofollow")
        self.finish(self.body)

    def head(self):
        self.get()


def install_public_routes(application, *, production: bool):
    """Prepend only exact document paths; leave all other routing untouched."""
    template = Path(file_util.get_static_dir(), "index.html").read_text()
    routes = []
    for path, body, content_type in [
        (r"/", render_index(template, production=production), "text/html; charset=utf-8"),
        (r"/robots\.txt", robots_txt(production=production), "text/plain; charset=utf-8"),
        (r"/sitemap\.xml", sitemap_xml(), "application/xml; charset=utf-8"),
    ]:
        routes.append((path, PublicDocumentHandler, {
            "body": body, "content_type": content_type, "production": production,
        }))
    application.add_handlers(r".*$", routes)
    return application


class SearchableServer(Server):
    def _create_app(self):
        if config.get_option("server.baseUrlPath"):
            raise RuntimeError("SOXL public routes require an empty server.baseUrlPath.")
        return install_public_routes(
            super()._create_app(),
            production=os.environ.get("REPLIT_DEPLOYMENT") == "1",
        )


def main():
    main_script = str(Path(__file__).with_name("app.py").resolve())
    config._main_script_path = main_script
    flags = {"server.port": 5000, "server.headless": True, "server.useStarlette": False}
    bootstrap.load_config_options(flag_options=flags)
    # Select our subclass before bootstrap starts listening. Unlike app.py,
    # this executes on cold start without waiting for a WebSocket session.
    bootstrap.Server = SearchableServer
    bootstrap.run(main_script, False, [], flags)


if __name__ == "__main__":
    main()