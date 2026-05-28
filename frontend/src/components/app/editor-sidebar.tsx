import {
  WebPreview,
  WebPreviewBody,
  WebPreviewConsole,
  WebPreviewNavigation,
  WebPreviewNavigationButton,
  WebPreviewUrl,
} from '@/components/ai-elements/web-preview';
import { Button } from '@/components/ui/button';
import { canUsePreviewSelectBridge } from '@/lib/preview-select-bridge';
import { AnimatePresence, motion } from 'motion/react';
import { ExternalLink, FolderTree, Globe, MousePointerClick, PanelRightClose, RefreshCw, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

type EditorSidebarProps = {
  isOpen: boolean;
  isFileTreeVisible: boolean;
  isFullscreen?: boolean;
  onToggle: () => void;
  onToggleFileTree: () => void;
  url: string;
  onUrlChange: (url: string) => void;
  onSelectElement?: (html: string, selector: string, sourceUrl?: string) => void;
};

type PreviewConsoleLog = {
  level: 'log' | 'warn' | 'error';
  message: string;
  timestamp: Date;
};

type PreviewAccessState = 'unknown' | 'same-origin' | 'cross-origin';
type PreviewSelectBridgeState = 'unknown' | 'ready' | 'selecting' | 'unavailable';

const BRIDGE_READY = 'SC_SELECT_BRIDGE_READY';
const BRIDGE_PING = 'SC_SELECT_BRIDGE_PING';
const BRIDGE_START = 'SC_SELECT_START';
const BRIDGE_CANCEL = 'SC_SELECT_CANCEL';
const BRIDGE_RESULT = 'SC_SELECT_RESULT';
const BRIDGE_ERROR = 'SC_SELECT_ERROR';

function getElementSelector(el: HTMLElement): string {
  const parts: string[] = [];
  let current: HTMLElement | null = el;
  while (current && current.nodeType === 1) {
    let selector = current.tagName.toLowerCase();
    if (current.id) {
      selector += `#${current.id}`;
      parts.unshift(selector);
      break;
    }
    if (current.className && typeof current.className === 'string') {
      const classes = current.className
        .trim()
        .split(/\s+/)
        .filter((c) => c && !c.startsWith('__'));
      if (classes.length) {
        selector += `.${classes.join('.')}`;
      }
    }
    const parent = current.parentElement;
    if (parent) {
      const siblings = Array.from(parent.children).filter(
        (s) => s.tagName === current!.tagName
      );
      if (siblings.length > 1) {
        const index = siblings.indexOf(current) + 1;
        selector += `:nth-of-type(${index})`;
      }
    }
    parts.unshift(selector);
    current = current.parentElement;
  }
  return parts.slice(0, 4).join(' > ');
}

function getPostMessageTargetOrigin(url: string): string {
  try {
    return new URL(url).origin;
  } catch {
    return '*';
  }
}

function isBridgeMessage(value: unknown): value is {
  type: string;
  selector?: unknown;
  html?: unknown;
  message?: unknown;
  sourceUrl?: unknown;
} {
  return typeof value === 'object' && value !== null && 'type' in value;
}

export function EditorSidebar({
  isOpen,
  isFileTreeVisible,
  isFullscreen = false,
  onToggle,
  onToggleFileTree,
  url,
  onUrlChange,
  onSelectElement,
}: EditorSidebarProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [isSelectMode, setIsSelectMode] = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);
  const detachConsoleRef = useRef<(() => void) | null>(null);
  const [consoleLogs, setConsoleLogs] = useState<PreviewConsoleLog[]>([]);
  const [previewAccessState, setPreviewAccessState] = useState<PreviewAccessState>('unknown');
  const [previewSelectBridgeState, setPreviewSelectBridgeState] =
    useState<PreviewSelectBridgeState>('unknown');
  const previewAccessStateRef = useRef<PreviewAccessState>('unknown');
  const previewSelectBridgeStateRef = useRef<PreviewSelectBridgeState>('unknown');
  const crossOriginNoticeShownRef = useRef(false);
  const bridgeUnavailableNoticeShownRef = useRef(false);

  const canBridgeCurrentPreview = canUsePreviewSelectBridge(url);

  const pushConsoleLog = useCallback((level: PreviewConsoleLog['level'], message: string) => {
    setConsoleLogs((prev) => [
      ...prev.slice(-199),
      {
        level,
        message,
        timestamp: new Date(),
      },
    ]);
  }, []);

  const resetConsoleLogs = useCallback(() => {
    setConsoleLogs([]);
  }, []);

  const setPreviewAccess = useCallback((next: PreviewAccessState) => {
    if (previewAccessStateRef.current === next) {
      return;
    }
    previewAccessStateRef.current = next;
    setPreviewAccessState(next);
  }, []);

  const setBridgeState = useCallback((next: PreviewSelectBridgeState) => {
    if (previewSelectBridgeStateRef.current === next) {
      return;
    }
    previewSelectBridgeStateRef.current = next;
    setPreviewSelectBridgeState(next);
  }, []);

  const resetSelectModeState = useCallback(() => {
    setIsSelectMode(false);
    cleanupRef.current = null;
  }, []);

  const postBridgeMessage = useCallback((type: string) => {
    const iframeWindow = iframeRef.current?.contentWindow;
    if (!iframeWindow) {
      return;
    }
    iframeWindow.postMessage({ type }, getPostMessageTargetOrigin(url));
  }, [url]);

  const markCrossOrigin = useCallback((error?: unknown) => {
    setPreviewAccess('cross-origin');
    resetSelectModeState();

    if (!crossOriginNoticeShownRef.current) {
      const message =
        error instanceof Error
          ? error.message
          : '浏览器同源策略阻止了 iframe DOM 访问';
      pushConsoleLog('warn', `当前预览是跨域页面，无法直接捕获控制台输出：${message}`);
      crossOriginNoticeShownRef.current = true;
    }

    return null;
  }, [pushConsoleLog, resetSelectModeState, setPreviewAccess]);

  const resolveIframeDocument = useCallback(() => {
    const iframe = iframeRef.current;
    if (!iframe) {
      return null;
    }

    try {
      const doc = iframe.contentWindow?.document;
      if (!doc) {
        return null;
      }

      // Touch the DOM so cross-origin access fails here instead of later in event setup.
      void doc.documentElement;
      setPreviewAccess('same-origin');
      crossOriginNoticeShownRef.current = false;
      return doc;
    } catch (error) {
      return markCrossOrigin(error);
    }
  }, [markCrossOrigin, setPreviewAccess]);

  const handleRefresh = useCallback(() => {
    if (iframeRef.current) {
      resetConsoleLogs();
      crossOriginNoticeShownRef.current = false;
      bridgeUnavailableNoticeShownRef.current = false;
      setPreviewAccess('unknown');
      setBridgeState('unknown');
      resetSelectModeState();
      iframeRef.current.src = url;
    }
  }, [resetConsoleLogs, resetSelectModeState, setBridgeState, setPreviewAccess, url]);

  const handleOpenInNewTab = useCallback(() => {
    if (url) {
      window.open(url, '_blank');
    }
  }, [url]);

  const cancelSelectMode = useCallback(() => {
    if (previewSelectBridgeStateRef.current === 'selecting') {
      postBridgeMessage(BRIDGE_CANCEL);
      setBridgeState('ready');
      resetSelectModeState();
      return;
    }

    const doc = resolveIframeDocument();
    if (!doc) {
      resetSelectModeState();
      return;
    }
    doc.querySelectorAll('.__highlight-hover').forEach((el) => el.classList.remove('__highlight-hover'));
    doc.querySelectorAll('.__highlight-selected').forEach((el) => el.classList.remove('__highlight-selected'));
    cleanupRef.current?.();
    cleanupRef.current = null;
  }, [postBridgeMessage, resetSelectModeState, resolveIframeDocument, setBridgeState]);

  const attachConsoleCapture = useCallback(() => {
    detachConsoleRef.current?.();
    detachConsoleRef.current = null;

    const iframe = iframeRef.current;
    if (!iframe) {
      return;
    }

    const doc = resolveIframeDocument();
    if (!doc) {
      return;
    }

    try {
      const win = iframe.contentWindow;
      if (!win) {
        return;
      }

      void doc.head;
      const originalConsole = {
        log: win.console.log,
        warn: win.console.warn,
        error: win.console.error,
      };

      const stringifyArgs = (args: unknown[]) =>
        args
          .map((arg) => {
            if (typeof arg === 'string') return arg;
            try {
              return JSON.stringify(arg);
            } catch {
              return String(arg);
            }
          })
          .join(' ');

      win.console.log = (...args: unknown[]) => {
        pushConsoleLog('log', stringifyArgs(args));
        originalConsole.log.apply(win.console, args);
      };
      win.console.warn = (...args: unknown[]) => {
        pushConsoleLog('warn', stringifyArgs(args));
        originalConsole.warn.apply(win.console, args);
      };
      win.console.error = (...args: unknown[]) => {
        pushConsoleLog('error', stringifyArgs(args));
        originalConsole.error.apply(win.console, args);
      };

      const handleError = (event: ErrorEvent) => {
        pushConsoleLog('error', event.message || 'Unknown error');
      };
      const handleRejection = (event: PromiseRejectionEvent) => {
        const reason = event.reason;
        const message =
          typeof reason === 'string'
            ? reason
            : reason instanceof Error
              ? reason.message
              : (() => {
                  try {
                    return JSON.stringify(reason);
                  } catch {
                    return String(reason);
                  }
                })();
        pushConsoleLog('error', `Unhandled rejection: ${message}`);
      };

      win.addEventListener('error', handleError);
      win.addEventListener('unhandledrejection', handleRejection);

      detachConsoleRef.current = () => {
        win.console.log = originalConsole.log;
        win.console.warn = originalConsole.warn;
        win.console.error = originalConsole.error;
        win.removeEventListener('error', handleError);
        win.removeEventListener('unhandledrejection', handleRejection);
      };
    } catch (error) {
      markCrossOrigin(error);
    }
  }, [markCrossOrigin, pushConsoleLog, resolveIframeDocument]);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe || !isOpen) {
      return;
    }

    let unavailableTimer: number | undefined;

    const handleLoad = () => {
      crossOriginNoticeShownRef.current = false;
      bridgeUnavailableNoticeShownRef.current = false;
      setPreviewAccess('unknown');
      setBridgeState('unknown');
      resetSelectModeState();
      resetConsoleLogs();
      attachConsoleCapture();

      if (canBridgeCurrentPreview) {
        window.clearTimeout(unavailableTimer);
        window.setTimeout(() => postBridgeMessage(BRIDGE_PING), 0);
        unavailableTimer = window.setTimeout(() => {
          if (
            previewAccessStateRef.current === 'cross-origin' &&
            previewSelectBridgeStateRef.current === 'unknown'
          ) {
            setBridgeState('unavailable');
          }
        }, 800);
      }
    };

    iframe.addEventListener('load', handleLoad);
    return () => {
      iframe.removeEventListener('load', handleLoad);
      window.clearTimeout(unavailableTimer);
    };
  }, [
    attachConsoleCapture,
    canBridgeCurrentPreview,
    isOpen,
    postBridgeMessage,
    resetConsoleLogs,
    resetSelectModeState,
    setBridgeState,
    setPreviewAccess,
  ]);

  useEffect(() => {
    const handleBridgeMessage = (event: MessageEvent<unknown>) => {
      const iframeWindow = iframeRef.current?.contentWindow;
      if (!iframeWindow || event.source !== iframeWindow || !isBridgeMessage(event.data)) {
        return;
      }

      const sourceUrl = typeof event.data.sourceUrl === 'string' ? event.data.sourceUrl : url;
      if (!canUsePreviewSelectBridge(sourceUrl)) {
        return;
      }

      if (event.data.type === BRIDGE_READY) {
        setPreviewAccess('cross-origin');
        setBridgeState('ready');
        crossOriginNoticeShownRef.current = true;
        bridgeUnavailableNoticeShownRef.current = false;
        return;
      }

      if (event.data.type === BRIDGE_RESULT) {
        const selector = typeof event.data.selector === 'string' ? event.data.selector : '';
        const html = typeof event.data.html === 'string' ? event.data.html : '';
        setBridgeState('ready');
        resetSelectModeState();
        if (selector && html) {
          onSelectElement?.(html, selector, sourceUrl);
        }
        return;
      }

      if (event.data.type === BRIDGE_ERROR) {
        const message = typeof event.data.message === 'string' ? event.data.message : '选择元素失败';
        pushConsoleLog('error', `跨域选择失败：${message}`);
        setBridgeState('ready');
        resetSelectModeState();
        return;
      }

      if (event.data.type === BRIDGE_CANCEL) {
        setBridgeState('ready');
        resetSelectModeState();
      }
    };

    window.addEventListener('message', handleBridgeMessage);
    return () => {
      window.removeEventListener('message', handleBridgeMessage);
    };
  }, [onSelectElement, pushConsoleLog, resetSelectModeState, setBridgeState, setPreviewAccess, url]);

  useEffect(() => {
    return () => {
      if (previewSelectBridgeStateRef.current === 'selecting') {
        postBridgeMessage(BRIDGE_CANCEL);
      }
      cleanupRef.current?.();
      cleanupRef.current = null;
      detachConsoleRef.current?.();
      detachConsoleRef.current = null;
    };
  }, [postBridgeMessage]);

  const handleBridgeSelectElement = useCallback(() => {
    if (!canBridgeCurrentPreview) {
      markCrossOrigin(new Error('跨域页面暂不支持直接选择元素'));
      return;
    }

    if (previewSelectBridgeStateRef.current !== 'ready') {
      if (!bridgeUnavailableNoticeShownRef.current) {
        pushConsoleLog(
          'warn',
          '需要在目标 Vite dev 项目接入 scripts/supercode-vite-select-bridge-plugin.mjs，或手动引入 select-bridge.js 后才能跨域选择元素。'
        );
        bridgeUnavailableNoticeShownRef.current = true;
      }
      setBridgeState('unavailable');
      return;
    }

    postBridgeMessage(BRIDGE_START);
    setBridgeState('selecting');
    setIsSelectMode(true);
  }, [canBridgeCurrentPreview, markCrossOrigin, postBridgeMessage, pushConsoleLog, setBridgeState]);

  const handleSelectElement = useCallback(() => {
    const doc = previewAccessStateRef.current === 'cross-origin' ? null : resolveIframeDocument();
    if (!doc) {
      handleBridgeSelectElement();
      return;
    }
    setIsSelectMode(true);

    const style = doc.createElement('style');
    style.setAttribute('data-selector-mode', 'true');
    style.textContent = `
      * { cursor: crosshair !important; }
      .__highlight-hover { outline: 2px dashed #3b82f6 !important; outline-offset: 2px !important; background-color: rgba(59, 130, 246, 0.1) !important; }
      .__highlight-selected { outline: 2px solid #3b82f6 !important; outline-offset: 2px !important; background-color: rgba(59, 130, 246, 0.15) !important; }
    `;
    doc.head.appendChild(style);

    const handleMouseOver = (e: MouseEvent) => {
      e.stopPropagation();
      const target = e.target as HTMLElement;
      if (target === doc.body || target === doc.documentElement) return;
      doc.querySelectorAll('.__highlight-hover').forEach((el) => el.classList.remove('__highlight-hover'));
      target.classList.add('__highlight-hover');
    };

    const handleMouseOut = (e: MouseEvent) => {
      (e.target as HTMLElement).classList.remove('__highlight-hover');
    };

    const handleClick = (e: MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const target = e.target as HTMLElement;
      if (target === doc.body || target === doc.documentElement) return;

      doc.querySelectorAll('.__highlight-selected').forEach((el) => el.classList.remove('__highlight-selected'));
      doc.querySelectorAll('.__highlight-hover').forEach((el) => el.classList.remove('__highlight-hover'));
      target.classList.add('__highlight-selected');

      const outerHtml = target.outerHTML;
      const selector = getElementSelector(target);

      cleanup();
      onSelectElement?.(outerHtml, selector, url);
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        cancelSelectMode();
      }
    };

    const cleanup = () => {
      style.remove();
      doc.removeEventListener('mouseover', handleMouseOver, true);
      doc.removeEventListener('mouseout', handleMouseOut, true);
      doc.removeEventListener('click', handleClick, true);
      doc.removeEventListener('keydown', handleKeyDown, true);
      setIsSelectMode(false);
      cleanupRef.current = null;
    };

    cleanupRef.current = cleanup;

    doc.addEventListener('mouseover', handleMouseOver, true);
    doc.addEventListener('mouseout', handleMouseOut, true);
    doc.addEventListener('click', handleClick, true);
    doc.addEventListener('keydown', handleKeyDown, true);
  }, [cancelSelectMode, handleBridgeSelectElement, onSelectElement, resolveIframeDocument, url]);

  const selectTooltip = isSelectMode
    ? '取消选择'
    : previewAccessState === 'cross-origin'
      ? previewSelectBridgeState === 'ready'
        ? '跨域本地页面可通过 bridge 选择元素'
        : previewSelectBridgeState === 'unavailable'
          ? '目标页面需要引入 SuperCode 选择脚本'
          : canBridgeCurrentPreview
            ? '等待目标页面选择 bridge 握手'
            : '跨域页面暂不支持直接选择元素'
      : previewAccessState === 'unknown'
        ? '页面加载完成后可选择元素'
        : '选择元素';

  const selectButtonClassName = [
    isSelectMode ? 'bg-primary/15 text-primary' : '',
    !isSelectMode && previewAccessState === 'cross-origin' && previewSelectBridgeState !== 'ready' ? 'opacity-70' : '',
  ].filter(Boolean).join(' ');
  return (
    <>
      <AnimatePresence initial={false}>
        {isOpen ? (
          <motion.div
            initial={isFullscreen ? { opacity: 0 } : { width: 0, opacity: 0, x: 18 }}
            animate={isFullscreen ? { opacity: 1 } : { width: 420, opacity: 1, x: 0 }}
            exit={isFullscreen ? { opacity: 0 } : { width: 0, opacity: 0, x: 18 }}
            transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
            className={`bg-background flex flex-col min-w-0 overflow-hidden ${isFullscreen ? 'h-full w-full' : 'border-l'}`}
          >
            <WebPreview url={url} onUrlChange={onUrlChange} className="rounded-none border-0">
              <WebPreviewNavigation>
                <WebPreviewNavigationButton
                  tooltip={isFileTreeVisible ? '收起文件树' : '展开文件树'}
                  onClick={onToggleFileTree}
                  className={isFileTreeVisible ? 'bg-primary/15 text-primary' : ''}
                >
                  <FolderTree className="w-4 h-4" />
                </WebPreviewNavigationButton>
                <WebPreviewNavigationButton tooltip="收起预览" onClick={onToggle}>
                  <PanelRightClose className="w-4 h-4" />
                </WebPreviewNavigationButton>
                <WebPreviewNavigationButton tooltip="刷新" onClick={handleRefresh}>
                  <RefreshCw className="w-4 h-4" />
                </WebPreviewNavigationButton>
                <WebPreviewUrl />
                <WebPreviewNavigationButton
                  tooltip={selectTooltip}
                  onClick={isSelectMode ? cancelSelectMode : handleSelectElement}
                  className={selectButtonClassName}
                >
                  <MousePointerClick className="w-4 h-4" />
                </WebPreviewNavigationButton>
                <WebPreviewNavigationButton tooltip="在新标签页打开" onClick={handleOpenInNewTab}>
                  <ExternalLink className="w-4 h-4" />
                </WebPreviewNavigationButton>
                <WebPreviewNavigationButton tooltip="关闭预览" onClick={onToggle}>
                  <X className="w-4 h-4" />
                </WebPreviewNavigationButton>
              </WebPreviewNavigation>
              <WebPreviewBody ref={iframeRef} className="bg-white" />
              <WebPreviewConsole logs={consoleLogs} />
            </WebPreview>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {!isOpen ? (
        <div className="flex w-12 shrink-0 flex-col items-center gap-2 border-l bg-muted/20 py-3">
          <Button
            variant={isFileTreeVisible ? 'secondary' : 'ghost'}
            size="icon"
            onClick={onToggleFileTree}
            className="h-8 w-8 rounded-lg"
            title={isFileTreeVisible ? '收起文件树' : '展开文件树'}
          >
            <FolderTree className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggle}
            className="h-8 w-8 rounded-lg"
            title="打开浏览器预览"
          >
            <Globe className="h-4 w-4" />
          </Button>
          <div className="[writing-mode:vertical-lr] rotate-180 text-[10px] text-muted-foreground/70">
            工具
          </div>
        </div>
      ) : null}
    </>
  );
}
