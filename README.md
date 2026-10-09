***

<div align="center">
<b>Switcher MCP Server</b><br>
MCP Server for Switcher API
</div>

<div align="center">

[![Master CI](https://github.com/switcherapi/switcher-mcp-server/actions/workflows/master.yml/badge.svg?branch=master)](https://github.com/switcherapi/switcher-mcp-server/actions/workflows/master.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=switcherapi_switcher-mcp-server&metric=alert_status)](https://sonarcloud.io/dashboard?id=switcherapi_switcher-mcp-server)
![Known Vulnerabilities](https://snyk.io/test/github/switcherapi/switcher-mcp-server/badge.svg)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker Hub](https://img.shields.io/docker/pulls/trackerforce/switcher-mcp-server.svg)](https://hub.docker.com/r/trackerforce/switcher-mcp-server)
[![Slack: Switcher-HQ](https://img.shields.io/badge/slack-@switcher/hq-blue.svg?logo=slack)](https://switcher-hq.slack.com/)

</div>

***

![Switcher API: Cloud-based Feature Flag API](https://raw.githubusercontent.com/switcherapi/switcherapi-assets/master/logo/switcherapi_grey.png)

# About

Switcher MCP Server exposes [Switcher API](https://github.com/switcherapi/switcher-api) feature
flags to MCP-capable AI assistants (Claude Desktop, VS Code, GitHub Copilot CLI, etc.) as a set
of MCP tools. It authenticates on behalf of a real Switcher API user/admin using an OAuth 2.1
Authorization Code + PKCE flow with Dynamic Client Registration, so no client secret is ever
stored or shared.

This is an MVP focused on **read-only** access:
- Discover the domains and environments a user can access.
- Read a feature flag's settings (enabled state, description, strategies, relay config).

Write operations (creating/toggling flags) are intentionally out of scope for this MVP.

# Quick Start

### Requirements

- Python 3.14+ (see `requires-python` in `pyproject.toml`)
- [pipenv](https://pipenv.pypa.io/) for dependency management
- A running [switcher-api](https://github.com/switcherapi/switcher-api) instance with OAuth
  support (authorization server + `/config/key/:key` endpoint)
- A [switcher-management](https://github.com/switcherapi/switcher-management) instance for the
  browser-based consent screen (`/oauth/consent`)

### Installation

```bash
git clone https://github.com/switcherapi/switcher-mcp-server.git
cd switcher-mcp-server

# Reuses the project-local .venv if present, otherwise pipenv creates one.
make install
```

`make install` runs `pipenv install --dev`, installing both runtime dependencies (`mcp`, `httpx`)
and development dependencies (`pylint`, `pytest`, `pytest-cov`, `pytest-httpx`) into the
project's virtual environment.

# Authentication

The first time a tool call needs a Switcher API token and none is cached (or the cached one can't
be refreshed), the server transparently runs the browser-based authorization flow before retrying
the call — the browser is **not** opened eagerly on server startup. That flow:

1. Discovers switcher-api's OAuth metadata from
   `GET {SWITCHER_API_URL}/.well-known/oauth-authorization-server`.
2. Dynamically registers itself as an OAuth client via `POST /oauth/register` (no client secret
   — a public, PKCE-only client) and persists the issued `client_id` locally.
3. Opens your default browser, **on the machine running the MCP server process**, to
   switcher-management's consent screen so you can log in (if needed) and approve access.
4. Receives the authorization code on a local loopback callback (`http://127.0.0.1:<port>/callback`)
   and exchanges it for an access/refresh token pair via `POST /oauth/token`.

Credentials (client id, tokens, expiry) are cached at `~/.switcher-mcp/credentials.json`
(file permissions restricted to the current user on POSIX systems) and refreshed automatically
using the rotating refresh token. If the refresh token itself expires, the next tool call will
reopen the browser to re-authorize automatically; if you never complete the consent step, the
authorization attempt times out and the tool call fails with an error telling you to retry.

You can revoke access at any time from switcher-management's **Settings → Authorized Apps** page.

> **Note on `streamable-http`:** because the browser is opened on the server's own host, automatic
> authorization only works cleanly when the server and the browser approving access belong to the
> same single user on the same machine (e.g. local development). A hosted, multi-tenant
> `streamable-http` deployment serving multiple remote users would need a per-session credential
> store and a way to hand the authorize URL back to the remote client instead of opening a local
> browser — that is not implemented yet.

# Running the Server

Configure the target switcher-api instance via the `SWITCHER_API_URL` environment variable
(defaults to `http://localhost:3000`).

### Stdio Transport

The default transport, used when the server is launched as a local subprocess by an MCP client:

```bash
SWITCHER_API_URL=https://api.switcherapi.com pipenv run python -m switcher_mcp_server.server
```

### Streamable HTTP Transport

For a hosted/remote MCP server:

```bash
pipenv run python -m switcher_mcp_server.server --transport streamable-http --host 0.0.0.0 --port 8000
```

The server will be reachable at `http://<host>:<port>/mcp`.

## Configuration

| Variable                 | CLI flag         | Default             | Description                                   |
|---------------------------|-------------------|----------------------|------------------------------------------------|
| `SWITCHER_API_URL`        | —                 | `http://localhost:3000` | Base URL of the target switcher-api instance |
| `SWITCHER_MCP_TRANSPORT`  | `--transport`     | `stdio`              | `stdio` or `streamable-http`                   |
| `SWITCHER_MCP_HOST`       | `--host`          | `127.0.0.1`          | Bind host for the streamable HTTP transport    |
| `SWITCHER_MCP_PORT`       | `--port`          | `8000`               | Bind port for the streamable HTTP transport    |
| `SWITCHER_MCP_CREDENTIALS_PATH` | —           | `~/.switcher-mcp/credentials.json` | Override the persisted OAuth credentials cache location |

CLI flags take precedence over environment variables.

## MCP Client Configuration

Example stdio configuration for an MCP client (e.g. Claude Desktop, VS Code):

```json
{
  "mcpServers": {
    "switcher": {
      "command": "pipenv",
      "args": ["run", "python", "-m", "switcher_mcp_server.server"],
      "cwd": "/path/to/switcher-mcp-server",
      "env": {
        "SWITCHER_API_URL": "https://api.switcherapi.com"
      }
    }
  }
}
```

# Available Tools

| Tool               | Description                                                                 |
|---------------------|------------------------------------------------------------------------------|
| `list_domains`      | List the domains the authenticated user owns and/or collaborates on.        |
| `list_environments` | List environment names for a given domain id.                               |
| `get_feature_flag`  | Get a feature flag's settings by key, domain name, and optional environment. |

# Development

## Quality Gate

```bash
make install   # pipenv install --dev
make lint      # pylint switcher_mcp_server
make test      # pytest with coverage (coverage.xml)
make cover     # generate an HTML coverage report (htmlcov/)
make e2e       # manual, configurable e2e validation (see scripts/e2e/README.md)
```

Both `pylint` and `pytest` must pass before merging changes. Tests use `pytest-httpx` to mock all
outbound HTTP calls to switcher-api — no live server is required to run the test suite.

## Manual End-to-End Validation

`scripts/e2e_validate.py` is a standalone script (not part of the automated pytest suite) that
exercises the full OAuth + config-by-key flow against a **live** switcher-api instance backed by
a real MongoDB. Use it to sanity-check a local switcher-api build:

```bash
pipenv run python scripts/e2e_validate.py
```

It signs up a throwaway admin, registers an OAuth client, completes the PKCE authorize/token
exchange, and calls `/domain`, `/environment`, and `/config/key/:key` using only the issued OAuth
access token.

For a configurable flow that drives the **real** `switcher_mcp_server` process (over the MCP
stdio transport) against an **existing** account/domain/flag — with switchable switcher-api and
switcher-management endpoints — see [`scripts/e2e/README.md`](scripts/e2e/README.md).

## Project Layout

```
switcher_mcp_server/
    oauth_client.py       # OAuth 2.1 + PKCE client (registration, authorize, token, refresh)
    api_client.py         # Authenticated async HTTP client for switcher-api
    server.py             # Entrypoint wiring tools to the stdio/streamable-http transports
    tools/
        context_tools.py  # list_domains / list_environments
        flag_tools.py     # get_feature_flag
tests/                    # pytest suite (unit + transport integration tests)
```

## Contributing

Read our [Contributing](https://github.com/switcherapi/switcher-api/blob/master/CONTRIBUTING.md)
guide to learn about our development process, and how to propose enhancements and improvements.

# AI Disclaimer

This project was designed and implemented with AI-assisted tools. We have thoroughly reviewed and tested all AI-generated contributions to ensure they meet our quality standards and align with our project's goals. We are committed to transparency about our use of AI and will continue to disclose any significant AI contributions in the future.

External contributions from the community are **equally valued and will be reviewed with the same standards, regardless of whether they were assisted by AI or not**. We encourage all contributors to disclose their use of AI tools in their contributions to maintain transparency and foster trust within our community.