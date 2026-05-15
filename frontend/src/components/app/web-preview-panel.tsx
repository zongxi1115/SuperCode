import {
  WebPreview,
  WebPreviewBody,
  WebPreviewNavigation,
  WebPreviewNavigationButton,
  WebPreviewUrl,
} from '@/components/ai-elements/web-preview';
import { Button } from '@/components/ui/button';
import { AnimatePresence, motion } from 'motion/react';
import { Globe, PanelRightClose, PanelRightOpen, RefreshCw, X } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';

type WebPreviewPanelProps = {
  isOpen: boolean;
  onToggle: () => void;
};

export function WebPreviewPanel({ isOpen, onToggle }: WebPreviewPanelProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [previewUrl, setPreviewUrl] = useState('http://localhost:5173');

  const handleRefresh = useCallback(() => {
    if (iframeRef.current) {
      iframeRef.current.src = iframeRef.current.src;
    }
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
            <WebPreview defaultUrl={previewUrl} onUrlChange={setPreviewUrl} className="rounded-none border-0">
              <WebPreviewNavigation>
                <WebPreviewNavigationButton tooltip="刷新" onClick={handleRefresh}>
                  <RefreshCw className="w-4 h-4" />
                </WebPreviewNavigationButton>
                <WebPreviewUrl />
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
