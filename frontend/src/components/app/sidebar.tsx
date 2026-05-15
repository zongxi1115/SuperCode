import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { AnimatePresence, motion } from 'motion/react';
import type { SessionHistoryItem } from '@/lib/app-types';
import { cn } from '@/lib/utils';
import { FileCode, FolderOpen, MessageSquareText, PanelLeftClose, PanelLeftOpen, Plus, Trash2, Wrench } from 'lucide-react';

type SidebarProps = {
  currentSessionId: string | null;
  historyItems: SessionHistoryItem[];
  isHistoryLoading: boolean;
  isCollapsed: boolean;
  selectedWorkspace: string;
  backendMode: 'agent' | 'demo';
  startupError: string | null;
  onNewSession: () => void;
  onSelectHistory: (sessionId: string) => void;
  onDeleteHistory: (sessionId: string) => void;
  onToggle: () => void;
  onSelectOtherProject: () => void;
};

function formatHistoryTime(timestamp: number) {
  const diff = Date.now() - timestamp;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return '刚刚';
  if (diff < hour) return `${Math.floor(diff / minute)}分前`;
  if (diff < day) return `${Math.floor(diff / hour)}时前`;
  return new Date(timestamp).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' });
}

export function Sidebar({
  currentSessionId,
  historyItems,
  isHistoryLoading,
  isCollapsed,
  selectedWorkspace,
  backendMode,
  startupError,
  onNewSession,
  onSelectHistory,
  onDeleteHistory,
  onToggle,
  onSelectOtherProject,
}: SidebarProps) {
  const sidebarWidth = isCollapsed ? 48 : 240;

  return (
    <motion.div
      animate={{ width: sidebarWidth }}
      transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
      className="border-r bg-muted/20 flex flex-col flex-shrink-0 overflow-hidden"
    >
      <div className="flex items-center gap-1 p-2 border-b min-h-[40px]">
        <AnimatePresence mode="wait">
          {!isCollapsed && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="flex-1 flex gap-1 min-w-0"
            >
              <Button variant="default" size="sm" className="flex-1 justify-start gap-1.5 h-7 text-xs" onClick={onNewSession}>
                <Plus className="w-3.5 h-3.5" /> 新建
              </Button>
              <Button variant="outline" size="sm" className="flex-1 justify-start gap-1.5 h-7 text-xs" onClick={onSelectOtherProject}>
                <FolderOpen className="w-3.5 h-3.5" /> 项目
              </Button>
            </motion.div>
          )}
        </AnimatePresence>
        <Button variant="ghost" size="icon" onClick={onToggle} className="shrink-0 h-7 w-7">
          {isCollapsed ? <PanelLeftOpen className="w-3.5 h-3.5" /> : <PanelLeftClose className="w-3.5 h-3.5" />}
        </Button>
      </div>

      <AnimatePresence mode="wait">
        {!isCollapsed && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="flex-1 flex flex-col min-h-0"
          >
            <div className="px-3 pt-2 pb-1">
              <div className="text-[11px] text-muted-foreground truncate" title={selectedWorkspace}>
                {backendMode === 'agent' ? 'Agent' : 'Demo'} · {selectedWorkspace}
              </div>
              {startupError && (
                <div className="mt-1 rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-900">
                  {startupError}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between px-3 py-1">
              <div className="text-[10px] font-semibold tracking-[0.18em] text-muted-foreground/80">HISTORY</div>
              <div className="text-[10px] text-muted-foreground">{historyItems.length}</div>
            </div>

            <ScrollArea className="flex-1 px-1.5 pb-2">
              <div className="space-y-0.5">
                {isHistoryLoading ? (
                  <div className="rounded-lg border border-dashed px-2 py-3 text-[11px] text-muted-foreground">加载中...</div>
                ) : null}

                {!isHistoryLoading && historyItems.length === 0 ? (
                  <div className="rounded-lg border border-dashed px-2 py-3 text-[11px] text-muted-foreground">暂无历史</div>
                ) : null}

                {historyItems.map((item) => {
                  const isActive = item.sessionId === currentSessionId;
                  return (
                    <div
                      key={item.sessionId}
                      className={cn(
                        'group relative rounded-lg border px-2 py-1.5 transition-colors cursor-pointer',
                        isActive
                          ? 'border-primary/30 bg-primary/8'
                          : 'border-transparent hover:border-border hover:bg-muted/30'
                      )}
                      onClick={() => onSelectHistory(item.sessionId)}
                    >
                      <div className="flex items-start gap-1.5">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-xs font-medium leading-4">{item.title}</div>
                          <div className="truncate text-[11px] text-muted-foreground leading-4">{item.preview}</div>
                        </div>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onDeleteHistory(item.sessionId);
                          }}
                          className="shrink-0 rounded p-0.5 text-muted-foreground/50 opacity-0 group-hover:opacity-100 hover:bg-background/70 hover:text-foreground transition-opacity"
                          aria-label={`删除 ${item.title}`}
                          title="删除"
                        >
                          <Trash2 className="size-3" />
                        </button>
                      </div>
                      <div className="flex items-center gap-2 mt-1 text-[10px] text-muted-foreground">
                        <span className="inline-flex items-center gap-0.5">
                          <MessageSquareText className="size-2.5" />
                          {item.messageCount}
                        </span>
                        <span className="inline-flex items-center gap-0.5">
                          <Wrench className="size-2.5" />
                          {item.toolCallCount}
                        </span>
                        <span>{item.mode === 'agent' ? 'Agent' : 'Demo'}</span>
                        <span className="ml-auto">{formatHistoryTime(item.updatedAt)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </motion.div>
        )}
      </AnimatePresence>

      {isCollapsed && (
        <div className="flex-1 flex flex-col items-center pt-3 gap-2">
          <div className="w-6 h-6 rounded bg-muted/80 flex items-center justify-center" title={selectedWorkspace}>
            <FileCode className="w-3.5 h-3.5 text-muted-foreground" />
          </div>
        </div>
      )}
    </motion.div>
  );
}
