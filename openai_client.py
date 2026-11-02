"""OpenAI client helper.

Prefer the app owner's standard OpenAI key when configured. Replit AI
Integrations remain available as a fallback for Replit-hosted deployments.
"""

import os

from openai import OpenAI

# the newest OpenAI model is "gpt-5" which was released August 7, 2025.
# do not change this unless explicitly requested by the user
DEFAULT_MODEL = "gpt-5"


def get_openai_client() -> OpenAI:
    """Return a fresh client using the owner's key or Replit integration.

    Never cache this client — credentials can rotate between app restarts.
    """
    own_key = os.environ.get("OPENAI_API_KEY")
    if own_key:
        options = {"api_key": own_key}
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            options["base_url"] = base_url
        return OpenAI(**options)

    base_url = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
    api_key = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
    if not base_url or not api_key:
        raise RuntimeError(
            "OpenAI is not configured. Set OPENAI_API_KEY, or configure the "
            "Replit OpenAI integration."
        )
    return OpenAI(api_key=api_key, base_url=base_url)


def openai_available() -> bool:
    return bool(
        os.environ.get("OPENAI_API_KEY")
        or (
            os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
            and os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
        )
    )
