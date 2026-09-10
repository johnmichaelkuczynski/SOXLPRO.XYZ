#!/bin/bash
set -e

# Sync Python dependencies (idempotent, non-interactive)
uv sync

# Fail on an incompatible Streamlit shell/routing upgrade. Metadata is now
# generated in memory by seo_server.py, not patched into installed packages.
python -m unittest discover -s tests -p 'test_seo*.py'
