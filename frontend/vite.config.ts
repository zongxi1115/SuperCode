import http from 'node:http'
import https from 'node:https'
import path from 'node:path'
import { URL } from 'node:url'
import type { IncomingMessage, RequestOptions, ServerResponse } from 'node:http'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

const PREVIEW_PROXY_PREFIX = '/__preview_proxy__'

type PreviewProxyTarget = {
  protocol: 'http' | 'https'
  hostname: string
  port: string
  targetOrigin: string
  targetUrl: URL
}

function parsePreviewProxyTarget(rawUrl: string): PreviewProxyTarget | null {
  const requestUrl = new URL(rawUrl, 'http://localhost')
  if (!requestUrl.pathname.startsWith(`${PREVIEW_PROXY_PREFIX}/`)) {
    return null
  }

  const rawTargetUrl = requestUrl.pathname.slice(PREVIEW_PROXY_PREFIX.length + 1)
  let targetUrl: URL
  try {
    targetUrl = new URL(`${rawTargetUrl}${requestUrl.search}`)
  } catch {
    return null
  }

  const protocol = targetUrl.protocol.replace(/:$/, '')
  if (protocol !== 'http' && protocol !== 'https') {
    return null
  }

  const hostname = targetUrl.hostname
  return {
    protocol,
    hostname,
    port: targetUrl.port,
    targetOrigin: targetUrl.origin,
    targetUrl,
  }
}

function buildProxyUrl(value: string, baseUrl: URL): string {
  try {
    return `${PREVIEW_PROXY_PREFIX}/${new URL(value, baseUrl).href}`
  } catch {
    return value
  }
}

function rewriteCssReferences(css: string, baseUrl: URL): string {
  return css.replace(/url\((['"]?)(?!data:|blob:|#|\/\/|https?:)([^'")]+)\1\)/gi, (_, quote: string, value: string) => {
    return `url(${quote}${buildProxyUrl(value.trim(), baseUrl)}${quote})`
  })
}

function rewriteHtmlReferences(html: string, targetUrl: URL): string {
  return html.replace(
    /\b(src|href|action|poster)=("|')([^"']+)\2/gi,
    (match: string, attr: string, quote: string, value: string) => {
      const normalized = value.trim()
      if (
        !normalized ||
        normalized.startsWith('#') ||
        normalized.startsWith('data:') ||
        normalized.startsWith('blob:') ||
        normalized.startsWith('javascript:') ||
        normalized.startsWith('//')
      ) {
        return match
      }

      return `${attr}=${quote}${buildProxyUrl(normalized, targetUrl)}${quote}`
    },
  )
}

function injectPreviewProxyScript(html: string, targetUrl: URL): string {
  const proxyScript = `<script>
(() => {
  const PROXY_PREFIX = ${JSON.stringify(PREVIEW_PROXY_PREFIX + '/')};
  const TARGET_URL = ${JSON.stringify(targetUrl.href)};
  const toProxyUrl = (value) => {
    if (value == null) return value;
    if (typeof value !== 'string') value = String(value);
    if (!value || value.startsWith('#') || value.startsWith('data:') || value.startsWith('blob:') || value.startsWith('javascript:')) {
      return value;
    }
    if (value.startsWith('//')) {
      return value;
    }
    try {
      if (value.startsWith(PROXY_PREFIX)) {
        return value;
      }
      const absolute = new URL(value, window.location.href);
      if (absolute.origin === window.location.origin && absolute.pathname.startsWith(PROXY_PREFIX)) {
        return absolute.pathname + absolute.search + absolute.hash;
      }
      return PROXY_PREFIX + new URL(value, TARGET_URL).href;
    } catch {
      return value;
    }
  };

  const originalFetch = window.fetch;
  if (typeof originalFetch === 'function') {
    window.fetch = function patchedFetch(input, init) {
      if (typeof input === 'string' || input instanceof URL) {
        return originalFetch.call(this, toProxyUrl(String(input)), init);
      }
      if (input instanceof Request) {
        return originalFetch.call(this, new Request(toProxyUrl(input.url), input), init);
      }
      return originalFetch.call(this, input, init);
    };
  }

  const nativeOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function patchedOpen(method, url, ...rest) {
    return nativeOpen.call(this, method, toProxyUrl(String(url)), ...rest);
  };

  if (typeof window.EventSource === 'function') {
    const NativeEventSource = window.EventSource;
    window.EventSource = function PatchedEventSource(url, config) {
      return new NativeEventSource(toProxyUrl(String(url)), config);
    };
    window.EventSource.prototype = NativeEventSource.prototype;
  }

  if (typeof window.open === 'function') {
    const nativeWindowOpen = window.open;
    window.open = function patchedWindowOpen(url, targetName, features) {
      const nextUrl = typeof url === 'string' ? toProxyUrl(url) : url;
      return nativeWindowOpen.call(window, nextUrl, targetName, features);
    };
  }
})();
</script>`

  const withAbsoluteRefs = rewriteHtmlReferences(html, targetUrl)
  if (/<head[^>]*>/i.test(withAbsoluteRefs)) {
    return withAbsoluteRefs.replace(/<head([^>]*)>/i, `<head$1>${proxyScript}`)
  }
  return `${proxyScript}${withAbsoluteRefs}`
}

function applyProxyHeaders(
  res: ServerResponse,
  upstream: IncomingMessage,
): void {
  const blockedHeaders = new Set([
    'content-length',
    'content-security-policy',
    'content-security-policy-report-only',
    'cross-origin-embedder-policy',
    'cross-origin-opener-policy',
    'cross-origin-resource-policy',
    'frame-options',
    'transfer-encoding',
    'x-frame-options',
  ])

  for (const [key, value] of Object.entries(upstream.headers)) {
    if (value == null || blockedHeaders.has(key.toLowerCase())) {
      continue
    }
    res.setHeader(key, value)
  }
}

async function readStream(stream: IncomingMessage): Promise<Buffer> {
  const chunks: Buffer[] = []
  for await (const chunk of stream) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk))
  }
  return Buffer.concat(chunks)
}

async function handlePreviewProxyRequest(
  req: IncomingMessage,
  res: ServerResponse,
  target: PreviewProxyTarget,
): Promise<void> {
  const transport = target.protocol === 'https' ? https : http
  const headers = { ...req.headers }
  delete headers.host
  headers.origin = target.targetOrigin
  headers.referer = `${target.targetOrigin}/`
  headers['accept-encoding'] = 'identity'

  const requestOptions: RequestOptions = {
    protocol: `${target.protocol}:`,
    hostname: target.hostname,
    port: target.port || undefined,
    method: req.method,
    path: `${target.targetUrl.pathname}${target.targetUrl.search}`,
    headers,
  }

  await new Promise<void>((resolve) => {
    const upstreamRequest = transport.request(requestOptions, async (upstreamResponse) => {
      const contentType = String(upstreamResponse.headers['content-type'] || '').toLowerCase()
      res.statusCode = upstreamResponse.statusCode || 502
      applyProxyHeaders(res, upstreamResponse)

      try {
        if (contentType.includes('text/html')) {
          const body = (await readStream(upstreamResponse)).toString('utf8')
          res.end(injectPreviewProxyScript(body, target.targetUrl))
          resolve()
          return
        }

        if (contentType.includes('text/css')) {
          const body = (await readStream(upstreamResponse)).toString('utf8')
          res.end(rewriteCssReferences(body, target.targetUrl))
          resolve()
          return
        }

        upstreamResponse.pipe(res)
        upstreamResponse.on('end', resolve)
      } catch (error) {
        res.statusCode = 502
        res.setHeader('content-type', 'text/plain; charset=utf-8')
        res.end(`Preview proxy failed: ${error instanceof Error ? error.message : String(error)}`)
        resolve()
      }
    })

    upstreamRequest.on('error', (error) => {
      res.statusCode = 502
      res.setHeader('content-type', 'text/plain; charset=utf-8')
      res.end(`Preview proxy failed: ${error.message}`)
      resolve()
    })

    if (req.method === 'GET' || req.method === 'HEAD') {
      upstreamRequest.end()
      return
    }

    req.pipe(upstreamRequest)
  })
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'supercode-preview-proxy',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const requestUrl = req.url || ''
          const target = parsePreviewProxyTarget(requestUrl)
          if (!target) {
            next()
            return
          }

          void handlePreviewProxyRequest(req, res, target)
        })
      },
    },
  ],
  server: {
    port: 8888,
  },
  preview: {
    port: 8888,
  },
  resolve: {
    alias: [
      // Force `@/` imports to resolve into `src/` even if a real `frontend/@` folder exists.
      { find: /^@\//, replacement: `${path.resolve(__dirname, './src')}/` },
    ],
  },
})
