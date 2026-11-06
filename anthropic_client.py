"""Anthropic client helper using standard deployment environment variables."""
import os

from anthropic import Anthropic


def anthropic_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def get_anthropic_client() -> Anthropic:
    """Create a client without persisting or logging credentials."""
    own_key = os.environ.get("ANTHROPIC_API_KEY")
    if own_key:
        options = {"api_key": own_key}
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if base_url:
            options["base_url"] = base_url
        return Anthropic(**options)

    raise RuntimeError(
        "Anthropic is not configured. Set ANTHROPIC_API_KEY."
    )
