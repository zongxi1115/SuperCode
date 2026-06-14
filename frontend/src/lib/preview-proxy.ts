import { apiUrl } from './api-client';

const PREVIEW_PROXY_PREFIX = '/__preview_proxy__';
const BACKEND_PREVIEW_PROXY_PATH = '/api/preview/proxy';

function isDesktopRuntime(): boolean {
  return typeof window !== 'undefined' && Boolean(window.__TAURI__?.core);
}

export function buildPreviewProxySrc(url: string): string {
  try {
    const parsed = new URL(url);

    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return url;
    }

    if (isDesktopRuntime()) {
      return apiUrl(`${BACKEND_PREVIEW_PROXY_PATH}?url=${encodeURIComponent(parsed.href)}`);
    }

    return `${PREVIEW_PROXY_PREFIX}/${parsed.href}`;
  } catch {
    return url;
  }
}
