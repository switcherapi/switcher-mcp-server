"""MCP tools for Switcher domain discovery."""

from __future__ import annotations

from typing import Any

from switcher_mcp_server.tools.shared import _get_api_client, mcp


def _normalize_domain(domain: dict[str, Any], source: str) -> dict[str, Any]:
    """Normalize a raw Switcher domain payload into a stable tool response."""

    return {
        'id': domain.get('_id'),
        'name': domain.get('name'),
        'description': domain.get('description'),
        'activated': domain.get('activated'),
        'sources': [source],
    }


def _merge_domain(existing: dict[str, Any], source: str) -> None:
    """Merge source metadata into an existing normalized domain entry."""

    existing.setdefault('sources', []).append(source)


@mcp.tool(description='List the authenticated user domains, optionally including team collaborations.')
async def list_domains(include_collaborations: bool = True) -> list[dict[str, Any]]:
    """Return normalized owned and collaborative domains accessible to the user."""

    api_client = _get_api_client()
    normalized_domains: dict[str, dict[str, Any]] = {}

    for domain in await api_client.list_domains():
        domain_identifier = domain.get('_id')
        if domain_identifier is None:
            continue

        domain_id = str(domain_identifier)
        normalized_domains[domain_id] = _normalize_domain(domain, 'owned')

    if include_collaborations:
        for domain in await api_client.list_domain_collaborations():
            domain_identifier = domain.get('_id')
            if domain_identifier is None:
                continue

            domain_id = str(domain_identifier)
            if domain_id in normalized_domains:
                _merge_domain(normalized_domains[domain_id], 'collaboration')
                continue

            normalized_domains[domain_id] = _normalize_domain(domain, 'collaboration')

    return sorted(normalized_domains.values(), key=lambda item: str(item.get('name', '')).lower())


@mcp.prompt(description='Discover and summarize the Switcher domains accessible to the authenticated user.')
def switcher_domains(include_collaborations: bool = True) -> str:
    """Build a guided message that drives the list_domains tool and summarizes the result."""

    collaboration_note = (
        'including team collaborations' if include_collaborations else 'owned domains only, no collaborations'
    )
    return (
        f'Call the list_domains tool with include_collaborations={include_collaborations} '
        f'({collaboration_note}). Summarize the returned domains in a table with columns '
        'name, description, and activated.'
    )
