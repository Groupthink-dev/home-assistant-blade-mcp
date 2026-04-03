"""Shared constants, types, and write-gate for Home Assistant Blade MCP server."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default limits for list operations (token efficiency)
DEFAULT_LIMIT = 50
DEFAULT_HISTORY_HOURS = 24


@dataclass
class ProviderConfig:
    """Configuration for a single Home Assistant instance."""

    name: str
    url: str
    token: str


def parse_providers() -> list[ProviderConfig]:
    """Parse HA provider configuration from environment variables.

    Supports two modes:

    1. Multi-provider: ``HA_PROVIDERS=sandybay,paddington`` with per-provider
       ``HA_SANDYBAY_URL``, ``HA_SANDYBAY_TOKEN``

    2. Single-provider (backward-compatible): ``HA_URL``, ``HA_TOKEN``
       treated as provider "default".
    """
    providers_str = os.environ.get("HA_PROVIDERS", "").strip()
    if providers_str:
        providers = []
        for name in providers_str.split(","):
            name = name.strip()
            prefix = f"HA_{name.upper()}_"
            url = os.environ.get(f"{prefix}URL", "").rstrip("/")
            token = os.environ.get(f"{prefix}TOKEN", "")
            if not all([url, token]):
                logger.warning("Incomplete config for provider %s — skipping", name)
                continue
            providers.append(ProviderConfig(name=name, url=url, token=token))
        if not providers:
            raise ValueError("HA_PROVIDERS set but no providers configured correctly")
        return providers

    # Backward-compatible single-provider mode
    url = os.environ.get("HA_URL", "").rstrip("/")
    token = os.environ.get("HA_TOKEN", "")
    if not all([url, token]):
        raise ValueError(
            "Home Assistant credentials not configured. "
            "Set HA_URL and HA_TOKEN, or HA_PROVIDERS with per-provider vars."
        )
    return [ProviderConfig(name="default", url=url, token=token)]


def is_write_enabled() -> bool:
    """Check if write operations are enabled via env var."""
    return os.environ.get("HA_WRITE_ENABLED", "").lower() == "true"


def require_write() -> str | None:
    """Return an error message if writes are disabled, else None."""
    if not is_write_enabled():
        return "Error: Write operations are disabled. Set HA_WRITE_ENABLED=true to enable."
    return None


def require_confirm(confirm: bool) -> str | None:
    """Return an error message if confirm is not set, else None."""
    if not confirm:
        return "Error: This is a destructive or security-sensitive operation. Set confirm=true to proceed."
    return None


def scrub_credentials(text: str) -> str:
    """Remove tokens and URLs with embedded auth from text."""
    # Strip Bearer tokens
    text = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ****", text)
    # Strip URLs with embedded credentials
    text = re.sub(r"https?://[^:]+:[^@]+@", "https://****:****@", text)
    # Strip token parameters
    text = re.sub(r"token=[^\s&]+", "token=****", text, flags=re.IGNORECASE)
    # Strip JWT-like tokens (eyJ...)
    text = re.sub(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*", "****", text)
    return text
