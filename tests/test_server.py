"""Tests for the Switcher MCP server entrypoint and transport wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

from switcher_mcp_server import server


def test_main_defaults_to_stdio_transport(monkeypatch) -> None:
    """With no arguments, the server should run over stdio."""

    fake_server = MagicMock()
    monkeypatch.setattr(server, 'get_mcp_server', lambda: fake_server)
    monkeypatch.delenv('SWITCHER_MCP_TRANSPORT', raising=False)

    server.main([])

    fake_server.run.assert_called_once_with(transport='stdio')


def test_main_runs_streamable_http_transport_with_host_and_port(monkeypatch) -> None:
    """CLI flags should select the streamable HTTP transport with the given host/port."""

    fake_server = MagicMock()
    fake_auth = MagicMock()
    monkeypatch.setattr(server, 'get_mcp_server', lambda: fake_server)
    monkeypatch.setattr(server, 'configure_http_auth', fake_auth)

    server.main(['--transport', 'streamable-http', '--host', '0.0.0.0', '--port', '9000'])

    fake_auth.assert_called_once_with(fake_server, '0.0.0.0', 9000, None)
    fake_server.run.assert_called_once_with(transport='streamable-http', host='0.0.0.0', port=9000)


def test_main_reads_transport_from_environment_variable(monkeypatch) -> None:
    """Environment variables should configure defaults when CLI flags are omitted."""

    fake_server = MagicMock()
    monkeypatch.setattr(server, 'get_mcp_server', lambda: fake_server)
    monkeypatch.setattr(server, 'configure_http_auth', MagicMock())
    monkeypatch.setenv('SWITCHER_MCP_TRANSPORT', 'streamable-http')
    monkeypatch.setenv('SWITCHER_MCP_HOST', '127.0.0.5')
    monkeypatch.setenv('SWITCHER_MCP_PORT', '9100')

    server.main([])

    fake_server.run.assert_called_once_with(transport='streamable-http', host='127.0.0.5', port=9100)
