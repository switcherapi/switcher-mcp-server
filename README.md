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

![Switcher API: Cloud-based Feature Flag API](https://raw.githubusercontent.com/switcherapi/switcherapi-assets/master/logo/switcherapi_mcp_server.png)

# About

Switcher MCP Server exposes [Switcher API](https://github.com/switcherapi/switcher-api) feature
flags to MCP-capable AI assistants (Claude Desktop, VS Code, GitHub Copilot CLI, etc.) as a set
of MCP tools. It authenticates on behalf of a real Switcher API user/admin using an OAuth 2.1
Authorization Code + PKCE flow with Dynamic Client Registration, so no client secret is ever
stored or shared.

Toggling feature flags will not be supported by this MCP Server for security and consistency reasons.

# Quick Start

### Requirements

- Python 3.14+
- [pipenv](https://pipenv.pypa.io/) for dependency management
- A running [switcher-api](https://github.com/switcherapi/switcher-api) instance with OAuth enabled
- A [switcher-management](https://github.com/switcherapi/switcher-management) instance for the
  browser-based consent screen (`/oauth/consent`)

# Authentication

How authentication works depends on the transport.

### Streamable HTTP transport

The MCP client (VS Code, Claude, etc.) performs the OAuth flow itself, **on the user's machine**,
when it registers/connects to the MCP server. The server never opens a browser or stores
credentials:

1. The client calls `/mcp` without a token and receives a `401` challenge whose
   `resource_metadata` points to the server's protected-resource metadata.
2. The metadata advertises switcher-api as the authorization server. The client discovers its
   OAuth metadata and dynamically registers via `POST /oauth/register` (public, PKCE-only client).
3. The client opens the consent page in the user's browser (switcher-management's `/oauth/consent`),
   which happens during MCP registration.
4. The client exchanges the code for tokens via `POST /oauth/token` and sends the access token as a
   bearer token on every MCP request. The server forwards it to switcher-api, which validates it
   and its scopes.

If the token is rejected (e.g. consent revoked), tool calls fail with an error asking you to
re-authorize the MCP client. Set `SWITCHER_MCP_PUBLIC_URL` when the server is reachable through a
different URL than `http://<host>:<port>`.

### Stdio transport

The server is a local subprocess of the client, so it runs the authorization flow itself. When a
tool call needs a Switcher API token and none is cached (or the cached one can't be refreshed), it
runs the browser-based flow before retrying the call — the browser is **not** opened eagerly on
server startup. That flow:

1. Discovers switcher-api's OAuth metadata from
   `GET {SWITCHER_API_URL}/.well-known/oauth-authorization-server`.
2. Dynamically registers itself as an OAuth client via `POST /oauth/register` (no client secret
   — a public, PKCE-only client) and persists the issued `client_id` locally.
3. Opens your default browser (the server runs on your machine) to
   switcher-management's consent screen so you can log in (if needed) and approve access.
4. Receives the authorization code on a local loopback callback (`http://127.0.0.1:<port>/callback`)
   and exchanges it for an access/refresh token pair via `POST /oauth/token`.

In stdio mode, credentials (client id, tokens, expiry) are cached at `~/.switcher-mcp/credentials.json`
(file permissions restricted to the current user on POSIX systems) and refreshed automatically
using the rotating refresh token. If the refresh token itself expires, the next tool call will
reopen the browser to re-authorize automatically; if you never complete the consent step, the
authorization attempt times out and the tool call fails with an error telling you to retry.

You can revoke access at any time from switcher-management's **Settings → Authorized Apps** page.

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
| `SWITCHER_MCP_PUBLIC_URL` | `--public-url`    | `http://<host>:<port>` | Externally reachable MCP URL used as the OAuth resource identifier (streamable HTTP only) |
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

# Available Prompts

Prompts are user-selectable, guided templates (e.g. shown as `/switcher_domains` in MCP clients)
that drive one of the tools above and ask the model to summarize or analyze its result. All
prompts are prefixed with `switcher_` for easy discovery.

| Prompt                  | Drives              | Description                                                       |
|--------------------------|----------------------|---------------------------------------------------------------------|
| `switcher_domains`       | `list_domains`       | Discover and summarize the Switcher domains accessible to the authenticated user. |
| `switcher_environments`  | `list_environments`  | List a Switcher domain's environments. |
| `switcher_get_feature`   | `get_feature_flag`   | Fetch a Switcher feature flag's settings. |

# Development

## Quality Gate

```bash
make install      # pipenv install --dev
make lint         # pylint switcher_mcp_server
make test         # pytest with coverage (coverage.xml)
make cover        # generate an HTML coverage report (htmlcov/)
make e2e-tools    # manual, configurable e2e tool validation (see scripts/e2e/README.md)
make e2e-prompts  # manual, configurable e2e prompt validation (see scripts/e2e/README.md)
```

Both `pylint` and `pytest` must pass before merging changes. Tests use `pytest-httpx` to mock all
outbound HTTP calls to switcher-api — no live server is required to run the test suite.

## Project Layout

```
switcher_mcp_server/
    oauth_client.py       # OAuth 2.1 + PKCE client (registration, authorize, token, refresh)
    api_client.py         # Authenticated async HTTP client for switcher-api
    server.py             # Entrypoint wiring tools to the stdio/streamable-http transports
    tools/                # MCP server tools (list_domains, list_environments, get_feature_flag)
tests/                    # pytest suite (unit + transport integration tests)
```

## Contributing

Read our [Contributing](https://github.com/switcherapi/switcher-api/blob/master/CONTRIBUTING.md)
guide to learn about our development process, and how to propose enhancements and improvements.

# AI Disclaimer

This project was designed and implemented with AI-assisted tools. We have thoroughly reviewed and tested all AI-generated contributions to ensure they meet our quality standards and align with our project's goals. We are committed to transparency about our use of AI and will continue to disclose any significant AI contributions in the future.

External contributions from the community are **equally valued and will be reviewed with the same standards, regardless of whether they were assisted by AI or not**. We encourage all contributors to disclose their use of AI tools in their contributions to maintain transparency and foster trust within our community.