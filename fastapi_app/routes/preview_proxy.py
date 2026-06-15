from __future__ import annotations

import asyncio
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request as UrlRequest

from agent.http_transport import open_url
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response

PREVIEW_PROXY_ENDPOINT = "/api/preview/proxy"
PREVIEW_PROXY_TIMEOUT_SECONDS = 30


def _validate_target_url(raw_url: str) -> str:
    target_url = raw_url.strip()
    parsed = urlparse(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="预览代理只支持 http/https URL")
    return target_url


def _proxy_url(value: str, base_url: str) -> str:
    target_url = urljoin(base_url, value)
    return f"{PREVIEW_PROXY_ENDPOINT}?url={quote(target_url, safe='')}"


def _rewrite_css_references(css: str, base_url: str) -> str:
    def replace(match: re.Match[str]) -> str:
        quote_char = match.group(1)
        value = match.group(2).strip()
        if not value or value.startswith(("data:", "blob:", "#", "//", "http://", "https://")):
            return match.group(0)
        return f"url({quote_char}{_proxy_url(value, base_url)}{quote_char})"

    return re.sub(r"url\((['\"]?)(?!data:|blob:|#|//|https?:)([^'\")]+)\1\)", replace, css, flags=re.I)


def _rewrite_html_references(html: str, base_url: str) -> str:
    def replace(match: re.Match[str]) -> str:
        attr = match.group(1)
        quote_char = match.group(2)
        value = match.group(3).strip()
        if not value or value.startswith(("#", "data:", "blob:", "javascript:", "//")):
            return match.group(0)
        return f"{attr}={quote_char}{_proxy_url(value, base_url)}{quote_char}"

    return re.sub(
        r"\b(src|href|action|poster)=(\"|')([^\"']+)\2",
        replace,
        html,
        flags=re.I,
    )


def _inject_preview_proxy_script(html: str, base_url: str) -> str:
    proxy_script = f"""<script>
(() => {{
  const PROXY_ENDPOINT = {PREVIEW_PROXY_ENDPOINT!r} + "?url=";
  const TARGET_URL = {base_url!r};
  const toProxyUrl = (value) => {{
    if (value == null) return value;
    if (typeof value !== "string") value = String(value);
    if (!value || value.startsWith("#") || value.startsWith("data:") || value.startsWith("blob:") || value.startsWith("javascript:")) {{
      return value;
    }}
    if (value.startsWith(PROXY_ENDPOINT)) {{
      return value;
    }}
    try {{
      const absolute = new URL(value, window.location.href);
      if (absolute.origin === window.location.origin && absolute.pathname === {PREVIEW_PROXY_ENDPOINT!r}) {{
        return absolute.pathname + absolute.search + absolute.hash;
      }}
      return PROXY_ENDPOINT + encodeURIComponent(new URL(value, TARGET_URL).href);
    }} catch {{
      return value;
    }}
  }};

  const originalFetch = window.fetch;
  if (typeof originalFetch === "function") {{
    window.fetch = function patchedFetch(input, init) {{
      if (typeof input === "string" || input instanceof URL) {{
        return originalFetch.call(this, toProxyUrl(String(input)), init);
      }}
      if (input instanceof Request) {{
        return originalFetch.call(this, new Request(toProxyUrl(input.url), input), init);
      }}
      return originalFetch.call(this, input, init);
    }};
  }}

  const nativeOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function patchedOpen(method, url, ...rest) {{
    return nativeOpen.call(this, method, toProxyUrl(String(url)), ...rest);
  }};

  if (typeof window.EventSource === "function") {{
    const NativeEventSource = window.EventSource;
    window.EventSource = function PatchedEventSource(url, config) {{
      return new NativeEventSource(toProxyUrl(String(url)), config);
    }};
    window.EventSource.prototype = NativeEventSource.prototype;
  }}

  if (typeof window.open === "function") {{
    const nativeWindowOpen = window.open;
    window.open = function patchedWindowOpen(url, targetName, features) {{
      const nextUrl = typeof url === "string" ? toProxyUrl(url) : url;
      return nativeWindowOpen.call(window, nextUrl, targetName, features);
    }};
  }}
}})();
</script>"""

    with_rewritten_refs = _rewrite_html_references(html, base_url)
    if re.search(r"<head[^>]*>", with_rewritten_refs, flags=re.I):
        return re.sub(r"<head([^>]*)>", f"<head\\1>{proxy_script}", with_rewritten_refs, count=1, flags=re.I)
    return f"{proxy_script}{with_rewritten_refs}"


def _response_charset(content_type: str) -> str:
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.I)
    return match.group(1).strip("\"'") if match else "utf-8"


def _filtered_headers(upstream_headers) -> dict[str, str]:
    blocked_headers = {
        "content-length",
        "content-security-policy",
        "content-security-policy-report-only",
        "cross-origin-embedder-policy",
        "cross-origin-opener-policy",
        "cross-origin-resource-policy",
        "frame-options",
        "transfer-encoding",
        "x-frame-options",
    }
    return {
        key: value
        for key, value in upstream_headers.items()
        if key.lower() not in blocked_headers
    }


def _upstream_request_headers(request: Request, target_url: str) -> dict[str, str]:
    parsed = urlparse(target_url)
    target_origin = f"{parsed.scheme}://{parsed.netloc}"
    blocked_headers = {"host", "content-length", "accept-encoding", "origin", "referer"}
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in blocked_headers
    }
    headers["Accept-Encoding"] = "identity"
    headers["Origin"] = target_origin
    headers["Referer"] = f"{target_origin}/"
    return headers


async def _fetch_upstream(request: Request, target_url: str) -> Response:
    body = await request.body()
    method = request.method.upper()
    data = None if method in {"GET", "HEAD"} else body
    upstream_request = UrlRequest(
        target_url,
        data=data,
        headers=_upstream_request_headers(request, target_url),
        method=method,
    )

    def fetch() -> tuple[int, str, dict[str, str], bytes, str]:
        with open_url(upstream_request, timeout=PREVIEW_PROXY_TIMEOUT_SECONDS) as upstream:
            body_bytes = upstream.read()
            final_url = upstream.geturl()
            content_type = upstream.headers.get("content-type", "")
            return upstream.status, content_type, _filtered_headers(upstream.headers), body_bytes, final_url

    try:
        status_code, content_type, headers, body_bytes, final_url = await asyncio.to_thread(fetch)
    except HTTPError as exc:
        body_bytes = exc.read()
        status_code = exc.code
        content_type = exc.headers.get("content-type", "")
        headers = _filtered_headers(exc.headers)
        final_url = exc.geturl()
    except (URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=f"预览代理请求失败：{exc}") from exc

    lowered_content_type = content_type.lower()
    if "text/html" in lowered_content_type:
        charset = _response_charset(content_type)
        text = body_bytes.decode(charset, errors="replace")
        body_bytes = _inject_preview_proxy_script(text, final_url).encode(charset, errors="replace")
    elif "text/css" in lowered_content_type:
        charset = _response_charset(content_type)
        text = body_bytes.decode(charset, errors="replace")
        body_bytes = _rewrite_css_references(text, final_url).encode(charset, errors="replace")

    return Response(
        body_bytes,
        status_code=status_code,
        media_type=content_type or None,
        headers=headers,
    )


def register_preview_proxy_routes(app: FastAPI) -> None:
    @app.api_route(
        PREVIEW_PROXY_ENDPOINT,
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def preview_proxy(request: Request, url: str = Query(...)) -> Response:
        target_url = _validate_target_url(url)
        return await _fetch_upstream(request, target_url)
