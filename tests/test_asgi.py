"""Tests for the uvicorn-compatible ASGI entrypoint."""

from __future__ import annotations

from unittest.mock import MagicMock

from switcher_mcp_server import asgi


def test_create_app_uses_default_host_and_port(monkeypatch) -> None:
    """With no environment variables set, the app should be built with the documented defaults."""

    fake_server = MagicMock()
    fake_auth = MagicMock()
    monkeypatch.setattr(asgi, 'get_mcp_server', lambda: fake_server)
    monkeypatch.setattr(asgi, 'configure_http_auth', fake_auth)
    monkeypatch.delenv('SWITCHER_MCP_HOST', raising=False)
    monkeypatch.delenv('SWITCHER_MCP_PORT', raising=False)
    monkeypatch.delenv('SWITCHER_MCP_PUBLIC_URL', raising=False)
    monkeypatch.delenv('SWITCHER_API_URL', raising=False)

    app = asgi.create_app()

    fake_auth.assert_called_once_with(fake_server, asgi.DEFAULT_HOST, asgi.DEFAULT_PORT, None)
    fake_server.streamable_http_app.assert_called_once_with(host=asgi.DEFAULT_HOST)
    assert app is fake_server.streamable_http_app.return_value


def test_create_app_reads_configuration_from_environment(monkeypatch) -> None:
    """Environment variables should configure the host, port, and public URL."""

    fake_server = MagicMock()
    fake_auth = MagicMock()
    monkeypatch.setattr(asgi, 'get_mcp_server', lambda: fake_server)
    monkeypatch.setattr(asgi, 'configure_http_auth', fake_auth)
    monkeypatch.setenv('SWITCHER_MCP_HOST', '0.0.0.0')
    monkeypatch.setenv('SWITCHER_MCP_PORT', '8443')
    monkeypatch.setenv('SWITCHER_MCP_PUBLIC_URL', 'https://mcp.switcherapi.com')
    monkeypatch.setenv('SWITCHER_API_URL', 'https://switcherapi.com/api')

    asgi.create_app()

    fake_auth.assert_called_once_with(fake_server, '0.0.0.0', 8443, 'https://mcp.switcherapi.com')
    fake_server.streamable_http_app.assert_called_once_with(host='0.0.0.0')
