import os
import sys

from seo_metadata import inject_structured_data


def main():
    if not inject_structured_data():
        raise RuntimeError("Could not inject structured data into Streamlit")
    port = os.environ.get("STREAMLIT_PORT", "5000")
    address = os.environ.get("STREAMLIT_ADDRESS")
    base_url_path = os.environ.get("STREAMLIT_BASE_URL_PATH")
    streamlit_args = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app.py",
        "--server.port",
        port,
        "--server.headless",
        "true",
    ]
    if address:
        streamlit_args.extend(["--server.address", address])
    if base_url_path:
        streamlit_args.extend(["--server.baseUrlPath", base_url_path])
    os.execv(
        sys.executable,
        streamlit_args,
    )


if __name__ == "__main__":
    main()
