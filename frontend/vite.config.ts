import http from 'node:http'
import https from 'node:https'
import path from 'node:path'
import { URL } from 'node:url'
import type { IncomingMessage, RequestOptions, ServerResponse } from 'node:http'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

const PREVIEW_SELECT_PROXY_PREFIX = '/__sc_select_proxy'

type SelectProxyTarget = {
  protocol: 'http' | 'https'
  hostname: string
  port: string
  targetOrigin: string
  targetUrl: URL
}

function isLoopbackHost(hostname: string): boolean {
  const normalized = hostname.replace(/^\[|\]$/g, '').toLowerCase()
  return normalized === 'localhost' || normalized === '127.0.0.1' || normalized === '::1'
}

function parseSelectProxyTarget(rawUrl: string): SelectProxyTarget | null {
  const requestUrl = new URL(rawUrl, 'http://localhost')
  if (!requestUrl.pathname.startsWith(`${PREVIEW_SELECT_PROXY_PREFIX}/`)) {
    return null
  }

  const remainder = requestUrl.pathname.slice(PREVIEW_SELECT_PROXY_PREFIX.length + 1)
  const segments = remainder.split('/')
  if (segments.length < 3) {
    return null
  }

  const [protocolToken, encodedHost, encodedPort, ...pathSegments] = segments
  if (protocolToken !== 'http' && protocolToken !== 'https') {
    return null
  }

  const hostname = decodeURIComponent(encodedHost)
  const portToken = decodeURIComponent(encodedPort)
  if (!isLoopbackHost(hostname)) {
    return null
  }

  const port = portToken === '_' ? '' : portToken
  const pathname = `/${pathSegments.join('/')}`.replace(/\/{2,}/g, '/')
  const targetOrigin = `${protocolToken}://${hostname}${port ? `:${port}` : ''}`
  const targetUrl = new URL(`${targetOrigin}${pathname}${requestUrl.search}`)

  return {
    protocol: protocolToken,
    hostname,
    port,
    targetOrigin,
    targetUrl,
  }
}

function absolutizeHtmlReferences(html: string, targetOrigin: string): string {
  return html.replace(
    /\b(src|href|action|poster)=("|')\/(?!\/)/gi,
    (_, attr: string, quote: string) => `${attr}=${quote}${targetOrigin}/`,
  )
}

function injectBridgeScript(html: string, targetOrigin: string): string {
  const bridgeScript = `<script>
(() => {
  const TARGET_ORIGIN = ${JSON.stringify(targetOrigin)};
  const normalize = (value) => {
    if (value == null) return value;
    if (typeof value !== 'string') value = String(value);
    if (!value || value.startsWith('#') || value.startsWith('data:') || value.startsWith('blob:') || value.startsWith('javascript:')) {
      return value;
    }
    if (value.startsWith('//')) {
      return value;
    }
    if (value.startsWith('/')) {
      return TARGET_ORIGIN + value;
    }
    try {
      const absolute = new URL(value, TARGET_ORIGIN + '/');
      if (absolute.origin === window.location.origin) {
        return value;
      }
      return absolute.href;
    } catch {
      return value;
    }
  };

  const originalFetch = window.fetch;
  if (typeof originalFetch === 'function') {
    window.fetch = function patchedFetch(input, init) {
      if (typeof input === 'string' || input instanceof URL) {
        return originalFetch.call(this, normalize(String(input)), init);
      }
      if (input instanceof Request) {
        return originalFetch.call(this, new Request(normalize(input.url), input), init);
      }
      return originalFetch.call(this, input, init);
    };
  }

  const nativeOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function patchedOpen(method, url, ...rest) {
    return nativeOpen.call(this, method, normalize(String(url)), ...rest);
  };

  if (typeof window.EventSource === 'function') {
    const NativeEventSource = window.EventSource;
    window.EventSource = function PatchedEventSource(url, config) {
      return new NativeEventSource(normalize(String(url)), config);
    };
    window.EventSource.prototype = NativeEventSource.prototype;
  }

  if (typeof window.open === 'function') {
    const nativeWindowOpen = window.open;
    window.open = function patchedWindowOpen(url, targetName, features) {
      const nextUrl = typeof url === 'string' ? normalize(url) : url;
      return nativeWindowOpen.call(window, nextUrl, targetName, features);
    };
  }
})();
</script>`

  const withAbsoluteRefs = absolutizeHtmlReferences(html, targetOrigin)
  if (/<head[^>]*>/i.test(withAbsoluteRefs)) {
    return withAbsoluteRefs.replace(/<head([^>]*)>/i, `<head$1>${bridgeScript}`)
  }
  return `${bridgeScript}${withAbsoluteRefs}`
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

async function handleSelectProxyRequest(
  req: IncomingMessage,
  res: ServerResponse,
  target: SelectProxyTarget,
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
          res.end(injectBridgeScript(body, target.targetOrigin))
          resolve()
          return
        }

        upstreamResponse.pipe(res)
        upstreamResponse.on('end', resolve)
      } catch (error) {
        res.statusCode = 502
        res.setHeader('content-type', 'text/plain; charset=utf-8')
        res.end(`Preview select bridge failed: ${error instanceof Error ? error.message : String(error)}`)
        resolve()
      }
    })

    upstreamRequest.on('error', (error) => {
      res.statusCode = 502
      res.setHeader('content-type', 'text/plain; charset=utf-8')
      res.end(`Preview select bridge failed: ${error.message}`)
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
      name: 'supercode-preview-select-bridge',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const requestUrl = req.url || ''
          const target = parseSelectProxyTarget(requestUrl)
          if (!target) {
            next()
            return
          }

          void handleSelectProxyRequest(req, res, target)
        })
      },
    },
  ],
  resolve: {
    alias: [
      // Force `@/` imports to resolve into `src/` even if a real `frontend/@` folder exists.
      { find: /^@\//, replacement: `${path.resolve(__dirname, './src')}/` },
    ],
  },
})
