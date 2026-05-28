const DEFAULT_BRIDGE_URL = 'http://localhost:3001/api/preview/select-bridge.js';

export function superCodeSelectBridgePlugin(options = {}) {
  const bridgeUrl =
    typeof options.bridgeUrl === 'string' && options.bridgeUrl.trim()
      ? options.bridgeUrl.trim()
      : process.env.SUPERCODE_SELECT_BRIDGE_URL || DEFAULT_BRIDGE_URL;

  return {
    name: 'supercode-select-bridge',
    apply: 'serve',
    transformIndexHtml(html) {
      if (
        options.enabled === false ||
        html.includes('data-supercode-select-bridge') ||
        html.includes(bridgeUrl)
      ) {
        return html;
      }

      return {
        html,
        tags: [
          {
            tag: 'script',
            attrs: {
              src: bridgeUrl,
              defer: true,
              'data-supercode-select-bridge': 'true',
            },
            injectTo: 'head',
          },
        ],
      };
    },
  };
}

export default superCodeSelectBridgePlugin;
