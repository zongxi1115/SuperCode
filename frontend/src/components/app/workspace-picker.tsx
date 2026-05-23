import { Button } from '@/components/ui/button';
import { FileTree } from '@/components/ai-elements/file-tree';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { renderDirectoryNodes } from '@/components/app/file-tree-renderers';
import type { DirectoryNode, RecentProject } from '@/lib/app-types';
import { Clock, Folder, X } from 'lucide-react';

type WorkspacePickerProps = {
  shouldRestoreSession: boolean;
  customWorkspace: string;
  sessionError: string | null;
  isSessionBooting: boolean;
  selectedWorkspace: string;
  directoryTree: DirectoryNode[];
  directoryExpanded: Set<string>;
  recentProjects: RecentProject[];
  onDirectoryExpandedChange: (nextExpanded: Set<string>) => void;
  onCustomWorkspaceChange: (value: string) => void;
  onSelectWorkspace: (path: string) => void;
  onCreateSession: () => void | Promise<void>;
  onOpenRecentProject: (workspace: string) => void;
  onRemoveRecentProject: (workspace: string) => void;
};

function formatRelativeTime(timestamp: number): string {
  const diff = Date.now() - timestamp;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} 个月前`;
  return `${Math.floor(months / 12)} 年前`;
}

function getFolderName(path: string): string {
  const normalized = path.replace(/\\/g, '/');
  const segments = normalized.split('/').filter(Boolean);
  return segments[segments.length - 1] || path;
}

export function WorkspacePicker({
  shouldRestoreSession,
  customWorkspace,
  sessionError,
  isSessionBooting,
  selectedWorkspace,
  directoryTree,
  directoryExpanded,
  recentProjects,
  onDirectoryExpandedChange,
  onCustomWorkspaceChange,
  onSelectWorkspace,
  onCreateSession,
  onOpenRecentProject,
  onRemoveRecentProject,
}: WorkspacePickerProps) {
  if (shouldRestoreSession) {
    return (
      <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-6">
        <div className="w-full max-w-xl rounded-2xl border bg-card p-6 shadow-sm space-y-5">
          <div className="space-y-2">
            <div className="text-sm font-medium text-muted-foreground">正在恢复上次的工作区</div>
            <h1 className="text-2xl font-semibold">加载中...</h1>
            <p className="text-sm text-muted-foreground">工作区：{customWorkspace}</p>
          </div>
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-6">
      <div className="w-full max-w-xl rounded-2xl border bg-card p-6 shadow-sm space-y-5">
        <div className="space-y-2">
          <div className="text-sm font-medium text-muted-foreground">初始化工作区</div>
          <h1 className="text-2xl font-semibold">先打开一个工作区</h1>
          <p className="text-sm text-muted-foreground">
            选定后，文件树、代码预览和后端 agent 都会围绕这个目录工作。
          </p>
        </div>

        {recentProjects.length > 0 && (
          <div className="space-y-2">
            <label className="text-sm font-medium flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5" />
              最近打开
            </label>
            <ScrollArea className="max-h-44 rounded-lg border">
              <div className="p-1.5 space-y-0.5">
                {recentProjects.map((project) => (
                  <div
                    key={project.workspace}
                    className="group flex items-center gap-2 rounded-md px-2.5 py-2 cursor-pointer hover:bg-accent transition-colors"
                    onClick={() => onOpenRecentProject(project.workspace)}
                  >
                    <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{getFolderName(project.workspace)}</div>
                      <div className="text-xs text-muted-foreground truncate">{project.workspace}</div>
                    </div>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {formatRelativeTime(project.timestamp)}
                    </span>
                    <button
                      className="opacity-0 group-hover:opacity-100 shrink-0 p-0.5 rounded hover:bg-destructive/10 hover:text-destructive transition-all"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveRecentProject(project.workspace);
                      }}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        )}

        <div className="space-y-3">
          <label className="text-sm font-medium">树形选择目录</label>
          <ScrollArea className="h-72 rounded-lg border">
            <div className="p-3">
              <FileTree
                expanded={directoryExpanded}
                onExpandedChange={onDirectoryExpandedChange}
                selectedPath={selectedWorkspace}
                onSelect={onSelectWorkspace}
              >
                {renderDirectoryNodes(directoryTree)}
              </FileTree>
            </div>
          </ScrollArea>
          <p className="text-xs text-muted-foreground">点击目录名即可选中并展开/收起，左侧箭头也仍可单独控制展开。</p>
        </div>

        <div className="space-y-3">
          <label className="text-sm font-medium">或直接输入系统绝对路径</label>
          <Input
            value={customWorkspace}
            onChange={(e) => onCustomWorkspaceChange(e.target.value)}
            placeholder="例如 D:\\vibe_projs\\SuperCode 或 C:\\Users\\32980\\Desktop"
          />
          <p className="text-xs text-muted-foreground">留空时使用上面的选项；输入系统绝对路径时会覆盖下拉选择。</p>
        </div>

        {sessionError && (
          <div className="rounded border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {sessionError}
          </div>
        )}

        <Button className="w-full" onClick={onCreateSession} disabled={isSessionBooting}>
          {isSessionBooting ? '正在打开工作区...' : '打开工作区'}
        </Button>
      </div>
    </div>
  );
}
