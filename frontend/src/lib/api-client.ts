const DEFAULT_BACKEND_BASE_URL = 'http://127.0.0.1:3001';

declare global {
  interface Window {
    __SUPERCODE_BACKEND_URL__?: string;
    __TAURI__?: {
      core?: {
        invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>;
      };
      shell?: {
        open(url: string): Promise<void>;
      };
    };
  }
}

function normalizeBackendBaseUrl(value: string | undefined | null) {
  const cleaned = String(value || '').trim().replace(/\/+$/, '');
  return cleaned || DEFAULT_BACKEND_BASE_URL;
}

let backendBaseUrl = normalizeBackendBaseUrl(
  window.__SUPERCODE_BACKEND_URL__ || import.meta.env.VITE_SUPERCODE_BACKEND_URL,
);

export function setBackendBaseUrl(value: string) {
  backendBaseUrl = normalizeBackendBaseUrl(value);
  window.__SUPERCODE_BACKEND_URL__ = backendBaseUrl;
}

export function getBackendBaseUrl() {
  return backendBaseUrl;
}

export async function initializeBackendBaseUrl() {
  if (window.__SUPERCODE_BACKEND_URL__) {
    setBackendBaseUrl(window.__SUPERCODE_BACKEND_URL__);
    return backendBaseUrl;
  }

  const invoke = window.__TAURI__?.core?.invoke;
  if (!invoke) {
    return backendBaseUrl;
  }

  try {
    const value = await invoke<string>('get_backend_base_url');
    setBackendBaseUrl(value);
  } catch (error) {
    console.warn('[SuperCode] failed to resolve desktop backend URL', error);
  }
  return backendBaseUrl;
}

export function apiUrl(path: string) {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${backendBaseUrl}${normalizedPath}`;
}

export function apiWebSocketUrl(path: string) {
  const url = new URL(apiUrl(path));
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

export function apiFetch(input: string | URL | Request, init?: RequestInit) {
  if (typeof input === 'string') {
    return fetch(apiUrl(input), init);
  }
  if (input instanceof URL) {
    return fetch(apiUrl(input.toString()), init);
  }
  return fetch(input, init);
}

export async function openExternalUrl(url: string) {
  if (window.__TAURI__?.shell) {
    try {
      await window.__TAURI__.shell.open(url);
      return;
    } catch {}
  }
  window.open(url, '_blank', 'noopener,noreferrer');
}
