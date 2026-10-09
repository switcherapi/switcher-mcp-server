"""Manual, configurable, real-account end-to-end validation flow.

Not part of the pytest suite. Assumes the configured Switcher account,
domain, and feature flag already exist (real-world usage) -- this script
does not sign up accounts or create any data.

Usage:
    pipenv run python scripts/e2e/flows/full_validation.py

Configuration: see scripts/e2e/README.md and scripts/e2e/.env.e2e.example.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import E2EConfigError, load_config  # noqa: E402  pylint: disable=wrong-import-position
from mcp_runner import McpToolError, call_tool, mcp_client_session  # noqa: E402  pylint: disable=wrong-import-position
from oauth_bootstrap import OAuthBootstrapError, bootstrap_credentials  # noqa: E402  pylint: disable=wrong-import-position


class ValidationError(RuntimeError):
    """Raised when a validation assertion against the live MCP server fails."""


async def _run() -> None:
    config = load_config()

    print(f'switcher-api:        {config.switcher_api_url}')
    print(f'switcher-management: {config.switcher_management_url} (configured, not called by this flow)')
    print(f'account:              {config.account_email}')
    print(f'domain:               {config.domain_name}')
    print(f'switcher_key:         {config.switcher_key}')
    print(f'environment:          {config.environment or "(server default)"}')
    print(f'credentials cache:    {config.credentials_path}')
    print()

    print('[1/5] Bootstrapping OAuth credentials headlessly...')
    bootstrap_credentials(config)
    print('      credentials cached ok')

    async with mcp_client_session(config) as session:
        print('[2/5] switcher_mcp_server started and MCP session initialized')

        tools_result = await session.list_tools()
        tool_names = {tool.name for tool in tools_result.tools}
        expected_tools = {'list_domains', 'list_environments', 'get_feature_flag'}
        missing_tools = expected_tools - tool_names
        if missing_tools:
            raise ValidationError(f'Server did not advertise expected tool(s): {missing_tools}')
        print(f'      tools available: {sorted(tool_names)}')

        print('[3/5] Calling list_domains...')
        domains = await call_tool(session, 'list_domains')
        matching_domain = next(
            (domain for domain in domains if domain.get('name') == config.domain_name),
            None,
        )
        if matching_domain is None:
            available = [domain.get('name') for domain in domains]
            raise ValidationError(
                f"Domain '{config.domain_name}' not found for this account. Available domains: {available}"
            )
        print(f"      found domain '{config.domain_name}' (id={matching_domain.get('id')})")

        print('[4/5] Calling list_environments...')
        environments = await call_tool(session, 'list_environments', {'domain_id': matching_domain['id']})
        print(f'      environments: {environments}')

        print('[5/5] Calling get_feature_flag...')
        flag = await call_tool(
            session,
            'get_feature_flag',
            {
                'key': config.switcher_key,
                'domain': config.domain_name,
                'environment': config.environment,
            },
        )
        if flag.get('key') != config.switcher_key:
            raise ValidationError(f"Unexpected flag key in response: {flag.get('key')!r}")
        if not isinstance(flag.get('enabled'), bool):
            raise ValidationError(f"'enabled' field is not a boolean: {flag.get('enabled')!r}")
        print(f"      flag '{flag['key']}' enabled={flag['enabled']}")

    print('\nE2E VALIDATION PASSED')


def main() -> None:
    """Entrypoint: run the async validation flow and map failures to a non-zero exit code."""

    try:
        asyncio.run(_run())
    except (E2EConfigError, OAuthBootstrapError, McpToolError, ValidationError) as error:
        print(f'\nE2E VALIDATION FAILED: {error}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
