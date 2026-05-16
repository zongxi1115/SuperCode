import {
  WebPreview,
  WebPreviewBody,
  WebPreviewNavigation,
  WebPreviewNavigationButton,
  WebPreviewUrl,
} from '@/components/ai-elements/web-preview';
import { Button } from '@/components/ui/button';
import { AnimatePresence, motion } from 'motion/react';
import { PanelRightOpen, RefreshCw, ExternalLink, MousePointerClick, X } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';

type WebPreviewPanelProps = {
  isOpen: boolean;
  onToggle: () => void;
  url: string;
  onUrlChange: (url: string) => void;
  onSelectElement?: (html: string, selector: string) => void;
};

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

export function WebPreviewPanel({ isOpen, onToggle, url, onUrlChange, onSelectElement }: WebPreviewPanelProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [isSelectMode, setIsSelectMode] = useState(false);

  const handleRefresh = useCallback(() => {
    if (iframeRef.current) {
      iframeRef.current.src = iframeRef.current.src;
    }
  }, []);

  const handleOpenInNewTab = useCallback(() => {
    if (url) {
      window.open(url, '_blank');
    }
  }, [url]);

  const handleSelectElement = useCallback(() => {
    if (!iframeRef.current?.contentDocument) return;
    const doc = iframeRef.current.contentDocument;
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
        doc.querySelectorAll('.__highlight-hover').forEach((el) => el.classList.remove('__highlight-hover'));
        doc.querySelectorAll('.__highlight-selected').forEach((el) => el.classList.remove('__highlight-selected'));
        cleanup();
      }
    };

    const cleanup = () => {
      style.remove();
      doc.removeEventListener('mouseover', handleMouseOver, true);
      doc.removeEventListener('mouseout', handleMouseOut, true);
      doc.removeEventListener('click', handleClick, true);
      doc.removeEventListener('keydown', handleKeyDown, true);
      setIsSelectMode(false);
    };

    doc.addEventListener('mouseover', handleMouseOver, true);
    doc.addEventListener('mouseout', handleMouseOut, true);
    doc.addEventListener('click', handleClick, true);
    doc.addEventListener('keydown', handleKeyDown, true);
  }, [onSelectElement]);

  return (
    <>
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: '40%', opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
            className="border-l bg-background flex flex-col min-w-0 overflow-hidden"
            style={{ maxWidth: '50%', minWidth: 320 }}
          >
            <WebPreview url={url} onUrlChange={onUrlChange} className="rounded-none border-0">
              <WebPreviewNavigation>
                <WebPreviewNavigationButton tooltip="刷新" onClick={handleRefresh}>
                  <RefreshCw className="w-4 h-4" />
                </WebPreviewNavigationButton>
                <WebPreviewUrl />
                <WebPreviewNavigationButton tooltip="选择元素" onClick={handleSelectElement} disabled={isSelectMode}>
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
            </WebPreview>
          </motion.div>
        )}
      </AnimatePresence>

      {!isOpen && (
        <div className="flex flex-col items-center pt-2 border-l bg-muted/20">
          <Button variant="ghost" size="icon" onClick={onToggle} className="h-8 w-8" title="打开浏览器预览">
            <PanelRightOpen className="w-4 h-4" />
          </Button>
          <div className="mt-1.5 [writing-mode:vertical-lr] text-[10px] text-muted-foreground/60 rotate-180">预览</div>
        </div>
      )}
    </>
  );
}
