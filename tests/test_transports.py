"""Integration tests exercising the stdio and streamable HTTP transports end-to-end."""

from __future__ import annotations

import socket
import sys
import threading
import time

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from switcher_mcp_server.tools import get_mcp_server

EXPECTED_TOOL_NAMES = {'list_domains', 'list_environments', 'get_feature_flag'}


def _free_port() -> int:
    """Return an available TCP port on localhost."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.mark.anyio
async def test_stdio_transport_exposes_registered_tools() -> None:
    """A real MCP client connecting over stdio should discover all registered tools."""

    params = StdioServerParameters(
        command=sys.executable,
        args=['-m', 'switcher_mcp_server.server'],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

    tool_names = {tool.name for tool in tools.tools}
    assert EXPECTED_TOOL_NAMES.issubset(tool_names)


def test_streamable_http_transport_exposes_registered_tools() -> None:
    """A real MCP client connecting over streamable HTTP should discover all registered tools."""

    port = _free_port()
    server = get_mcp_server()

    server_thread = threading.Thread(
        target=lambda: anyio.run(lambda: server.run_streamable_http_async(host='127.0.0.1', port=port)),
        daemon=True,
    )
    server_thread.start()
    time.sleep(1.0)  # give the ASGI server time to bind before connecting.

    async def _discover_tools() -> set[str]:
        url = f'http://127.0.0.1:{port}/mcp'
        async with streamable_http_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return {tool.name for tool in tools.tools}

    tool_names = anyio.run(_discover_tools)
    assert EXPECTED_TOOL_NAMES.issubset(tool_names)
