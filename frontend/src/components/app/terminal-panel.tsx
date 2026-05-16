"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ManagedProcessPayload } from "@/lib/app-types";
import { AnimatePresence, motion } from "motion/react";
import { ChevronDown, CornerDownLeft, RefreshCw, Square, Terminal as TerminalIcon, Trash2 } from "lucide-react";
import type React from "react";
import { useEffect, useRef } from "react";

type TerminalPanelProps = {
  output: string;
  input: string;
  cwd: string;
  backend: string;
  isOpen: boolean;
  isSubmitting: boolean;
  supportsInterrupt: boolean;
  isStoppingProcesses: boolean;
  processes: ManagedProcessPayload[];
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  onInterrupt: () => void;
  onToggle: () => void;
  onClear: () => void;
  onRefreshProcesses: () => void;
  onStopAllProcesses: () => void;
  onTerminateProcess: (terminalId: string) => void;
};

export function TerminalPanel({
  output,
  input,
  cwd,
  backend,
  isOpen,
  isSubmitting,
  supportsInterrupt,
  isStoppingProcesses,
  processes,
  onInputChange,
  onSubmit,
  onInterrupt,
  onToggle,
  onClear,
  onRefreshProcesses,
  onStopAllProcesses,
  onTerminateProcess,
}: TerminalPanelProps) {
  const outputRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [output]);

  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus();
    }
  }, [isOpen]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c" && input.length === 0 && supportsInterrupt) {
      event.preventDefault();
      onInterrupt();
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      onSubmit();
    }
  };

  return (
    <div className="flex flex-col shrink-0">
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 320, opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
            className="border-t bg-background text-foreground flex flex-col overflow-hidden"
          >
            <div className="border-b px-3 flex items-center justify-between shrink-0 bg-muted/40 h-9">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <TerminalIcon className="w-3.5 h-3.5" />
                PowerShell
                <Badge variant="secondary" className="font-mono text-[10px] uppercase">
                  {backend === "winpty" ? "PTY" : "PIPE"}
                </Badge>
                <span className="max-w-[340px] truncate font-mono text-[11px]" title={cwd || "当前目录"}>
                  {cwd || "等待终端就绪"}
                </span>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onInterrupt}
                  disabled={!supportsInterrupt || isSubmitting}
                  className="h-7 px-2 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                  title={supportsInterrupt ? "发送 Ctrl+C 中断" : "当前终端后端不支持 Ctrl+C"}
                >
                  Ctrl+C
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onRefreshProcesses}
                  className="h-7 w-7 text-muted-foreground hover:bg-muted hover:text-foreground"
                  title="刷新 AI 进程"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onClear}
                  className="h-7 w-7 text-muted-foreground hover:bg-muted hover:text-foreground"
                  title="清空终端"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onToggle}
                  className="h-7 w-7 text-muted-foreground hover:bg-muted hover:text-foreground"
                  title="关闭终端"
                >
                  <ChevronDown className="w-4 h-4" />
                </Button>
              </div>
            </div>

            <div className="grid flex-1 overflow-hidden md:grid-cols-[minmax(0,1fr)_320px]">
              <div
                ref={outputRef}
                className="overflow-auto bg-muted/15 px-4 py-3 font-mono text-xs leading-6 text-foreground"
              >
                <pre className="whitespace-pre-wrap">{output || "> 等待命令执行..."}</pre>
              </div>

              <div className="border-t md:border-l md:border-t-0 bg-background/80">
                <div className="flex items-center justify-between border-b px-3 py-2">
                  <div className="text-xs font-medium text-foreground">AI 受管进程</div>
                  <Button
                    size="xs"
                    variant="destructive"
                    onClick={onStopAllProcesses}
                    disabled={processes.length === 0 || isStoppingProcesses}
                  >
                    <Square className="size-3 fill-current" />
                    全部终止
                  </Button>
                </div>
                <div className="max-h-full overflow-auto p-3">
                  {processes.length === 0 ? (
                    <p className="text-xs text-muted-foreground">当前没有仍在运行的 AI 命令进程。</p>
                  ) : (
                    <div className="space-y-2">
                      {processes.map((process) => (
                        <div
                          key={process.terminalId}
                          className="rounded-md border bg-muted/20 p-2 text-xs"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0 space-y-1">
                              <div className="flex items-center gap-2">
                                <span className="font-medium text-foreground">{process.terminalId}</span>
                                <Badge variant={process.status === "orphaned" ? "destructive" : "secondary"}>
                                  {process.status === "running" ? "运行中" : process.status === "orphaned" ? "残留" : process.status}
                                </Badge>
                              </div>
                              <p className="truncate font-mono text-[11px] text-muted-foreground">
                                PID {process.rootPid} · {process.processCount} 个进程
                              </p>
                            </div>
                            <Button
                              size="xs"
                              variant="outline"
                              onClick={() => onTerminateProcess(process.terminalId)}
                            >
                              终止
                            </Button>
                          </div>
                          <pre className="mt-2 whitespace-pre-wrap break-all rounded bg-background/70 p-2 font-mono text-[11px] leading-5 text-foreground">
                            {process.command}
                          </pre>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="border-t bg-background px-4 py-3">
              <div className="flex items-center gap-3 font-mono text-xs">
                <span className="shrink-0 text-muted-foreground">PS&gt;</span>
                <Input
                  ref={inputRef}
                  value={input}
                  onChange={(event) => onInputChange(event.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="输入命令或交互输入，回车发送；空输入也可发送回车"
                  className="h-8 border-0 bg-transparent px-0 py-0 font-mono text-xs text-foreground shadow-none focus-visible:ring-0 focus-visible:border-0 placeholder:text-muted-foreground"
                />
                <Button
                  size="icon"
                  onClick={onSubmit}
                  disabled={isSubmitting}
                  title="发送输入"
                  aria-label="发送输入"
                  className="h-7 w-7 shrink-0 bg-muted text-foreground hover:bg-muted/80"
                >
                  <CornerDownLeft className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {!isOpen && (
        <button
          onClick={onToggle}
          className="w-full h-9 flex items-center justify-center gap-2 border-t bg-background text-muted-foreground text-xs hover:text-foreground hover:bg-muted/40 transition-colors shrink-0"
        >
          <TerminalIcon className="w-3.5 h-3.5" />
          终端
          {output && (
            <span className="w-2 h-2 rounded-full bg-primary/60 animate-pulse" />
          )}
        </button>
      )}
    </div>
  );
}
