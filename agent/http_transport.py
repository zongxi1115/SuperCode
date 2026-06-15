from __future__ import annotations

import os
from urllib import request
from urllib.parse import urlparse, urlunparse

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def open_url(
    req: request.Request | str,
    *,
    timeout: float | None = None,
):
    """Open HTTP(S) requests with SuperCode's proxy normalization."""

    opener = request.build_opener(request.ProxyHandler(_proxies_for_request(req)))
    return opener.open(req, timeout=timeout)


def _proxies_for_request(req: request.Request | str) -> dict[str, str]:
    target_url = req.full_url if isinstance(req, request.Request) else req
    if _is_local_url(target_url):
        return {}
    return _normalized_system_proxies()


def _normalized_system_proxies() -> dict[str, str]:
    if _env_flag_enabled("SUPERCODE_DISABLE_SYSTEM_PROXY"):
        return {}

    proxies: dict[str, str] = {}
    for scheme, proxy_url in request.getproxies().items():
        if not proxy_url:
            continue
        proxies[scheme] = _normalize_proxy_url(proxy_url)
    return proxies


def _normalize_proxy_url(proxy_url: str) -> str:
    parsed = urlparse(proxy_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and host in _LOCAL_HOSTS:
        parsed = parsed._replace(scheme="http")
        return urlunparse(parsed)
    return proxy_url


def _is_local_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower() in _LOCAL_HOSTS


def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}
