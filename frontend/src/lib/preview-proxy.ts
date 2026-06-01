const PREVIEW_PROXY_PREFIX = '/__preview_proxy__';

export function buildPreviewProxySrc(url: string): string {
  try {
    const parsed = new URL(url);

    return `${PREVIEW_PROXY_PREFIX}/${parsed.href}`;
  } catch {
    return url;
  }
}
