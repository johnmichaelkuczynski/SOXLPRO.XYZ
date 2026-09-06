#!/bin/bash
set -e

# Sync Python dependencies (idempotent, non-interactive)
uv sync

# Re-apply the Google Search Console verification tag in case the
# streamlit package was reinstalled (app.py also does this at startup).
python - <<'EOF'
import pathlib
try:
    import streamlit
    tag = '<meta name="google-site-verification" content="yJ3j7aTgMTOt62WpeNQL_rAWyRMuzLBSVJ7L2BmsAoI" />'
    p = pathlib.Path(streamlit.__file__).parent / "static" / "index.html"
    html = p.read_text()
    if tag not in html:
        p.write_text(html.replace("<head>", "<head>" + tag, 1))
        print("re-injected google-site-verification tag")
except Exception as e:
    print(f"WARNING: could not verify/inject meta tag: {e}")
EOF
