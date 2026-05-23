import {
  Commit,
  CommitHeader,
  CommitHash,
  CommitMessage,
  CommitMetadata,
  CommitSeparator,
  CommitInfo,
  CommitFile,
  CommitFileInfo,
  CommitFileStatus,
  CommitFileIcon,
  CommitFilePath,
} from '@/components/ai-elements/commit';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import type { GitCommitInfo, GitLogPayload, GitTagInfo, GitTagsPayload } from '@/lib/app-types';
import {
  GitBranch,
  GitCommitHorizontal,
  Tag,
  Loader2,
  Plus,
  RefreshCw,
  Send,
} from 'lucide-react';
import { memo, useCallback, useEffect, useRef, useState } from 'react';

type GitPanelProps = {
  sessionId: string | null;
};

const FILE_STATUS_MAP: Record<string, 'added' | 'modified' | 'deleted' | 'renamed'> = {
  A: 'added',
  M: 'modified',
  D: 'deleted',
  R: 'renamed',
};

function parseFileStatus(line: string): { status: 'added' | 'modified' | 'deleted' | 'renamed'; path: string } {
  const code = line.substring(0, 2).trim();
  const path = line.substring(3).trim();
  const status = FILE_STATUS_MAP[code] ?? 'modified';
  return { status, path };
}

function CommitItem({ commit }: { commit: GitCommitInfo }) {
  return (
    <Commit defaultOpen={false}>
      <CommitHeader>
        <CommitInfo>
          <CommitMessage>{commit.message}</CommitMessage>
          <CommitMetadata>
            <CommitHash>{commit.hash}</CommitHash>
            <CommitSeparator />
            <span>{commit.author}</span>
            <CommitSeparator />
            <span>{commit.date}</span>
          </CommitMetadata>
        </CommitInfo>
      </CommitHeader>
    </Commit>
  );
}

function CommitForm({
  sessionId,
  changedFiles,
  onCommitSuccess,
}: {
  sessionId: string;
  changedFiles: string[];
  onCommitSuccess?: () => void;
}) {
  const [message, setMessage] = useState('');
  const [isCommitting, setIsCommitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleCommit = useCallback(async () => {
    if (!message.trim() || isCommitting) return;
    setIsCommitting(true);
    try {
      const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/git/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message.trim() }),
      });
      if (res.ok) {
        setMessage('');
        onCommitSuccess?.();
      }
    } catch (error) {
      console.error(error);
    } finally {
      setIsCommitting(false);
    }
  }, [sessionId, message, isCommitting, onCommitSuccess]);

  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
        <GitCommitHorizontal className="size-3" />
        待提交变更 ({changedFiles.length})
      </div>
      {changedFiles.length > 0 && (
        <div className="rounded-md border bg-muted/30 max-h-32 overflow-y-auto">
          {changedFiles.map((line, i) => {
            const { status, path } = parseFileStatus(line);
            return (
              <CommitFile key={i}>
                <CommitFileInfo>
                  <CommitFileStatus status={status} />
                  <CommitFileIcon />
                  <CommitFilePath>{path}</CommitFilePath>
                </CommitFileInfo>
              </CommitFile>
            );
          })}
        </div>
      )}
      <div className="flex gap-1.5">
        <Input
          ref={inputRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void handleCommit();
            }
          }}
          placeholder="输入提交信息..."
          className="h-8 text-xs flex-1"
          disabled={isCommitting || changedFiles.length === 0}
        />
        <Button
          size="sm"
          className="h-8 px-3 gap-1.5 text-xs shrink-0"
          onClick={handleCommit}
          disabled={!message.trim() || isCommitting || changedFiles.length === 0}
        >
          {isCommitting ? <Loader2 className="size-3 animate-spin" /> : <Send className="size-3" />}
          提交
        </Button>
      </div>
    </div>
  );
}

function TagForm({ sessionId, tags, onTagCreated }: { sessionId: string; tags: GitTagInfo[]; onTagCreated?: () => void }) {
  const [tagName, setTagName] = useState('');
  const [tagMessage, setTagMessage] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const handleCreate = useCallback(async () => {
    if (!tagName.trim() || isCreating) return;
    setIsCreating(true);
    try {
      const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/git/tag`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag: tagName.trim(), message: tagMessage.trim() || undefined }),
      });
      if (res.ok) {
        setTagName('');
        setTagMessage('');
        setShowForm(false);
        onTagCreated?.();
      }
    } catch (error) {
      console.error(error);
    } finally {
      setIsCreating(false);
    }
  }, [sessionId, tagName, tagMessage, isCreating, onTagCreated]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
          <Tag className="size-3" />
          版本标签 ({tags.length})
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-[10px] gap-1"
          onClick={() => setShowForm(!showForm)}
        >
          <Plus className="size-3" />
          新建
        </Button>
      </div>
      {showForm && (
        <div className="space-y-1.5 rounded-md border bg-muted/30 p-2">
          <Input
            value={tagName}
            onChange={(e) => setTagName(e.target.value)}
            placeholder="标签名 (如 v1.0.0)"
            className="h-7 text-xs"
          />
          <Input
            value={tagMessage}
            onChange={(e) => setTagMessage(e.target.value)}
            placeholder="标签注释 (可选)"
            className="h-7 text-xs"
          />
          <Button
            size="sm"
            className="h-7 px-3 text-xs gap-1 w-full"
            onClick={handleCreate}
            disabled={!tagName.trim() || isCreating}
          >
            {isCreating ? <Loader2 className="size-3 animate-spin" /> : <Tag className="size-3" />}
            创建标签
          </Button>
        </div>
      )}
      {tags.length > 0 && (
        <div className="space-y-0.5">
          {tags.map((tag) => (
            <div key={tag.name} className="flex items-center gap-2 rounded px-2 py-1 text-xs hover:bg-muted/50">
              <Tag className="size-3 text-muted-foreground shrink-0" />
              <span className="font-mono font-medium">{tag.name}</span>
              {tag.message && <span className="text-muted-foreground truncate">{tag.message}</span>}
              <span className="ml-auto text-muted-foreground text-[10px] shrink-0">{tag.date}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export const GitPanel = memo(function GitPanel({ sessionId }: GitPanelProps) {
  const [gitLog, setGitLog] = useState<GitLogPayload | null>(null);
  const [tags, setTags] = useState<GitTagInfo[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'changes' | 'history' | 'tags'>('changes');

  const refreshGitState = useCallback(async () => {
    if (!sessionId) return;
    setIsLoading(true);
    try {
      const [logRes, tagsRes] = await Promise.all([
        fetch(`http://localhost:8000/api/sessions/${sessionId}/git/log?count=30`),
        fetch(`http://localhost:8000/api/sessions/${sessionId}/git/tags`),
      ]);
      if (logRes.ok) {
        const logData: GitLogPayload = await logRes.json();
        setGitLog(logData);
      }
      if (tagsRes.ok) {
        const tagsData: GitTagsPayload = await tagsRes.json();
        setTags(tagsData.tags ?? []);
      }
    } catch (error) {
      console.error(error);
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  const hasLoadedRef = useRef(false);

  useEffect(() => {
    if (!hasLoadedRef.current && sessionId) {
      hasLoadedRef.current = true;
      void refreshGitState();
    }
  }, [sessionId, refreshGitState]);

  if (!sessionId) return null;

  const isRepo = gitLog?.isRepo ?? false;
  const changedFiles = gitLog?.changedFiles ?? [];
  const commits = gitLog?.commits ?? [];
  const branch = gitLog?.branch ?? 'main';

  if (!isRepo) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-4 text-xs text-muted-foreground">
        <GitBranch className="size-6" />
        <span>不是 Git 仓库</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full text-foreground">
      <div className="flex items-center justify-between px-3 py-2 border-b">
        <div className="flex items-center gap-1.5 text-xs font-medium">
          <GitBranch className="size-3.5" />
          <span className="font-mono">{branch}</span>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={refreshGitState}
          disabled={isLoading}
          title="刷新"
        >
          <RefreshCw className={cn('size-3.5', isLoading && 'animate-spin')} />
        </Button>
      </div>

      <div className="flex border-b">
        {(['changes', 'history', 'tags'] as const).map((tab) => {
          const label = tab === 'changes' ? '变更' : tab === 'history' ? '历史' : '标签';
          const badge = tab === 'changes' ? changedFiles.length : undefined;
          return (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={cn(
                'flex-1 py-1.5 text-[11px] font-medium transition-colors relative',
                activeTab === tab
                  ? 'text-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              <span className="inline-flex items-center gap-1">
                {label}
                {badge != null && badge > 0 ? (
                  <span className="inline-flex items-center justify-center size-4 rounded-full bg-primary/15 text-primary text-[9px]">
                    {badge}
                  </span>
                ) : null}
              </span>
              {activeTab === tab && (
                <span className="absolute bottom-0 left-1/4 right-1/4 h-0.5 bg-primary rounded-full" />
              )}
            </button>
          );
        })}
      </div>

      <ScrollArea className="flex-1">
        <div className="p-3 space-y-3">
          {activeTab === 'changes' && (
            <CommitForm
              sessionId={sessionId}
              changedFiles={changedFiles}
              onCommitSuccess={refreshGitState}
            />
          )}

          {activeTab === 'history' && (
            <div className="space-y-1">
              {commits.length === 0 ? (
                <div className="text-xs text-muted-foreground text-center py-4">暂无提交历史</div>
              ) : (
                commits.map((commit, i) => (
                  <CommitItem key={commit.hash} commit={commit} isLast={i === commits.length - 1} />
                ))
              )}
            </div>
          )}

          {activeTab === 'tags' && (
            <TagForm
              sessionId={sessionId}
              tags={tags}
              onTagCreated={refreshGitState}
            />
          )}
        </div>
      </ScrollArea>
    </div>
  );
});
