import { GitPanel } from '@/components/app/git-panel';
import { ScrollArea } from '@/components/ui/scroll-area';
import { AnimatePresence, motion } from 'motion/react';
import type { PluginSummary, SessionHistoryItem } from '@/lib/app-types';
import { cn } from '@/lib/utils';
import {
  ChevronRight,
  Folder,
  FolderOpen,
  GitBranch,
  LayoutDashboard,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Trash2,
  X,
  FileText,
  SquarePen,
} from 'lucide-react';
import { useMemo, useState } from 'react';

type SidebarProps = {
  currentSessionId: string | null;
  historyItems: SessionHistoryItem[];
  isHistoryLoading: boolean;
  hasMoreHistory: boolean;
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
  onLoadMoreHistory: () => void;
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

const fallbackPlugins: PluginSummary[] = [
  {
    id: 'kanban',
    name: '看板',
    description: '工作区任务看板',
    icon: 'layout-dashboard',
    navSlot: 'sidebar',
    enabled: true,
  },
];

function PluginIcon({ id }: { id: string }) {
  if (id === 'project-docs') {
    return <FileText className="w-4 h-4 shrink-0 text-muted-foreground/80" />;
  }
  return <LayoutDashboard className="w-4 h-4 shrink-0 text-muted-foreground/80" />;
}

export function Sidebar({
  currentSessionId,
  historyItems,
  isHistoryLoading,
  hasMoreHistory,
  isCollapsed,
  isResizing,
  selectedWorkspace,
  selectedBaseWorkspace,
  backendMode,
  isGitPanelOpen,
  onGitPanelToggle,
  onNewSession,
  onSelectHistory,
  onDeleteHistory,
  onLoadMoreHistory,
  onToggle,
  onSelectOtherProject,
  width,
  activePlugin,
  plugins,
  onActivePluginChange,
}: SidebarProps) {
  const [collapsedProjects, setCollapsedProjects] = useState<Set<string>>(new Set());
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const currentProjectName = useMemo(() => {
    const ws = selectedBaseWorkspace || selectedWorkspace;
    return getFolderName(ws) || 'SuperCode';
  }, [selectedBaseWorkspace, selectedWorkspace]);

  const initials = useMemo(() => {
    const clean = currentProjectName.replace(/[^a-zA-Z0-9]/g, '');
    return (clean.slice(0, 3) || 'ZX').toUpperCase();
  }, [currentProjectName]);

  const filteredHistory = useMemo(() => {
    if (!searchQuery.trim()) return historyItems;
    const query = searchQuery.toLowerCase().trim();
    return historyItems.filter((i) => i.title.toLowerCase().includes(query));
  }, [historyItems, searchQuery]);

  const projectGroups = useMemo<ProjectGroup[]>(() => {
    const map = new Map<string, SessionHistoryItem[]>();
    for (const item of filteredHistory) {
      const ws = item.baseWorkspace || item.workspace || '默认项目';
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
  }, [filteredHistory, selectedBaseWorkspace, selectedWorkspace]);

  const toggleProjectCollapse = (workspace: string) => {
    setCollapsedProjects((prev) => {
      const next = new Set(prev);
      if (next.has(workspace)) next.delete(workspace);
      else next.add(workspace);
      return next;
    });
  };

  const activePluginsList = (plugins.length > 0 ? plugins : fallbackPlugins).filter(
    (plugin) => plugin.enabled && plugin.navSlot === 'sidebar'
  );

  return (
    <aside
      style={{
        width: isCollapsed ? 52 : width,
        transition: isResizing ? 'none' : 'width 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
      }}
      className={cn(
        'relative flex flex-col flex-shrink-0 h-full border-r bg-[#f9f9f9] dark:bg-[#171717] text-foreground select-none',
        'border-black/[0.08] dark:border-white/[0.08]',
        !isCollapsed && 'min-w-[240px] max-w-[480px]'
      )}
    >
      {/* 展开态：ChatGPT 布局 */}
      {!isCollapsed && (
        <div className="flex flex-col h-full w-full overflow-hidden">
          {/* 顶部 Header：Brand 品牌名 + 搜索 + 折叠按钮 */}
          <div className="flex items-center justify-between px-3.5 pt-3 pb-2">
            <span className="text-[15px] font-semibold text-foreground tracking-tight select-none">
              SuperCode
            </span>

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setIsSearchOpen((prev) => !prev)}
                className={cn(
                  'w-7 h-7 rounded-md flex items-center justify-center transition-colors',
                  isSearchOpen
                    ? 'bg-black/[0.08] dark:bg-white/[0.12] text-foreground'
                    : 'text-muted-foreground hover:text-foreground hover:bg-black/[0.05] dark:hover:bg-white/[0.06]'
                )}
                title="搜索会话"
              >
                <Search className="w-4 h-4" />
              </button>

              <button
                type="button"
                onClick={onToggle}
                className="w-7 h-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-black/[0.05] dark:hover:bg-white/[0.06] transition-colors"
                title="收起侧边栏"
              >
                <PanelLeftClose className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* 搜索框 */}
          <AnimatePresence>
            {isSearchOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="overflow-hidden px-3 pb-2"
              >
                <div className="relative flex items-center">
                  <Search className="absolute left-2.5 w-3.5 h-3.5 text-muted-foreground/60 pointer-events-none" />
                  <input
                    autoFocus
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="搜索历史会话..."
                    className="w-full h-7.5 pl-8 pr-7 bg-black/[0.04] dark:bg-white/[0.06] border border-black/[0.08] dark:border-white/[0.08] rounded-lg text-xs placeholder:text-muted-foreground/50 focus:outline-none focus:border-ring"
                  />
                  {searchQuery && (
                    <button
                      type="button"
                      onClick={() => setSearchQuery('')}
                      className="absolute right-2 text-muted-foreground/60 hover:text-foreground p-0.5 rounded"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* 顶部固定导航区（新聊天、插件、打开项目、Git） */}
          <div className="px-2 pt-1 pb-2 space-y-0.5 border-b border-black/[0.06] dark:border-white/[0.06]">
            {/* 新聊天 */}
            <button
              type="button"
              onClick={onNewSession}
              className="flex items-center gap-2.5 w-full px-2.5 py-2 rounded-lg text-[13px] font-medium text-foreground hover:bg-black/[0.05] dark:hover:bg-white/[0.08] transition-colors text-left"
            >
              <SquarePen className="w-4 h-4 shrink-0 text-foreground" />
              <span className="flex-1 truncate">新聊天</span>
            </button>

            {/* 插件列表 */}
            {activePluginsList.map((plugin) => {
              const isActive = activePlugin === plugin.id;
              return (
                <button
                  key={plugin.id}
                  type="button"
                  onClick={() => onActivePluginChange(isActive ? null : plugin.id)}
                  className={cn(
                    'flex items-center gap-2.5 w-full px-2.5 py-2 rounded-lg text-[13px] transition-colors text-left',
                    isActive
                      ? 'bg-black/[0.08] dark:bg-white/[0.12] text-foreground font-medium'
                      : 'text-muted-foreground hover:text-foreground hover:bg-black/[0.04] dark:hover:bg-white/[0.06]'
                  )}
                  title={plugin.description}
                >
                  <PluginIcon id={plugin.id} />
                  <span className="flex-1 truncate">{plugin.name}</span>
                </button>
              );
            })}

            {/* 打开项目 */}
            <button
              type="button"
              onClick={onSelectOtherProject}
              className="flex items-center gap-2.5 w-full px-2.5 py-2 rounded-lg text-[13px] text-muted-foreground hover:text-foreground hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition-colors text-left"
              title="切换或打开项目工作区"
            >
              <FolderOpen className="w-4 h-4 shrink-0 text-muted-foreground/80" />
              <span className="flex-1 truncate">打开项目</span>
            </button>

            {/* Git 版本控制 */}
            <button
              type="button"
              onClick={onGitPanelToggle}
              className={cn(
                'flex items-center gap-2.5 w-full px-2.5 py-2 rounded-lg text-[13px] transition-colors text-left',
                isGitPanelOpen
                  ? 'bg-black/[0.08] dark:bg-white/[0.12] text-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-black/[0.04] dark:hover:bg-white/[0.06]'
              )}
            >
              <GitBranch className="w-4 h-4 shrink-0 text-muted-foreground/80" />
              <span className="flex-1 truncate">Git 仓库</span>
            </button>
          </div>

          {/* 会话历史列表区域（支持按项目文件夹折叠/展开，清晰层级，纯净文字，带完整删除交互） */}
          <ScrollArea className="flex-1 px-2">
            <div className="py-2 space-y-3">
              {isHistoryLoading && historyItems.length === 0 && (
                <div className="py-3 px-3 text-xs text-muted-foreground/60">加载中...</div>
              )}

              {!isHistoryLoading && filteredHistory.length === 0 && (
                <div className="py-3 px-3 text-xs text-muted-foreground/60">
                  {searchQuery ? '未找到相关会话' : '暂无历史记录'}
                </div>
              )}

              {projectGroups.map((group) => {
                const isCollapsed = collapsedProjects.has(group.workspace);
                const isCurrentProject =
                  group.workspace === selectedWorkspace || group.workspace === selectedBaseWorkspace;

                return (
                  <div key={group.workspace} className="space-y-0.5">
                    {/* 项目文件夹分组标头（清晰展示项目名、支持点击展开/折叠、显示会话数） */}
                    <button
                      type="button"
                      onClick={() => toggleProjectCollapse(group.workspace)}
                      className={cn(
                        'flex items-center gap-1.5 w-full min-w-0 overflow-hidden px-2 py-1.5 rounded-md text-[12px] font-medium transition-colors text-left select-none group',
                        isCurrentProject
                          ? 'text-foreground'
                          : 'text-muted-foreground hover:text-foreground hover:bg-black/[0.03] dark:hover:bg-white/[0.04]'
                      )}
                      title={`项目路径: ${group.workspace}\n点击展开/收起`}
                    >
                      <ChevronRight
                        className={cn(
                          'w-3.5 h-3.5 text-muted-foreground/60 group-hover:text-foreground transition-transform duration-150 shrink-0',
                          !isCollapsed && 'rotate-90'
                        )}
                      />
                      <Folder className="w-3.5 h-3.5 text-muted-foreground/70 group-hover:text-foreground shrink-0" />
                      <span className="truncate min-w-0 flex-1 font-semibold tracking-tight">
                        {group.name}
                      </span>
                      <span className="text-[10px] font-mono text-muted-foreground/60 px-1.5 py-0.2 rounded-full bg-black/[0.04] dark:bg-white/[0.06] shrink-0">
                        {group.items.length}
                      </span>
                    </button>

                    {/* 项目下的会话列表 */}
                    <AnimatePresence initial={false}>
                      {!isCollapsed && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.15 }}
                          className="overflow-hidden pl-3 space-y-0.5 border-l border-black/[0.06] dark:border-white/[0.06] ml-3.5 my-0.5"
                        >
                          {group.items.map((item) => {
                            const isActive = item.sessionId === currentSessionId;
                            const isWorktree = item.executionMode === 'worktree';

                            return (
                              <div
                                key={item.sessionId}
                                onClick={() => {
                                  onActivePluginChange(null);
                                  onSelectHistory(item.sessionId);
                                }}
                                title={item.title}
                                className={cn(
                                  'group relative flex items-center justify-between w-full min-w-0 overflow-hidden px-2.5 py-1.5 rounded-lg text-[13px] cursor-pointer transition-colors text-left select-none',
                                  isActive
                                    ? 'bg-black/[0.08] dark:bg-white/[0.12] text-foreground font-medium'
                                    : 'text-muted-foreground hover:text-foreground hover:bg-black/[0.04] dark:hover:bg-white/[0.06]'
                                )}
                              >
                                <div className="min-w-0 flex-1 flex items-center gap-1.5 overflow-hidden">
                                  <span className="truncate block min-w-0 flex-1 leading-snug tracking-tight">
                                    {item.title}
                                  </span>
                                  {isWorktree && (
                                    <span className="shrink-0 text-[9px] font-mono px-1 py-0.2 rounded border border-blue-500/25 bg-blue-500/10 text-blue-600 dark:text-blue-400">
                                      worktree
                                    </span>
                                  )}
                                </div>

                                {/* 删除按钮（支持 hover 显著出现，点击触发删除会话） */}
                                <button
                                  type="button"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    event.preventDefault();
                                    onDeleteHistory(item.sessionId);
                                  }}
                                  className={cn(
                                    'shrink-0 p-1 ml-1 rounded-md text-muted-foreground/40 hover:text-destructive hover:bg-destructive/10 transition-all',
                                    isActive ? 'opacity-50 group-hover:opacity-100' : 'opacity-0 group-hover:opacity-100'
                                  )}
                                  aria-label={`删除会话 ${item.title}`}
                                  title="删除会话"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            );
                          })}
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                );
              })}

              {hasMoreHistory && (
                <button
                  type="button"
                  onClick={onLoadMoreHistory}
                  disabled={isHistoryLoading}
                  className="w-full text-center py-1.5 text-xs text-muted-foreground/70 hover:text-foreground transition-colors"
                >
                  {isHistoryLoading ? '加载中...' : '加载更多'}
                </button>
              )}
            </div>
          </ScrollArea>

          {/* Git 展开内容抽屉 */}
          <AnimatePresence>
            {isGitPanelOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 280, opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden border-t border-black/[0.08] dark:border-white/[0.08]"
              >
                <GitPanel sessionId={currentSessionId} />
              </motion.div>
            )}
          </AnimatePresence>

          {/* 底部用户/工作区卡片（ChatGPT 底部样式） */}
          <div className="p-2 border-t border-black/[0.06] dark:border-white/[0.06]">
            <button
              type="button"
              onClick={onSelectOtherProject}
              className="flex items-center justify-between w-full p-1.5 rounded-lg hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition-colors text-left group"
              title={`当前项目: ${selectedWorkspace}\n点击切换工作区`}
            >
              <div className="flex items-center gap-2.5 min-w-0 flex-1">
                {/* 橙红色圆形头像徽标 */}
                <div className="w-7 h-7 rounded-full bg-[#d9534f] text-white flex items-center justify-center font-semibold text-[11px] shrink-0">
                  {initials}
                </div>
                <div className="flex flex-col min-w-0 flex-1">
                  <span className="text-[13px] font-medium text-foreground truncate leading-tight">
                    {currentProjectName}
                  </span>
                  <span className="text-[11px] text-muted-foreground/70 truncate leading-tight">
                    {backendMode === 'agent' ? 'Agent 模式' : 'Demo 模式'}
                  </span>
                </div>
              </div>

              <span className="text-[11px] px-2 py-0.5 rounded-full bg-black/[0.06] dark:bg-white/[0.10] text-muted-foreground group-hover:text-foreground transition-colors font-normal">
                切换
              </span>
            </button>
          </div>
        </div>
      )}

      {/* 折叠态 (52px 极简 Rail) */}
      {isCollapsed && (
        <div className="flex flex-col items-center justify-between h-full py-3">
          <div className="flex flex-col items-center gap-2.5 w-full px-1">
            <button
              type="button"
              onClick={onNewSession}
              className="w-8 h-8 rounded-lg text-foreground hover:bg-black/[0.06] dark:hover:bg-white/[0.10] flex items-center justify-center transition-colors"
              title="新聊天"
            >
              <SquarePen className="w-4 h-4" />
            </button>

            <div className="w-5 h-[1px] bg-black/[0.08] dark:bg-white/[0.08] my-0.5" />

            {/* 插件 */}
            {activePluginsList.map((plugin) => {
              const isActive = activePlugin === plugin.id;
              return (
                <button
                  key={plugin.id}
                  type="button"
                  onClick={() => onActivePluginChange(isActive ? null : plugin.id)}
                  className={cn(
                    'w-8 h-8 rounded-lg flex items-center justify-center transition-colors',
                    isActive
                      ? 'bg-black/[0.08] dark:bg-white/[0.14] text-foreground'
                      : 'text-muted-foreground hover:text-foreground hover:bg-black/[0.05] dark:hover:bg-white/[0.08]'
                  )}
                  title={plugin.name}
                >
                  <PluginIcon id={plugin.id} />
                </button>
              );
            })}

            {/* Git */}
            <button
              type="button"
              onClick={onGitPanelToggle}
              className={cn(
                'w-8 h-8 rounded-lg flex items-center justify-center transition-colors',
                isGitPanelOpen
                  ? 'bg-black/[0.08] dark:bg-white/[0.14] text-foreground'
                  : 'text-muted-foreground hover:text-foreground hover:bg-black/[0.05] dark:hover:bg-white/[0.08]'
              )}
              title="Git 仓库"
            >
              <GitBranch className="w-4 h-4" />
            </button>
          </div>

          <div className="flex flex-col items-center gap-2 w-full px-1">
            {/* 头像 */}
            <div
              className="w-7 h-7 rounded-full bg-[#d9534f] text-white flex items-center justify-center font-semibold text-[11px] shrink-0 cursor-pointer shadow-2xs"
              onClick={onSelectOtherProject}
              title={`当前工作区: ${currentProjectName}`}
            >
              {initials}
            </div>

            {/* 展开 */}
            <button
              type="button"
              onClick={onToggle}
              className="w-8 h-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-black/[0.05] dark:hover:bg-white/[0.08] flex items-center justify-center transition-colors"
              title="展开侧边栏"
            >
              <PanelLeftOpen className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}
