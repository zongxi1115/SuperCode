import { Button } from '@/components/ui/button';
import { FileTree } from '@/components/ai-elements/file-tree';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { renderDirectoryNodes } from '@/components/app/file-tree-renderers';
import type { DirectoryNode } from '@/lib/app-types';

type WorkspacePickerProps = {
  shouldRestoreSession: boolean;
  customWorkspace: string;
  sessionError: string | null;
  isSessionBooting: boolean;
  selectedWorkspace: string;
  directoryTree: DirectoryNode[];
  directoryExpanded: Set<string>;
  onDirectoryExpandedChange: (nextExpanded: Set<string>) => void;
  onCustomWorkspaceChange: (value: string) => void;
  onSelectWorkspace: (path: string) => void;
  onCreateSession: () => void | Promise<void>;
};

export function WorkspacePicker({
  shouldRestoreSession,
  customWorkspace,
  sessionError,
  isSessionBooting,
  selectedWorkspace,
  directoryTree,
  directoryExpanded,
  onDirectoryExpandedChange,
  onCustomWorkspaceChange,
  onSelectWorkspace,
  onCreateSession,
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
          <p className="text-xs text-muted-foreground">点击目录名选中工作区，点左侧箭头继续展开下一层。</p>
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
