"""Fast public listener; expensive Streamlit and refresh work run in subprocesses."""
from fast_gateway import serve

def __getattr__(name):
    # Keep public-route tests and integrations compatible without cold imports.
    if name in {"PublicDocumentHandler", "SearchableServer", "install_public_routes"}:
        import streamlit_backend
        return getattr(streamlit_backend, name)
    raise AttributeError(name)

if __name__ == "__main__":
    serve(port=5000)
