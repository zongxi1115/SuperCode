"use client";

import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { CodeBlock } from "@/components/ai-elements/code-block";
import type { SubagentSnapshot } from "@/lib/app-types";
import { cn } from "@/lib/utils";
import {
  BotIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  Clock3Icon,
  FileSearchIcon,
  FileCode2Icon,
  HammerIcon,
  TerminalSquareIcon,
  XCircleIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

type SubagentTaskCardProps = {
  snapshot: SubagentSnapshot;
  className?: string;
};

function getStatusMeta(status: string) {
  if (status === "completed") {
    return {
      label: "Completed",
      icon: <CheckCircle2Icon className="size-3.5 text-emerald-600" />,
      badgeClassName: "border-emerald-200 bg-emerald-500/10 text-emerald-700",
    };
  }
  if (status === "error") {
    return {
      label: "Error",
      icon: <XCircleIcon className="size-3.5 text-destructive" />,
      badgeClassName: "border-destructive/20 bg-destructive/10 text-destructive",
    };
  }
  if (status === "paused") {
    return {
      label: "Paused",
      icon: <Clock3Icon className="size-3.5 text-amber-600" />,
      badgeClassName: "border-amber-200 bg-amber-500/10 text-amber-700",
    };
  }
  return {
    label: "Running",
    icon: <Clock3Icon className="size-3.5 animate-pulse text-primary" />,
    badgeClassName: "border-primary/20 bg-primary/10 text-primary",
  };
}

export function SubagentTaskCard({
  snapshot,
  className,
}: SubagentTaskCardProps) {
  const [isOpen, setIsOpen] = useState(snapshot.status === "running");
  const statusMeta = getStatusMeta(snapshot.status);
  const steps = snapshot.steps ?? [];
  const filesRead = snapshot.filesRead ?? [];
  const changedFiles = snapshot.changedFiles ?? [];
  const commandsRun = snapshot.commandsRun ?? [];
  const findings = snapshot.findings ?? [];
  const recommendedFiles = snapshot.recommendedFiles ?? [];
  const runningSteps = steps.filter((step) => step.status === "running").length;
  const latestStep = steps[steps.length - 1];
  const title = snapshot.title || (snapshot.kind === "code_exploration" ? "代码探索" : "子智能体");

  const summary = useMemo(() => {
    if (snapshot.status === "running" && latestStep?.name) {
      return `子智能体正在处理 ${latestStep.name}`;
    }
    if (filesRead.length > 0) {
      return `已阅读 ${filesRead.length} 个文件`;
    }
    if (recommendedFiles.length > 0) {
      return `建议查看 ${recommendedFiles.length} 个文件`;
    }
    if (changedFiles.length > 0) {
      return `已影响 ${changedFiles.length} 个文件`;
    }
    if (commandsRun.length > 0) {
      return `执行了 ${commandsRun.length} 条命令`;
    }
    return snapshot.status === "completed" ? "子任务已完成" : "子任务处理中";
  }, [
    latestStep?.name,
    filesRead.length,
    recommendedFiles.length,
    changedFiles.length,
    commandsRun.length,
    snapshot.status,
  ]);

  return (
    <Collapsible
      open={isOpen}
      onOpenChange={setIsOpen}
      className={cn("overflow-hidden rounded-xl border bg-background/70 shadow-sm", className)}
    >
      <CollapsibleTrigger className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left">
        <div className="flex min-w-0 flex-1 gap-3">
          <div className="mt-0.5 rounded-full border bg-muted/70 p-2 text-muted-foreground">
            <BotIcon className="size-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{title}</span>
              <Badge
                variant="outline"
                className={cn("gap-1.5 rounded-full text-[11px]", statusMeta.badgeClassName)}
              >
                {statusMeta.icon}
                {statusMeta.label}
              </Badge>
            </div>
            <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
              {snapshot.task}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
              <span>{summary}</span>
              {snapshot.stepCount > 0 ? <span>{snapshot.stepCount} steps</span> : null}
              {runningSteps > 0 ? <span>{runningSteps} running</span> : null}
            </div>
          </div>
        </div>
        <ChevronDownIcon
          className={cn(
            "mt-1 size-4 shrink-0 text-muted-foreground transition-transform",
            isOpen ? "rotate-180" : "rotate-0",
          )}
        />
      </CollapsibleTrigger>

      <CollapsibleContent className="border-t bg-muted/20 px-4 py-3">
        <div className="space-y-4">
          {snapshot.currentThought ? (
            <div className="space-y-1.5">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Current Thought
              </div>
              <div className="rounded-lg border bg-background px-3 py-2 text-sm text-muted-foreground">
                {snapshot.currentThought}
              </div>
            </div>
          ) : null}

          {steps.length > 0 ? (
            <div className="space-y-2">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Steps
              </div>
              <div className="space-y-2">
                {steps.map((step) => {
                  const stepMeta = getStatusMeta(step.status);
                  return (
                    <div
                      key={step.id}
                      className="rounded-lg border bg-background px-3 py-2"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2 text-sm font-medium">
                          <HammerIcon className="size-3.5 text-muted-foreground" />
                          <span>{step.name}</span>
                        </div>
                        <Badge
                          variant="outline"
                          className={cn("gap-1 rounded-full text-[10px]", stepMeta.badgeClassName)}
                        >
                          {stepMeta.icon}
                          {stepMeta.label}
                        </Badge>
                      </div>
                      {step.error ? (
                        <p className="mt-2 text-xs text-destructive">{step.error}</p>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {filesRead.length > 0 ? (
            <div className="space-y-2">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Files Read
              </div>
              <div className="grid gap-2">
                {filesRead.map((file) => (
                  <div
                    key={file}
                    className="flex items-center gap-2 rounded-lg border bg-background px-3 py-2 text-sm"
                  >
                    <FileSearchIcon className="size-3.5 text-muted-foreground" />
                    <span className="truncate">{file}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {recommendedFiles.length > 0 ? (
            <div className="space-y-2">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Recommended Files
              </div>
              <div className="grid gap-2">
                {recommendedFiles.map((file) => (
                  <div
                    key={file}
                    className="flex items-center gap-2 rounded-lg border bg-background px-3 py-2 text-sm"
                  >
                    <FileCode2Icon className="size-3.5 text-muted-foreground" />
                    <span className="truncate">{file}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {findings.length > 0 ? (
            <div className="space-y-2">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Findings
              </div>
              <div className="space-y-2">
                {findings.map((finding, index) => (
                  <div
                    key={`${finding}-${index}`}
                    className="rounded-lg border bg-background px-3 py-2 text-sm text-muted-foreground"
                  >
                    {finding}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {changedFiles.length > 0 ? (
            <div className="space-y-2">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Changed Files
              </div>
              <div className="grid gap-2">
                {changedFiles.map((file) => (
                  <div
                    key={file}
                    className="flex items-center gap-2 rounded-lg border bg-background px-3 py-2 text-sm"
                  >
                    <FileCode2Icon className="size-3.5 text-muted-foreground" />
                    <span className="truncate">{file}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {commandsRun.length > 0 ? (
            <div className="space-y-2">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Commands
              </div>
              <div className="grid gap-2">
                {commandsRun.map((command, index) => (
                  <div key={`${command}-${index}`} className="rounded-lg border bg-background">
                    <div className="flex items-center gap-2 px-3 pt-3 text-xs text-muted-foreground">
                      <TerminalSquareIcon className="size-3.5" />
                      执行命令
                    </div>
                    <CodeBlock code={command} language="bash" />
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {snapshot.finalOutput ? (
            <div className="space-y-2">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Final Output
              </div>
              <div className="rounded-lg border bg-background">
                <CodeBlock code={snapshot.finalOutput} language="markdown" />
              </div>
            </div>
          ) : null}

          {snapshot.error ? (
            <div className="rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {snapshot.error}
            </div>
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
