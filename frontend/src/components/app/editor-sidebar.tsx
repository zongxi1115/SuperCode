import {
  WebPreview,
  WebPreviewBody,
  WebPreviewConsole,
  WebPreviewNavigation,
  WebPreviewNavigationButton,
  WebPreviewUrl,
} from '@/components/ai-elements/web-preview';
import { Button } from '@/components/ui/button';
import { buildPreviewSelectBridgeSrc, canUsePreviewSelectBridge } from '@/lib/preview-select-bridge';
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
  onSelectElement?: (html: string, selector: string) => void;
};

type PreviewConsoleLog = {
  level: 'log' | 'warn' | 'error';
  message: string;
  timestamp: Date;
};

type PreviewAccessState = 'unknown' | 'same-origin' | 'cross-origin';

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
  const [isSelectBridgeActive, setIsSelectBridgeActive] = useState(false);
  const previewAccessStateRef = useRef<PreviewAccessState>('unknown');
  const crossOriginNoticeShownRef = useRef(false);
  const pendingBridgeSelectionRef = useRef(false);

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

  const canBridgeCurrentPreview = canUsePreviewSelectBridge(url);
  const previewFrameSrc = isSelectBridgeActive
    ? buildPreviewSelectBridgeSrc(url)
    : undefined;

  const setPreviewAccess = useCallback((next: PreviewAccessState) => {
    if (previewAccessStateRef.current === next) {
      return;
    }
    previewAccessStateRef.current = next;
    setPreviewAccessState(next);
  }, []);

  const resetSelectModeState = useCallback(() => {
    setIsSelectMode(false);
    cleanupRef.current = null;
  }, []);

  const markCrossOrigin = useCallback((error?: unknown) => {
    setPreviewAccess('cross-origin');
    resetSelectModeState();

    if (!crossOriginNoticeShownRef.current) {
      const message =
        error instanceof Error
          ? error.message
          : '浏览器同源策略阻止了 iframe DOM 访问';
      pushConsoleLog('warn', `当前预览是跨域页面，无法直接选择元素或捕获控制台输出：${message}`);
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
      setPreviewAccess('unknown');
      resetSelectModeState();
      iframeRef.current.src = previewFrameSrc ?? url;
    }
  }, [previewFrameSrc, resetConsoleLogs, resetSelectModeState, setPreviewAccess, url]);

  const handleOpenInNewTab = useCallback(() => {
    if (url) {
      window.open(url, '_blank');
    }
  }, [url]);

  const cancelSelectMode = useCallback(() => {
    const doc = resolveIframeDocument();
    if (!doc) {
      resetSelectModeState();
      pendingBridgeSelectionRef.current = false;
      setIsSelectBridgeActive(false);
      return;
    }
    doc.querySelectorAll('.__highlight-hover').forEach((el) => el.classList.remove('__highlight-hover'));
    doc.querySelectorAll('.__highlight-selected').forEach((el) => el.classList.remove('__highlight-selected'));
    cleanupRef.current?.();
    cleanupRef.current = null;
    pendingBridgeSelectionRef.current = false;
    setIsSelectBridgeActive(false);
  }, [resetSelectModeState, resolveIframeDocument]);

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

    const handleLoad = () => {
      crossOriginNoticeShownRef.current = false;
      setPreviewAccess('unknown');
      resetSelectModeState();
      resetConsoleLogs();
      attachConsoleCapture();

      if (pendingBridgeSelectionRef.current) {
        pendingBridgeSelectionRef.current = false;
        queueMicrotask(() => {
          const doc = resolveIframeDocument();
          if (!doc) {
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
            onSelectElement?.(outerHtml, selector);
            setIsSelectBridgeActive(false);
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
        });
      }
    };

    iframe.addEventListener('load', handleLoad);
    return () => {
      iframe.removeEventListener('load', handleLoad);
    };
  }, [attachConsoleCapture, cancelSelectMode, isOpen, onSelectElement, resetConsoleLogs, resetSelectModeState, resolveIframeDocument, setPreviewAccess, url]);

  useEffect(() => {
    return () => {
      cleanupRef.current?.();
      cleanupRef.current = null;
      detachConsoleRef.current?.();
      detachConsoleRef.current = null;
    };
  }, []);

  const handleUnavailableSelect = useCallback(() => {
    if (canBridgeCurrentPreview) {
      pendingBridgeSelectionRef.current = true;
      setIsSelectBridgeActive(true);
      pushConsoleLog('log', '正在尝试为本地页面启用桥接选择模式...');
      return;
    }
    markCrossOrigin(new Error('浏览器同源策略阻止访问跨域 iframe 的 DOM'));
  }, [canBridgeCurrentPreview, markCrossOrigin, pushConsoleLog]);

  const handleSelectElement = useCallback(() => {
    const doc = resolveIframeDocument();
    if (!doc) {
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
      onSelectElement?.(outerHtml, selector);
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
  }, [onSelectElement, cancelSelectMode, resolveIframeDocument]);

  const selectTooltip = isSelectMode
    ? '取消选择'
    : previewAccessState === 'cross-origin'
      ? canBridgeCurrentPreview
        ? '跨域本地页面将尝试桥接选择元素'
        : '跨域页面暂不支持直接选择元素'
      : previewAccessState === 'unknown'
        ? '页面加载完成后可选择元素'
        : '选择元素';

  const selectButtonClassName = [
    isSelectMode ? 'bg-primary/15 text-primary' : '',
    !isSelectMode && previewAccessState === 'cross-origin' ? 'opacity-50' : '',
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
                  onClick={
                    isSelectMode
                      ? cancelSelectMode
                      : previewAccessState === 'cross-origin'
                        ? handleUnavailableSelect
                        : handleSelectElement
                  }
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
              <WebPreviewBody ref={iframeRef} className="bg-white" src={previewFrameSrc} />
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
