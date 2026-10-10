"""Switcher MCP server entrypoint.

Wires the registered MCP tools (see :mod:`switcher_mcp_server.tools`) to the
stdio and streamable HTTP transports provided by the official MCP SDK.
"""

from __future__ import annotations

import argparse
import os
from typing import Sequence

from switcher_mcp_server.tools import get_mcp_server
from switcher_mcp_server.auth import configure_http_auth

DEFAULT_TRANSPORT = 'stdio'
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8000


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the MCP server entrypoint."""

    parser = argparse.ArgumentParser(
        prog='switcher-mcp-server',
        description='Switcher MCP Server - exposes Switcher API feature flags as MCP tools.',
    )
    parser.add_argument(
        '--transport',
        choices=['stdio', 'streamable-http'],
        default=os.getenv('SWITCHER_MCP_TRANSPORT', DEFAULT_TRANSPORT),
        help='Transport protocol to serve the MCP server on (default: stdio).',
    )
    parser.add_argument(
        '--host',
        default=os.getenv('SWITCHER_MCP_HOST', DEFAULT_HOST),
        help='Host to bind the streamable HTTP transport to (default: 127.0.0.1).',
    )
    parser.add_argument(
        '--port',
        type=int,
        default=int(os.getenv('SWITCHER_MCP_PORT', str(DEFAULT_PORT))),
        help='Port to bind the streamable HTTP transport to (default: 8000).',
    )
    parser.add_argument(
        '--public-url',
        default=os.getenv('SWITCHER_MCP_PUBLIC_URL'),
        help='Externally reachable URL of this MCP server, used as the OAuth resource identifier '
        '(default: http://<host>:<port>). http:// is accepted for development only.',
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Switcher MCP server using the requested transport."""

    args = _build_arg_parser().parse_args(argv)
    server = get_mcp_server()

    if args.transport == 'stdio':
        server.run(transport='stdio')
    else:
        configure_http_auth(server, args.host, args.port, args.public_url)
        server.run(transport='streamable-http', host=args.host, port=args.port)


if __name__ == '__main__':
    main()
