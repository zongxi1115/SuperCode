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
  return (
    <motion.div
      animate={{ width: isCollapsed ? 48 : 'auto' }}
      transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
      className={cn(
        'border-r bg-muted/20 flex flex-col flex-shrink-0 overflow-hidden',
        !isCollapsed && 'w-[20%] min-w-[220px] max-w-[360px]'
      )}
    >
      <div className="flex items-center gap-1 p-2 border-b min-h-[44px]">
        <AnimatePresence mode="wait">
          {!isCollapsed && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="flex-1 flex gap-1.5 min-w-0"
            >
              <Button variant="default" size="sm" className="flex-1 justify-start gap-1.5 h-8 text-xs" onClick={onNewSession}>
                <Plus className="w-3.5 h-3.5" /> 新建会话
              </Button>
              <Button variant="outline" size="sm" className="flex-1 justify-start gap-1.5 h-8 text-xs" onClick={onSelectOtherProject}>
                <FolderOpen className="w-3.5 h-3.5" /> 打开项目
              </Button>
            </motion.div>
          )}
        </AnimatePresence>
        <Button variant="ghost" size="icon" onClick={onToggle} className="shrink-0 h-8 w-8">
          {isCollapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
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
            <div className="px-3 pt-2.5 pb-1.5">
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground truncate" title={selectedWorkspace}>
                <FileCode className="w-3 h-3 shrink-0" />
                <span className="truncate">{backendMode === 'agent' ? 'Agent' : 'Demo'} · {selectedWorkspace}</span>
              </div>
              {startupError && (
                <div className="mt-1.5 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-[10px] text-amber-900">
                  {startupError}
                </div>
              )}
            </div>

            <div className="mx-3 flex items-center justify-between py-1.5 border-b border-border/50">
              <span className="text-[11px] font-medium text-muted-foreground">历史记录</span>
              <span className="text-[10px] text-muted-foreground/60 tabular-nums">{historyItems.length}</span>
            </div>

            <ScrollArea className="flex-1 px-2 py-1">
              <div className="space-y-0.5">
                {isHistoryLoading ? (
                  <div className="rounded-lg border border-dashed px-3 py-4 text-xs text-muted-foreground text-center">加载中...</div>
                ) : null}

                {!isHistoryLoading && historyItems.length === 0 ? (
                  <div className="rounded-lg border border-dashed px-3 py-4 text-xs text-muted-foreground text-center">暂无历史记录</div>
                ) : null}

                {historyItems.map((item) => {
                  const isActive = item.sessionId === currentSessionId;
                  return (
                    <div
                      key={item.sessionId}
                      className={cn(
                        'group relative rounded-md px-2.5 py-2 transition-colors cursor-pointer',
                        isActive
                          ? 'bg-primary/8 border border-primary/20'
                          : 'border border-transparent hover:bg-muted/40 hover:border-border/60'
                      )}
                      onClick={() => onSelectHistory(item.sessionId)}
                    >
                      <div className="flex items-center gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-xs font-medium leading-5">{item.title}</div>
                          <div className="line-clamp-2 break-words text-[11px] text-muted-foreground/70 leading-4 mt-0.5">{item.preview}</div>
                        </div>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onDeleteHistory(item.sessionId);
                          }}
                          className="shrink-0 self-center rounded-md p-1.5 text-muted-foreground/40 hover:bg-destructive/10 hover:text-destructive transition-colors"
                          aria-label={`删除 ${item.title}`}
                          title="删除"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <div className="flex items-center gap-2 mt-1.5 text-[10px] text-muted-foreground/60">
                        <span className="inline-flex items-center gap-0.5">
                          <MessageSquareText className="size-2.5" />
                          {item.messageCount}
                        </span>
                        <span className="inline-flex items-center gap-0.5">
                          <Wrench className="size-2.5" />
                          {item.toolCallCount}
                        </span>
                        <span className="text-[9px] px-1 py-px rounded bg-muted/60">{item.mode === 'agent' ? 'Agent' : 'Demo'}</span>
                        <span className="ml-auto tabular-nums">{formatHistoryTime(item.updatedAt)}</span>
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
          <div className="w-7 h-7 rounded-md bg-muted/80 flex items-center justify-center" title={selectedWorkspace}>
            <FileCode className="w-3.5 h-3.5 text-muted-foreground" />
          </div>
        </div>
      )}
    </motion.div>
  );
}
