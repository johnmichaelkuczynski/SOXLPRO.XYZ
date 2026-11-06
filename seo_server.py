"""Fast public listener; expensive Streamlit and refresh work run in subprocesses."""
import os

from fast_gateway import serve


def configured_port(environ=None):
    env = os.environ if environ is None else environ
    try:
        port = int(env.get("PORT") or "5000")
    except (TypeError, ValueError):
        raise ValueError("PORT must be an integer from 1 to 65535.") from None
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer from 1 to 65535.")
    return port


def __getattr__(name):
    # Keep public-route tests and integrations compatible without cold imports.
    if name in {"PublicDocumentHandler", "SearchableServer", "install_public_routes"}:
        import streamlit_backend
        return getattr(streamlit_backend, name)
    raise AttributeError(name)

if __name__ == "__main__":
    serve(port=configured_port())
