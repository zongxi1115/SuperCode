"use client";

import { CodeBlockDiff } from "@/components/ai-elements/code-block";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { CodeChangeRecord } from "@/lib/app-types";
import { getFileIcon } from "@/lib/file-icons";
import { ChevronRight, FileStack } from "lucide-react";
import { memo, useMemo, useState } from "react";

type AggregatedChange = {
  path: string;
  action: string;
  linesAdded: number;
  linesDeleted: number;
  records: CodeChangeRecord[];
};

function aggregateChanges(changes: CodeChangeRecord[]): AggregatedChange[] {
  const map = new Map<string, AggregatedChange>();
  for (const c of changes) {
    const key = `${c.action}::${c.path}`;
    const existing = map.get(key);
    if (existing) {
      existing.linesAdded += c.linesAdded;
      existing.linesDeleted += c.linesDeleted;
      existing.records.push(c);
    } else {
      map.set(key, {
        path: c.path,
        action: c.action,
        linesAdded: c.linesAdded,
        linesDeleted: c.linesDeleted,
        records: [c],
      });
    }
  }
  return Array.from(map.values());
}

function FileChangeItem({ agg }: { agg: AggregatedChange }) {
  const [open, setOpen] = useState(false);
  const fileName = agg.path.split(/[\\/]/).pop() ?? agg.path;
  const fileIcon = getFileIcon(fileName);

  const labelStyle = cn(
    agg.action === "added" && "text-emerald-600 dark:text-emerald-400",
    agg.action === "deleted" && "text-rose-500 dark:text-rose-400 line-through",
  );

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button
          className={cn(
            "group flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition-colors border-b border-border/50",
            "hover:bg-muted/60 hover:text-foreground",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            open && "bg-muted/40",
          )}
        >
          <ChevronRight
            className={cn(
              "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200",
              open && "rotate-90",
            )}
          />
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  className={cn(
                    "flex-1 truncate font-mono text-[13px] tracking-tight text-foreground/90 font-medium inline-flex items-center",
                    labelStyle,
                  )}
                >
                  {fileIcon ? (
                    <span
                      style={{ color: fileIcon.color }}
                      className="mr-1.5 text-base leading-none"
                    >
                      {fileIcon.icon}
                    </span>
                  ) : null}
                  {fileName}
                </span>
              </TooltipTrigger>
              <TooltipContent side="top" className="font-mono text-[11px]">
                {agg.path}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <span className="flex shrink-0 items-center gap-2 font-mono text-xs tabular-nums font-semibold">
            {agg.linesAdded > 0 && (
              <span className="text-emerald-500 dark:text-emerald-400">
                +{agg.linesAdded}
              </span>
            )}
            {agg.linesDeleted > 0 && (
              <span className="text-rose-500 dark:text-rose-400">
                -{agg.linesDeleted}
              </span>
            )}
          </span>
        </button>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="px-3 py-2.5 bg-muted/10 dark:bg-zinc-950/20 border-b border-border/50">
          {agg.records.map((r, i) => (
            <div key={r.id ?? i} className={cn(i > 0 && "mt-2 pt-2 border-t border-border/30")}>
              {r.summary && (
                <p className="text-xs text-muted-foreground mb-2">{r.summary}</p>
              )}
              {r.diffPreview ? (
                <CodeBlockDiff diff={r.diffPreview} />
              ) : (
                <div className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
                  暂无可展示的 diff
                </div>
              )}
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

type TurnFileChangeListProps = {
  changes: CodeChangeRecord[];
  className?: string;
};

export const TurnFileChangeList = memo(function TurnFileChangeList({
  changes,
  className,
}: TurnFileChangeListProps) {
  const aggregated = useMemo(() => aggregateChanges(changes), [changes]);
  const totalAdd = useMemo(
    () => changes.reduce((s, f) => s + f.linesAdded, 0),
    [changes],
  );
  const totalDel = useMemo(
    () => changes.reduce((s, f) => s + f.linesDeleted, 0),
    [changes],
  );

  if (changes.length === 0) return null;

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-border bg-card text-card-foreground shadow-sm mt-3",
        className,
      )}
    >
      <div className="flex items-center gap-3 border-b border-border bg-muted/30 dark:bg-zinc-900/40 px-3 py-2">
        <FileStack className="h-4 w-4 text-muted-foreground shrink-0" />
        <span className="font-mono text-xs tabular-nums font-medium text-muted-foreground">
          {aggregated.length} 个文件
        </span>
        <div className="flex items-center gap-2 font-mono text-xs tabular-nums font-medium">
          {totalAdd > 0 && (
            <span className="text-emerald-500 dark:text-emerald-400 font-bold">
              +{totalAdd}
            </span>
          )}
          {totalDel > 0 && (
            <span className="text-rose-500 dark:text-rose-400 font-bold">
              -{totalDel}
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-col bg-card divide-y-0">
        {aggregated.map((agg) => (
          <FileChangeItem key={`${agg.action}::${agg.path}`} agg={agg} />
        ))}
      </div>
    </div>
  );
});
