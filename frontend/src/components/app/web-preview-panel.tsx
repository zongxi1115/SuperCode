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
import { useCallback, useRef } from 'react';

type WebPreviewPanelProps = {
  isOpen: boolean;
  onToggle: () => void;
  url: string;
  onUrlChange: (url: string) => void;
};

export function WebPreviewPanel({ isOpen, onToggle, url, onUrlChange }: WebPreviewPanelProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);

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
    const style = doc.createElement('style');
    style.textContent = `
      * { cursor: crosshair !important; }
      .__highlight-selected { outline: 2px solid #3b82f6 !important; outline-offset: 2px !important; }
    `;
    doc.head.appendChild(style);

    const handleClick = (e: MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      doc.querySelectorAll('.__highlight-selected').forEach((el) => el.classList.remove('__highlight-selected'));
      (e.target as HTMLElement).classList.add('__highlight-selected');
      style.remove();
      doc.removeEventListener('click', handleClick, true);
    };

    doc.addEventListener('click', handleClick, true);
  }, []);

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
                <WebPreviewNavigationButton tooltip="选择元素" onClick={handleSelectElement}>
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
