import { Button } from '@/components/ui/button';
import { GitPanel } from '@/components/app/git-panel';
import { ScrollArea } from '@/components/ui/scroll-area';
import { AnimatePresence, motion } from 'motion/react';
import type { PluginSummary, SessionHistoryItem } from '@/lib/app-types';
import { cn } from '@/lib/utils';
import { ChevronRight, FileCode, FolderOpen, GitBranch, PanelLeftClose, PanelLeftOpen, Plus, Trash2, LayoutDashboard } from 'lucide-react';
import { useMemo, useState } from 'react';

type SidebarProps = {
  currentSessionId: string | null;
  historyItems: SessionHistoryItem[];
  isHistoryLoading: boolean;
  isCollapsed: boolean;
  isResizing: boolean;
  selectedWorkspace: string;
  selectedBaseWorkspace: string;
  backendMode: 'agent' | 'demo';
  startupError: string | null;
  width: number;
  isGitPanelOpen: boolean;
  onGitPanelToggle: () => void;
  onNewSession: () => void;
  onSelectHistory: (sessionId: string) => void;
  onDeleteHistory: (sessionId: string) => void;
  onToggle: () => void;
  onSelectOtherProject: () => void;
  activePlugin: string | null;
  plugins: PluginSummary[];
  onActivePluginChange: (pluginId: string | null) => void;
};

function getFolderName(path: string): string {
  const normalized = path.replace(/\\/g, '/');
  const segments = normalized.split('/').filter(Boolean);
  return segments[segments.length - 1] || path;
}

type ProjectGroup = {
  workspace: string;
  name: string;
  items: SessionHistoryItem[];
};

export function Sidebar({
  currentSessionId,
  historyItems,
  isHistoryLoading,
  isCollapsed,
  isResizing,
  selectedWorkspace,
  selectedBaseWorkspace,
  backendMode,
  startupError,
  isGitPanelOpen,
  onGitPanelToggle,
  onNewSession,
  onSelectHistory,
  onDeleteHistory,
  onToggle,
  onSelectOtherProject,
  width,
  activePlugin,
  plugins,
  onActivePluginChange,
}: SidebarProps) {
  const [collapsedProjects, setCollapsedProjects] = useState<Set<string>>(new Set());

  const projectGroups = useMemo<ProjectGroup[]>(() => {
    const map = new Map<string, SessionHistoryItem[]>();
    for (const item of historyItems) {
      const ws = item.baseWorkspace || item.workspace || '未知项目';
      if (!map.has(ws)) map.set(ws, []);
      map.get(ws)!.push(item);
    }
    const groups: ProjectGroup[] = [];
    const currentWs = selectedBaseWorkspace || selectedWorkspace;
    if (map.has(currentWs)) {
      groups.push({ workspace: currentWs, name: getFolderName(currentWs), items: map.get(currentWs)! });
      map.delete(currentWs);
    }
    for (const [ws, items] of map) {
      groups.push({ workspace: ws, name: getFolderName(ws), items });
    }
    return groups;
  }, [historyItems, selectedBaseWorkspace, selectedWorkspace]);

  const toggleProjectCollapse = (workspace: string) => {
    setCollapsedProjects((prev) => {
      const next = new Set(prev);
      if (next.has(workspace)) next.delete(workspace);
      else next.add(workspace);
      return next;
    });
  };

  return (
    <div
      style={{
        width: isCollapsed ? 48 : width,
        transition: isResizing ? 'none' : 'width 0.25s cubic-bezier(0.25, 0.1, 0.25, 1)',
      }}
      className={cn(
        'border-r bg-muted/20 flex flex-col flex-shrink-0 overflow-hidden',
        !isCollapsed && `min-w-[220px] max-w-[480px]`
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
              <Button variant="default" size="sm" className="min-w-0 flex-1 justify-start gap-1.5 h-8 text-xs" onClick={onNewSession}>
                <Plus className="w-3.5 h-3.5" /> 新建会话
              </Button>
              <Button variant="outline" size="sm" className="min-w-0 flex-1 justify-start gap-1.5 h-8 text-xs" onClick={onSelectOtherProject}>
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

            <ScrollArea className="flex-1 px-2 py-1">
              <div className="space-y-1">
                {/* 插件入口 */}
                {(plugins.length > 0 ? plugins : [{ id: 'kanban', name: '看板', description: '工作区级任务看板', icon: 'layout-dashboard', navSlot: 'sidebar', enabled: true }]).length > 0 ? (
                  <div className="space-y-0.5 mb-4">
                    <div className="px-2 py-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                      插件
                    </div>
                    {(plugins.length > 0 ? plugins : [{ id: 'kanban', name: '看板', description: '工作区级任务看板', icon: 'layout-dashboard', navSlot: 'sidebar', enabled: true }])
                      .filter((plugin) => plugin.enabled && plugin.navSlot === 'sidebar')
                      .map((plugin) => (
                        <button
                          key={plugin.id}
                          type="button"
                          onClick={() => onActivePluginChange(activePlugin === plugin.id ? null : plugin.id)}
                          className={cn(
                            'flex items-center gap-2 w-full px-2 py-1.5 rounded-md text-xs font-medium transition-colors',
                            activePlugin === plugin.id ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:text-foreground hover:bg-muted/40'
                          )}
                          title={plugin.description}
                        >
                          <LayoutDashboard className="w-3.5 h-3.5 shrink-0" />
                          <span className="flex-1 text-left">{plugin.id === 'kanban' ? '看板' : plugin.name}</span>
                        </button>
                      ))}
                  </div>
                ) : null}

                <div className="px-2 py-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider border-t pt-3">
                  会话历史
                </div>

                {isHistoryLoading ? (
                  <div className="rounded-lg border border-dashed px-3 py-4 text-xs text-muted-foreground text-center">加载中...</div>
                ) : null}

                {!isHistoryLoading && historyItems.length === 0 ? (
                  <div className="rounded-lg border border-dashed px-3 py-4 text-xs text-muted-foreground text-center">暂无历史记录</div>
                ) : null}

                {projectGroups.map((group) => {
                  const isCollapsedGroup = collapsedProjects.has(group.workspace);
                  const isCurrentProject = group.workspace === selectedWorkspace;
                  return (
                    <div key={group.workspace} className="space-y-0.5">
                      <button
                        type="button"
                        onClick={() => toggleProjectCollapse(group.workspace)}
                        className={cn(
                          'flex items-center gap-1.5 w-full px-2 py-1.5 rounded-md text-xs font-medium transition-colors',
                          isCurrentProject ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
                          'hover:bg-muted/40'
                        )}
                        title={group.workspace}
                      >
                        <motion.span
                          animate={{ rotate: isCollapsedGroup ? 0 : 90 }}
                          transition={{ duration: 0.15 }}
                          className="inline-flex shrink-0"
                        >
                          <ChevronRight className="w-3 h-3" />
                        </motion.span>
                        <FolderOpen className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                        <span className="truncate flex-1 text-left">{group.name}</span>
                        <span className="text-[10px] text-muted-foreground/50 tabular-nums shrink-0">{group.items.length}</span>
                      </button>

                      <AnimatePresence initial={false}>
                        {!isCollapsedGroup && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.15 }}
                            className="overflow-hidden"
                          >
                            <AnimatePresence mode="popLayout" initial={false}>
                              {group.items.map((item) => {
                                const isActive = item.sessionId === currentSessionId;
                                const isWorktree = item.executionMode === 'worktree';
                                return (
                                  <motion.div
                                    key={item.sessionId}
                                    layout
                                    layoutAnimation="to-zero"
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    exit={{ opacity: 0, height: 0, marginBottom: 0, paddingTop: 0, paddingBottom: 0 }}
                                    transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
                                    className={cn(
                                      'group flex items-center gap-1 rounded-md px-2 py-1.5 transition-colors cursor-pointer',
                                      isActive
                                        ? 'bg-primary/8 border border-primary/20'
                                        : 'border border-transparent hover:bg-muted/40 hover:border-border/60'
                                    )}
                                    onClick={() => onSelectHistory(item.sessionId)}
                                  >
                                    <span className="min-w-0 flex-1 break-all text-left text-xs leading-snug">
                                      <span>{item.title}</span>
                                      {isWorktree ? (
                                        <span className="ml-1 inline-flex items-center rounded border border-primary/20 bg-primary/10 px-1 text-[10px] text-primary">
                                          Worktree{item.worktreeBranch ? ` · ${item.worktreeBranch.replace('supercode/session-', '')}` : ''}
                                        </span>
                                      ) : null}
                                    </span>
                                    <button
                                      type="button"
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        onDeleteHistory(item.sessionId);
                                      }}
                                      className="shrink-0 rounded-md p-1 text-muted-foreground/30 hover:bg-destructive/10 hover:text-destructive transition-colors opacity-0 group-hover:opacity-100"
                                      aria-label={`删除 ${item.title}`}
                                      title="删除"
                                    >
                                      <Trash2 className="w-3 h-3" />
                                    </button>
                                  </motion.div>
                                );
                              })}
                            </AnimatePresence>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>

            <div className="border-t">
              <button
                type="button"
                onClick={onGitPanelToggle}
                className="flex items-center gap-2 w-full px-3 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
              >
                <GitBranch className="size-3.5 shrink-0" />
                <span className="flex-1 text-left">Git</span>
                <motion.span
                  animate={{ rotate: isGitPanelOpen ? 180 : 0 }}
                  transition={{ duration: 0.2 }}
                >
                  ▾
                </motion.span>
              </button>
              <AnimatePresence>
                {isGitPanelOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 320, opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden border-t"
                  >
                    <GitPanel sessionId={currentSessionId} />
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {isCollapsed && (
        <div className="flex-1 flex flex-col items-center pt-3 gap-2">
          <button
            type="button"
            onClick={onNewSession}
            className="w-7 h-7 rounded-md bg-primary/10 flex items-center justify-center hover:bg-primary/20 transition-colors"
            title="新建会话"
          >
            <Plus className="w-3.5 h-3.5 text-primary" />
          </button>
          <div className="w-7 h-7 rounded-md bg-muted/80 flex items-center justify-center" title={selectedWorkspace}>
            <FileCode className="w-3.5 h-3.5 text-muted-foreground" />
          </div>
          <button
            type="button"
            onClick={onGitPanelToggle}
            className="w-7 h-7 rounded-md bg-muted/80 flex items-center justify-center hover:bg-muted transition-colors"
            title="Git"
          >
            <GitBranch className="w-3.5 h-3.5 text-muted-foreground" />
          </button>
        </div>
      )}
    </div>
  );
}
