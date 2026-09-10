"""Public search metadata and factual copy shared by HTTP and Streamlit."""
import html
import re

# Verified with Replit deployment metadata on 2026-09-10. Never infer from Host,
# forwarded headers, or a workspace development domain.
CANONICAL_URL = "https://soxlpro.xyz/"
TITLE = "SOXL Pro | SOXL Charts, Probabilities & Backtesting"
DESCRIPTION = (
    "Analyze SOXL with interactive historical charts, price-move probabilities, "
    "benchmark comparisons, options risk tools, and strategy backtesting."
)
VERIFICATION = "yJ3j7aTgMTOt62WpeNQL_rAWyRMuzLBSVJ7L2BmsAoI"

ABOUT_HTML = """<section aria-label="About SOXL Pro">
<h2>SOXL Pro: semiconductor ETF analysis</h2>
<p>SOXL Pro is a research app for SOXL, the Direxion Daily Semiconductor Bull
3X Shares ETF. Explore historical prices, draw trend lines, compare benchmarks
such as QQQ, and study historical price-move probabilities.</p>
<p>The app includes options risk and reward analysis, volatility tools,
SOXL–QQQ comparisons, strategy backtesting, and an AI-assisted strategy builder.
Historical estimates depend on the selected data window and model assumptions;
they are not guaranteed forecasts.</p>
<h3>Understand the risks</h3>
<p>SOXL seeks three times the daily performance of its semiconductor index,
before fees and expenses. Daily resetting and compounding mean returns over
longer periods can differ substantially from three times the index return.
Leveraged ETFs and options can produce substantial losses.</p>
<p>SOXL Pro provides educational research tools, not investment advice.
Past performance does not guarantee future results. Market data may be delayed.</p>
</section>"""


def render_index(template: str, *, production: bool) -> str:
    """Enrich the installed shell in memory, before the first browser session."""
    # Older app versions patched this tag into site-packages. Remove it first
    # so both clean installs and existing workspaces get exactly one copy.
    template = re.sub(
        r'<meta\b(?=[^>]*\bname=["\']google-site-verification["\'])[^>]*>',
        "", template, flags=re.I,
    )
    template, count = re.subn(
        r"<title>.*?</title>", f"<title>{html.escape(TITLE)}</title>",
        template, flags=re.S | re.I,
    )
    if count != 1 or template.count('<div id="root"></div>') != 1:
        raise RuntimeError("Streamlit HTML changed; review SEO shell compatibility.")
    robots = "index, follow" if production else "noindex, nofollow"
    metadata = f"""
    <meta name="description" content="{html.escape(DESCRIPTION, quote=True)}">
    <meta name="robots" content="{robots}">
    <meta name="google-site-verification" content="{VERIFICATION}">
    <link rel="canonical" href="{CANONICAL_URL}">
    <meta property="og:type" content="website">
    <meta property="og:site_name" content="SOXL Pro">
    <meta property="og:title" content="{html.escape(TITLE, quote=True)}">
    <meta property="og:description" content="{html.escape(DESCRIPTION, quote=True)}">
    <meta property="og:url" content="{CANONICAL_URL}">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="{html.escape(TITLE, quote=True)}">
    <meta name="twitter:description" content="{html.escape(DESCRIPTION, quote=True)}">
"""
    if template.count("</head>") != 1:
        raise RuntimeError("Streamlit HTML has no unique head; SEO setup aborted.")
    template = template.replace("</head>", metadata + "</head>", 1)
    # React replaces this public, non-personalized loading content on mount.
    # The same description remains available in the app's About section.
    return template.replace(
        '<div id="root"></div>',
        '<div id="root"><main><h1>SOXL Pro</h1>' + ABOUT_HTML
        + "<p>Enable JavaScript to use the interactive analysis app.</p></main></div>",
        1,
    )


def robots_txt(*, production: bool) -> str:
    if not production:
        return "User-agent: *\nDisallow: /\n"
    return (
        "User-agent: *\nAllow: /\n"
        "Disallow: /_stcore/\nDisallow: /auth/\nDisallow: /oauth2callback\n"
        "Disallow: /component/\nDisallow: /*?\n"
        f"\nSitemap: {CANONICAL_URL}sitemap.xml\n"
    )


def sitemap_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{CANONICAL_URL}</loc></url></urlset>\n"
    )