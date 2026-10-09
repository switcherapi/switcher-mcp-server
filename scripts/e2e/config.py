"""Configuration loader for the manual, configurable e2e validation flows.

Not part of the pytest suite. Reads plain environment variables, optionally
pre-populated from a local ``.env.e2e`` file (see ``.env.e2e.example``) via
``python-dotenv`` if it is installed and the file exists.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

_E2E_DIR = Path(__file__).resolve().parent
_DOTENV_PATH = _E2E_DIR / '.env.e2e'

try:
    from dotenv import load_dotenv

    if _DOTENV_PATH.exists():
        load_dotenv(_DOTENV_PATH)
except ImportError:
    pass

DEFAULT_SWITCHER_API_URL = 'http://localhost:3000'
DEFAULT_SWITCHER_MANAGEMENT_URL = 'http://localhost:3001'

_REQUIRED_VARS = (
    'E2E_ACCOUNT_EMAIL',
    'E2E_ACCOUNT_PASSWORD',
    'E2E_DOMAIN_NAME',
    'E2E_SWITCHER_KEY',
)


class E2EConfigError(RuntimeError):
    """Raised when required e2e configuration is missing or invalid."""


@dataclass(frozen=True)
class E2EConfig:
    """Resolved configuration for a manual e2e validation run."""

    switcher_api_url: str
    switcher_management_url: str
    account_email: str
    account_password: str
    domain_name: str
    switcher_key: str
    environment: str | None
    credentials_path: Path


def _account_slug(email: str) -> str:
    """Derive a filesystem-safe, stable slug for isolating credentials per account."""

    return hashlib.sha256(email.encode('utf-8')).hexdigest()[:16]


def load_config() -> E2EConfig:
    """Load and validate configuration from the environment.

    Raises:
        E2EConfigError: if any required variable is missing.
    """

    missing = [name for name in _REQUIRED_VARS if not os.getenv(name)]
    if missing:
        raise E2EConfigError(
            'Missing required e2e configuration variable(s): '
            f"{', '.join(missing)}. Copy scripts/e2e/.env.e2e.example to "
            'scripts/e2e/.env.e2e and fill in the values, or export them '
            'in your shell.'
        )

    email = os.environ['E2E_ACCOUNT_EMAIL']
    credentials_path_override = os.getenv('SWITCHER_MCP_CREDENTIALS_PATH')
    credentials_path = (
        Path(credentials_path_override)
        if credentials_path_override
        else _E2E_DIR / '.cache' / f'{_account_slug(email)}-credentials.json'
    )

    return E2EConfig(
        switcher_api_url=os.getenv('SWITCHER_API_URL', DEFAULT_SWITCHER_API_URL).rstrip('/'),
        switcher_management_url=os.getenv(
            'SWITCHER_MANAGEMENT_URL', DEFAULT_SWITCHER_MANAGEMENT_URL
        ).rstrip('/'),
        account_email=email,
        account_password=os.environ['E2E_ACCOUNT_PASSWORD'],
        domain_name=os.environ['E2E_DOMAIN_NAME'],
        switcher_key=os.environ['E2E_SWITCHER_KEY'],
        environment=os.getenv('E2E_ENVIRONMENT') or None,
        credentials_path=credentials_path,
    )
