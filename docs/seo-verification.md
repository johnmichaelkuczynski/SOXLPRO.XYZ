# Search response verification — 2026-09-10

## Published baseline (read-only, not the new implementation)

Replit deployment metadata reported the public primary URL
`https://soxlpro.xyz`, with `https://soxlproxyz.replit.app` as an additional URL.
The current published build was reported successful. Its live deployment type
was autoscale; the workspace already specified VM for the next publish. This
change preserves that existing workspace target.

Unauthenticated HTTPS GET checks against the primary URL returned:

| Path | Status | Content-Type | Observation |
| --- | --- | --- | --- |
| `/` | 200 | text/html | title Streamlit; no SOXL text |
| `/robots.txt` | 200 | text/html | same Streamlit shell, not robots text |
| `/sitemap.xml` | 200 | text/html | same Streamlit shell, not sitemap XML |

These reproduce the scan findings recorded in the assigned plan. No standalone
earlier scan report was present in the current checkout.

## Implemented and verified in development

The workflow runs `python seo_server.py`. It serves the installed Streamlit
shell enriched in memory at startup, without modifying the installed package.
The same entrypoint is configured for the next publish.

Raw HTTPS responses through the workspace preview:

| Path | Status | Content-Type | Observation |
| --- | --- | --- | --- |
| `/` | 200 | text/html; charset=utf-8 | SOXL title, description, canonical, meaningful body copy |
| `/robots.txt` | 200 | text/plain; charset=utf-8 | development Disallow: / |
| `/sitemap.xml` | 200 | application/xml; charset=utf-8 | parses; only https://soxlpro.xyz/ |
| `/_stcore/health` | 200 | native Streamlit response | ok |

Development SEO documents have noindex headers. Production-mode HTTP tests
verify crawl-allowing robots with the sitemap reference, no development noindex
header, valid GET/HEAD responses, exact route matching, and fixed canonical URLs
even with a hostile Host header. The 10 unittest checks passed, including real
Streamlit handler ordering and installed HTML compatibility. Python compilation,
shell syntax, and whitespace checks passed.

A development browser smoke verified metadata after React mount, removal of
initial fallback content, the unchanged header and Buy placement, preview
sign-out/sign-in, the existing Buy dialog, chart rendering and scale controls,
and the expanded About text. No real Google login or purchase was attempted.
WebSockets/components loaded. Repeated SVG text-coordinate NaN console errors
and a WebGL warning were observed without blocking those interactions; chart
code was not modified by this work.

## Not yet verified

No publishing action was performed. The checks above do not prove the new
responses are live or indexed. After the owner publishes, re-check the primary
URL's raw `/`, `/robots.txt`, and `/sitemap.xml` responses, ensuring no production
noindex directive, then verify the rendered app and canonical. If the deployment
domain changes, obtain current deployment metadata before updating the canonical.
Search engines decide indexing, rankings, and traffic independently.