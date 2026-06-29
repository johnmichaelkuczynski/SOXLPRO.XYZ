"""OpenAI client helper — uses Replit AI Integrations (no own API key required).

Integration: blueprint:python_openai_ai_integrations
AI_INTEGRATIONS_OPENAI_BASE_URL and AI_INTEGRATIONS_OPENAI_API_KEY are set
automatically by the Replit OpenAI integration. Charges are billed to Replit
credits. Do not request or modify these env vars.
"""

import os

from openai import OpenAI

# the newest OpenAI model is "gpt-5" which was released August 7, 2025.
# do not change this unless explicitly requested by the user
DEFAULT_MODEL = "gpt-5"


def get_openai_client() -> OpenAI:
    """Return a fresh OpenAI client wired to Replit AI Integrations.

    Never cache this client — the integration credentials can rotate.
    """
    base_url = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
    api_key = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
    if not base_url or not api_key:
        raise RuntimeError(
            "OpenAI AI Integration is not configured "
            "(AI_INTEGRATIONS_OPENAI_BASE_URL / AI_INTEGRATIONS_OPENAI_API_KEY missing)."
        )
    return OpenAI(api_key=api_key, base_url=base_url)


def openai_available() -> bool:
    return bool(
        os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
        and os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
    )
