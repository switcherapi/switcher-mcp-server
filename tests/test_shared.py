"""Tests for the shared MCP server and API client wiring."""

from __future__ import annotations

import asyncio

from switcher_mcp_server.tools import shared


def test_shared_api_client_is_built_once_from_environment(monkeypatch, tmp_path) -> None:
    """Tools should lazily build a single API client wired to the configured Switcher URL."""

    monkeypatch.setattr(shared, '_API_CLIENT', None)
    monkeypatch.setenv('SWITCHER_API_URL', 'http://switcher.test')
    monkeypatch.setenv('SWITCHER_MCP_CREDENTIALS_PATH', str(tmp_path / 'credentials.json'))

    first = shared.get_api_client()
    try:
        assert first is shared.get_api_client()
        assert first._base_url == 'http://switcher.test'  # pylint: disable=protected-access
    finally:
        asyncio.run(first.aclose())
