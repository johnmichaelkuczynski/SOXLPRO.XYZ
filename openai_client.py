"""OpenAI client helper using standard deployment environment variables."""

import os

from openai import OpenAI

# the newest OpenAI model is "gpt-5" which was released August 7, 2025.
# do not change this unless explicitly requested by the user
DEFAULT_MODEL = "gpt-5"


def get_openai_client() -> OpenAI:
    """Return a fresh client using the configured OpenAI API key.

    Never cache this client — credentials can rotate between app restarts.
    """
    own_key = os.environ.get("OPENAI_API_KEY")
    if own_key:
        options = {"api_key": own_key}
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            options["base_url"] = base_url
        return OpenAI(**options)

    raise RuntimeError("OpenAI is not configured. Set OPENAI_API_KEY.")


def openai_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))
