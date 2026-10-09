# noqa: E402  # pylint: disable=wrong-import-position,import-error
"""Manual, configurable, real-account end-to-end validation flow for prompts.

Not part of the pytest suite. Assumes the configured Switcher account,
domain, and feature flag already exist (real-world usage) -- this script
does not sign up accounts or create any data.

Unlike tools_validation.py (which calls the tools directly), this flow drives
the switcher_domains, switcher_environments, and switcher_get_feature
*prompts*, asserting the generated guidance text correctly embeds the given
arguments and references the tool it is meant to drive.

Usage:
    pipenv run python scripts/e2e/flows/prompt_validation.py

Configuration: see scripts/e2e/README.md and scripts/e2e/.env.e2e.example.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import E2EConfigError, load_config
from mcp_runner import McpToolError, get_prompt_text, mcp_client_session
from oauth_bootstrap import OAuthBootstrapError, bootstrap_credentials


class ValidationError(RuntimeError):
    """Raised when a validation assertion against the live MCP server fails."""


def _assert_contains(text: str, needle: str, prompt_name: str) -> None:
    """Raise a ValidationError if `needle` is missing from a prompt's generated text."""

    if needle not in text:
        raise ValidationError(f"Prompt '{prompt_name}' output did not mention {needle!r}:\n{text}")


async def _run() -> None:
    config = load_config()

    print(f'switcher-api:        {config.switcher_api_url}')
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

        prompts_result = await session.list_prompts()
        prompt_names = {prompt.name for prompt in prompts_result.prompts}
        expected_prompts = {'switcher_domains', 'switcher_environments', 'switcher_get_feature'}
        missing_prompts = expected_prompts - prompt_names
        if missing_prompts:
            raise ValidationError(f'Server did not advertise expected prompt(s): {missing_prompts}')
        print(f'      prompts available: {sorted(prompt_names)}')

        print('[3/5] Rendering switcher_domains prompt...')
        domains_text = await get_prompt_text(session, 'switcher_domains', {'include_collaborations': 'true'})
        _assert_contains(domains_text, 'list_domains', 'switcher_domains')
        print(f'      {domains_text}')

        print('[4/5] Rendering switcher_environments prompt...')
        environments_text = await get_prompt_text(
            session, 'switcher_environments', {'domain_id': config.domain_name}
        )
        _assert_contains(environments_text, 'list_environments', 'switcher_environments')
        _assert_contains(environments_text, config.domain_name, 'switcher_environments')
        print(f'      {environments_text}')

        print('[5/5] Rendering switcher_get_feature prompt...')
        feature_arguments = {'key': config.switcher_key, 'domain': config.domain_name}
        if config.environment:
            feature_arguments['environment'] = config.environment
        feature_text = await get_prompt_text(session, 'switcher_get_feature', feature_arguments)
        _assert_contains(feature_text, 'get_feature_flag', 'switcher_get_feature')
        _assert_contains(feature_text, config.switcher_key, 'switcher_get_feature')
        _assert_contains(feature_text, config.domain_name, 'switcher_get_feature')
        if config.environment:
            _assert_contains(feature_text, config.environment, 'switcher_get_feature')
        print(f'      {feature_text}')

    print('\nE2E PROMPT VALIDATION PASSED')


def main() -> None:
    """Entrypoint: run the async validation flow and map failures to a non-zero exit code."""

    try:
        asyncio.run(_run())
    except (E2EConfigError, OAuthBootstrapError, McpToolError, ValidationError) as error:
        print(f'\nE2E PROMPT VALIDATION FAILED: {error}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
