"""Spawns the real switcher_mcp_server subprocess and drives it via the
official MCP stdio client SDK.

This intentionally exercises the actual `switcher_mcp_server.server`
entrypoint (stdio transport, real OAuth-backed API client, real registered
tools) rather than reimplementing raw HTTP calls, so a passing run means the
MCP server genuinely works end-to-end for a real account/domain/flag.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import E2EConfig


class McpToolError(RuntimeError):
    """Raised when an MCP tool call returns an error result."""


@asynccontextmanager
async def mcp_client_session(config: E2EConfig) -> AsyncGenerator[ClientSession, None]:
    """Spawn switcher_mcp_server over stdio and yield an initialized ClientSession."""

    server_params = StdioServerParameters(
        command=sys.executable,
        args=['-m', 'switcher_mcp_server.server'],
        env={
            'SWITCHER_API_URL': config.switcher_api_url,
            'SWITCHER_MCP_CREDENTIALS_PATH': str(config.credentials_path),
        },
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


def _unwrap_structured_content(structured_content: Any) -> Any:
    """Unwrap the `{"result": ...}` envelope used for non-object tool return types."""

    if isinstance(structured_content, dict) and set(structured_content.keys()) == {'result'}:
        return structured_content['result']
    return structured_content


async def call_tool(session: ClientSession, name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Call an MCP tool and return its structured result, raising on tool errors."""

    result = await session.call_tool(name, arguments or {})
    if result.is_error:
        text_parts = [block.text for block in result.content if getattr(block, 'text', None)] # type: ignore
        raise McpToolError(f"Tool '{name}' returned an error: {' '.join(text_parts) or result.content}")

    return _unwrap_structured_content(result.structured_content)


async def get_prompt_text(session: ClientSession, name: str, arguments: dict[str, str] | None = None) -> str:
    """Fetch an MCP prompt and return the text of its single generated user message."""

    result = await session.get_prompt(name, arguments or {})
    if not result.messages:
        raise McpToolError(f"Prompt '{name}' returned no messages.")

    content = result.messages[0].content
    text = getattr(content, 'text', None)
    if text is None:
        raise McpToolError(f"Prompt '{name}' returned a non-text message: {content!r}")

    return text
