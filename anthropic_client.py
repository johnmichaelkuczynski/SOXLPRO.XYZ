"""Anthropic client helper supporting owner-supplied and Replit credentials."""
import os

from anthropic import Anthropic


def anthropic_available() -> bool:
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or (
            os.environ.get("AI_INTEGRATIONS_ANTHROPIC_API_KEY")
            and os.environ.get("AI_INTEGRATIONS_ANTHROPIC_BASE_URL")
        )
    )


def get_anthropic_client() -> Anthropic:
    """Create a client without persisting or logging credentials."""
    own_key = os.environ.get("ANTHROPIC_API_KEY")
    if own_key:
        options = {"api_key": own_key}
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if base_url:
            options["base_url"] = base_url
        return Anthropic(**options)

    api_key = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_API_KEY")
    base_url = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_BASE_URL")
    if api_key and base_url:
        return Anthropic(api_key=api_key, base_url=base_url)
    raise RuntimeError(
        "Anthropic is not configured. Set ANTHROPIC_API_KEY, or configure "
        "the Replit Anthropic integration."
    )
