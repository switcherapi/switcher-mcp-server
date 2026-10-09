# Manual E2E Validation (configurable)

Standalone, configurable scripts for exploratory end-to-end validation against
live `switcher-api` / `switcher-management` deployments. **Not part of the
pytest suite** (`make test` never runs anything under this folder) — run them
manually when you want to sanity-check real changes across the stack.

## What this is for

`full_validation.py` drives the **real** `switcher_mcp_server` process (spawned
as a subprocess, talking over the official MCP stdio client SDK) through the
same tool calls a real MCP client would make:

1. Headlessly bootstraps OAuth credentials for a configured account (no
   browser needed — see [OAuth consent bypass](#oauth-consent-bypass) below).
2. Spawns `python -m switcher_mcp_server.server` pointed at your configured
   `SWITCHER_API_URL`.
3. Calls the `list_domains`, `list_environments`, and `get_feature_flag` tools
   exactly as a real MCP client would, and asserts the responses look right.

It assumes the **account, domain, and feature flag already exist** — it does
not sign up accounts or create any data. This intentionally emulates
real-world usage instead of a synthetic throwaway fixture, so you can point it
at any test account/domain/flag you already maintain and just swap
credentials/URLs to test a different environment.

This is different from [`scripts/e2e_validate.py`](../e2e_validate.py), which
signs up a throwaway admin, creates a fresh domain/group/flag, and talks to
switcher-api directly over HTTP (no MCP server involved at all). Use that one
instead if you want a fully disposable, self-contained sanity check of a local
switcher-api build with no pre-existing data.

## Prerequisites

- A reachable `switcher-api` instance with OAuth support.
- An existing Switcher account (email/password) with at least one domain and
  one feature flag key you can validate against.
- `pipenv install --dev` already run in the repo root (`python-dotenv` and
  `httpx` are provided by the project's `Pipfile`).

## Configuration

Copy the template and fill in your values:

```bash
cp scripts/e2e/.env.e2e.example scripts/e2e/.env.e2e
```

`.env.e2e` is gitignored and loaded automatically. You can also just export
the variables in your shell instead of using a file.

| Variable                     | Required | Default                  | Purpose |
|-------------------------------|----------|---------------------------|---------|
| `SWITCHER_API_URL`            | no       | `http://localhost:3000`   | switcher-api base URL — point this at a different shared/local deployment |
| `SWITCHER_MANAGEMENT_URL`     | no       | `http://localhost:3001`   | switcher-management base URL — recorded/documented for future flows; not called yet since the OAuth consent step is simulated headlessly |
| `E2E_ACCOUNT_EMAIL`           | **yes**  | —                          | Email of an existing Switcher account |
| `E2E_ACCOUNT_PASSWORD`        | **yes**  | —                          | Password for that account |
| `E2E_DOMAIN_NAME`             | **yes**  | —                          | Name of an existing domain owned by (or shared with) that account |
| `E2E_SWITCHER_KEY`            | **yes**  | —                          | Key of an existing feature flag under that domain, to validate via `get_feature_flag` |
| `E2E_ENVIRONMENT`             | no       | server default             | Optional environment name to pass to `get_feature_flag` |
| `SWITCHER_MCP_CREDENTIALS_PATH` | no     | `scripts/e2e/.cache/<account-hash>-credentials.json` | Isolated OAuth credentials cache used by the spawned server — never your real `~/.switcher-mcp/credentials.json` |

To switch between accounts/domains/environments (e.g. a throwaway test
account vs. a shared staging account), just maintain multiple `.env.e2e`
files (or shell profiles) and copy the one you want into place, or export the
variables directly before running.

## Running

```bash
pipenv run python scripts/e2e/flows/full_validation.py
# or, from the repo root:
make e2e
```

Exits non-zero and prints a clear error on any failed assertion, config error,
OAuth bootstrap failure, or tool-call error.

## OAuth consent bypass

Real MCP clients open a browser to switcher-management's consent screen. This
script instead logs into switcher-api directly with the configured account's
session JWT and calls `/oauth/authorize?...&consent=true`, which is the same
technique already used by `scripts/e2e_validate.py`. This exercises the exact
same `/oauth/register` → `/oauth/authorize` → `/oauth/token` endpoints as
production — only the human consent click is skipped so the flow can run
unattended. `switcher-management` itself is not called by this flow today;
`SWITCHER_MANAGEMENT_URL` is configured and documented for future flows that
might.

## Adding new flows

This folder is meant to grow. Suggested structure for a new flow:

```
scripts/e2e/
  config.py          # shared config loader — extend with new variables here
  oauth_bootstrap.py # shared headless OAuth bootstrap helper
  mcp_runner.py       # shared helper to spawn the server and call tools
  flows/
    full_validation.py   # existing: read-only validation of an existing account/domain/flag
    <your_new_flow>.py    # add new scenarios here, reusing the shared helpers above
```

Keep new flows:
- Out of `tests/` and free of `test_*` naming so pytest never collects them.
- Configuration-driven (extend `config.py` rather than hardcoding values).
- Documented in this README with a short "what it validates" summary.
