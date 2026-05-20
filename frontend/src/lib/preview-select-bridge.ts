const PREVIEW_SELECT_PROXY_PREFIX = '/__sc_select_proxy';

function isLoopbackHost(hostname: string): boolean {
  const normalized = hostname.replace(/^\[|\]$/g, '').toLowerCase();
  return normalized === 'localhost' || normalized === '127.0.0.1' || normalized === '::1';
}

export function canUsePreviewSelectBridge(url: string): boolean {
  if (!url || !import.meta.env.DEV) {
    return false;
  }

  try {
    const parsed = new URL(url);
    const protocol = parsed.protocol.replace(/:$/, '');
    return (protocol === 'http' || protocol === 'https') && isLoopbackHost(parsed.hostname);
  } catch {
    return false;
  }
}

export function buildPreviewSelectBridgeSrc(url: string): string {
  try {
    const parsed = new URL(url);
    const protocol = parsed.protocol.replace(/:$/, '');
    const encodedHost = encodeURIComponent(parsed.hostname);
    const encodedPort = encodeURIComponent(parsed.port || '_');
    const pathname = parsed.pathname.startsWith('/') ? parsed.pathname : `/${parsed.pathname}`;

    return `${PREVIEW_SELECT_PROXY_PREFIX}/${protocol}/${encodedHost}/${encodedPort}${pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return url;
  }
}

