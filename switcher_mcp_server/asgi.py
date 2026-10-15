"""ASGI entrypoint for running the streamable HTTP transport under an external ASGI server.

``switcher_mcp_server.server`` already runs the streamable HTTP transport through an embedded
uvicorn instance, but that embedded instance always binds a single worker with plain HTTP and
offers no way to pass TLS certificates or tune the worker count. Exposing ``create_app`` here lets
operators run this module directly with an external uvicorn process instead, e.g.:

    uvicorn switcher_mcp_server.asgi:create_app \\
        --factory \\
        --host 0.0.0.0 \\
        --port 8443 \\
        --ssl-certfile=/etc/certs/ca.crt \\
        --ssl-keyfile=/etc/certs/ca.key \\
        --workers 4

``--factory`` is required: ``create_app()`` mutates the shared MCP server instance (wiring up
bearer-token auth), so it must only run once uvicorn actually starts serving, not merely whenever
this module gets imported (e.g. for tooling or tests) — otherwise that side effect would leak into
whatever process happened to import it first.
"""

from __future__ import annotations

import os

from starlette.applications import Starlette

from switcher_mcp_server.auth import configure_http_auth
from switcher_mcp_server.oauth_client import DEFAULT_SWITCHER_API_URL
from switcher_mcp_server.tools import get_mcp_server

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8000


def create_app() -> Starlette:
    """Build the Starlette ASGI app for the streamable-http transport."""

    # api_client/oauth_client read SWITCHER_API_URL lazily via os.getenv; set it explicitly so it
    # has a resolved default even if the environment variable is unset.
    os.environ.setdefault('SWITCHER_API_URL', DEFAULT_SWITCHER_API_URL)

    host = os.getenv('SWITCHER_MCP_HOST', DEFAULT_HOST)
    port = int(os.getenv('SWITCHER_MCP_PORT', str(DEFAULT_PORT)))
    public_url = os.getenv('SWITCHER_MCP_PUBLIC_URL')

    server = get_mcp_server()
    configure_http_auth(server, host, port, public_url)
    return server.streamable_http_app(host=host)
