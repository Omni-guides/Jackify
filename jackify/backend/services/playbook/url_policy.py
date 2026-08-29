"""
Shared https-scheme + host-allowlist check for URLs that can appear in playbook-adjacent
content: a playbook's `reference_url`, and a catalog entry's asset/tool `url`. One allowlist,
one validator - a host added for one use case is available to the other automatically instead
of two lists silently drifting apart.
"""
from typing import Any
from urllib.parse import urlparse

ALLOWED_HOSTS = {"moddinglinked.com", "github.com", "nexusmods.com", "nuclearsunset.com"}


class UrlPolicyError(ValueError):
    """A URL failed the https-scheme or host-allowlist check."""


def validate_https_allowlisted_url(url: Any, context: str) -> str:
    """Raises UrlPolicyError unless `url` is a non-empty https string on an allowlisted host."""
    if not isinstance(url, str) or not url:
        raise UrlPolicyError(f"{context}: url must be a non-empty string")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UrlPolicyError(f"{context}: url must be https: {url!r}")
    host = (parsed.hostname or "").lower()
    allowed = any(
        host == allowed_host or host.endswith(f".{allowed_host}")
        for allowed_host in ALLOWED_HOSTS
    )
    if not allowed:
        raise UrlPolicyError(f"{context}: url host not allowlisted: {host!r}")
    return url
