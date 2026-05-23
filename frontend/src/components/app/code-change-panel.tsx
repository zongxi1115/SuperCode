import { CodeBlockDiff } from "@/components/ai-elements/code-block";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getFileIcon } from "@/lib/file-icons";
import type { CodeChangeRecord } from "@/lib/app-types";
import { ChevronDown, ChevronRight, Code2Icon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useMemo, useState } from "react";

type CodeChangePanelProps = {
  changes: CodeChangeRecord[];
  title?: string;
  emptyMessage?: string;
  collapsible?: boolean;
  defaultOpen?: boolean;
  compact?: boolean;
  className?: string;
};

const ACTION_META: Record<string, { label: string; icon: typeof PlusIcon; variant: "secondary" | "outline" | "destructive" }> = {
  added: { label: "新增", icon: PlusIcon, variant: "secondary" },
  modified: { label: "修改", icon: PencilIcon, variant: "outline" },
  deleted: { label: "删除", icon: Trash2Icon, variant: "destructive" },
};

function formatTimestamp(timestamp: number) {
  if (!timestamp) return "";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date(timestamp));
  } catch {
    return "";
  }
}

function mergeCounts(changes: CodeChangeRecord[]) {
  return changes.reduce(
    (acc, change) => {
      if (change.action === "added") acc.added += 1;
      if (change.action === "modified") acc.modified += 1;
      if (change.action === "deleted") acc.deleted += 1;
      return acc;
    },
    { added: 0, modified: 0, deleted: 0 },
  );
}

export function CodeChangePanel({
  changes,
  title = "代码变更追踪",
  emptyMessage = "本次会话还没有记录到代码变更。",
  collapsible = false,
  defaultOpen = true,
  compact = false,
  className = "",
}: CodeChangePanelProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const orderedChanges = useMemo(() => [...changes].sort((a, b) => b.timestamp - a.timestamp), [changes]);
  const counts = useMemo(() => mergeCounts(changes), [changes]);

  const content = (
    <div className={`rounded-xl border bg-muted/20 ${className}`}>
      <div className="flex items-center justify-between gap-3 border-b px-3 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Code2Icon className="size-4 text-muted-foreground" />
            <h3 className="text-sm font-medium">{title}</h3>
            <Badge variant="outline" className="rounded-full">
              {changes.length}
            </Badge>
          </div>
          {!compact ? (
            <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
              <span>新增 {counts.added}</span>
              <span>修改 {counts.modified}</span>
              <span>删除 {counts.deleted}</span>
            </div>
          ) : null}
        </div>
        {collapsible ? (
          <Button
            type="button"
            size="icon-xs"
            variant="ghost"
            onClick={() => setIsOpen((prev) => !prev)}
            aria-label={isOpen ? "收起代码变更追踪" : "展开代码变更追踪"}
          >
            {isOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          </Button>
        ) : null}
      </div>

      {(!collapsible || isOpen) ? (
        <ScrollArea className={compact ? "max-h-64" : "max-h-96"}>
          <div className="space-y-2 p-3">
            {orderedChanges.length ? orderedChanges.map((change) => {
              const meta = ACTION_META[change.action] ?? ACTION_META.modified;
              const fileIcon = getFileIcon(change.path.split("/").pop() ?? change.path);
              const isExpanded = expandedIds.has(change.id);
              const ActionIcon = meta.icon;
              return (
                <div key={change.id} className="rounded-lg border bg-background/80">
                  <button
                    type="button"
                    className="flex w-full items-start justify-between gap-3 px-3 py-2.5 text-left"
                    onClick={() =>
                      setExpandedIds((prev) => {
                        const next = new Set(prev);
                        if (next.has(change.id)) next.delete(change.id);
                        else next.add(change.id);
                        return next;
                      })
                    }
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={meta.variant} className="rounded-full">
                          <ActionIcon className="size-3" />
                          {meta.label}
                        </Badge>
                        <Badge variant="outline" className="rounded-full">
                          {change.source === "editor" ? "手动" : "AI"}
                        </Badge>
                        <span className="text-xs text-muted-foreground">{formatTimestamp(change.timestamp)}</span>
                      </div>
                      <div className="mt-2 flex items-center gap-2 font-mono text-xs text-foreground/90">
                        {fileIcon ? <span style={{ color: fileIcon.color }}>{fileIcon.icon}</span> : <Code2Icon className="size-3.5" />}
                        <span className="truncate">{change.path}</span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                        <span className="text-emerald-600">+{change.linesAdded}</span>
                        <span className="text-rose-600">-{change.linesDeleted}</span>
                        {change.stepIndex != null ? <span>步骤 {change.stepIndex}</span> : null}
                      </div>
                    </div>
                    {isExpanded ? <ChevronDown className="mt-0.5 size-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="mt-0.5 size-4 shrink-0 text-muted-foreground" />}
                  </button>

                  {isExpanded ? (
                    <div className="border-t px-3 py-3">
                      <div className="mb-2 text-xs text-muted-foreground">{change.summary}</div>
                      {change.diffPreview ? (
                        <CodeBlockDiff diff={change.diffPreview} />
                      ) : (
                        <div className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
                          当前记录没有可展示的 diff 预览。
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              );
            }) : (
              <div className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
                {emptyMessage}
              </div>
            )}
          </div>
        </ScrollArea>
      ) : null}
    </div>
  );

  return content;
}
