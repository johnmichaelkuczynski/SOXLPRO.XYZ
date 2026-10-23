"""Isolated real-app servers for the open-tab regression (no refresh workers)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    mode, port, backend_port = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    if mode == "backend":
        import streamlit_backend as backend

        # Keep the actual app, route installation, config, and Streamlit runtime.
        # Only change the listener; never terminate the preview's backend.
        load = backend.bootstrap.load_config_options
        run = backend.bootstrap.run

        def isolated_load(*, flag_options):
            flag_options["server.port"] = port
            load(flag_options=flag_options)

        def isolated_run(script, hello, args, flags):
            flags["server.port"] = port
            run(script, hello, args, flags)

        backend.bootstrap.load_config_options = isolated_load
        backend.bootstrap.run = isolated_run
        backend.main()
    else:
        import tornado.httpclient
        import tornado.web
        import fast_gateway as gateway

        gateway.BACKEND = f"http://127.0.0.1:{backend_port}"

        async def serve():
            app = tornado.web.Application([
                (r"/(_stcore/stream)", gateway.Socket),
                (r"/(.*)", gateway.Gateway),
            ], websocket_max_message_size=200 * 1024 * 1024)
            app.listen(port, address="127.0.0.1")
            while True:
                try:
                    response = await tornado.httpclient.AsyncHTTPClient().fetch(
                        gateway.BACKEND + "/_stcore/health", request_timeout=1)
                    gateway.ready = response.code == 200
                except Exception:
                    gateway.ready = False
                await asyncio.sleep(.2)

        asyncio.run(serve())
