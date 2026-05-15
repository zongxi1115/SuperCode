"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AnimatePresence, motion } from "motion/react";
import { ChevronDown, CornerDownLeft, Terminal as TerminalIcon, Trash2 } from "lucide-react";
import type React from "react";
import { useEffect, useRef } from "react";

type TerminalPanelProps = {
  output: string;
  input: string;
  isOpen: boolean;
  isSubmitting: boolean;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  onToggle: () => void;
  onClear: () => void;
};

export function TerminalPanel({
  output,
  input,
  isOpen,
  isSubmitting,
  onInputChange,
  onSubmit,
  onToggle,
  onClear,
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
              </div>
              <div className="flex items-center gap-1">
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

            <div
              ref={outputRef}
              className="flex-1 overflow-auto bg-muted/15 px-4 py-3 font-mono text-xs leading-6 text-foreground"
            >
              <pre className="whitespace-pre-wrap">{output || "> 等待命令执行..."}</pre>
            </div>

            <div className="border-t bg-background px-4 py-3">
              <div className="flex items-center gap-3 font-mono text-xs">
                <span className="shrink-0 text-muted-foreground">PS&gt;</span>
                <Input
                  ref={inputRef}
                  value={input}
                  onChange={(event) => onInputChange(event.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="输入命令后回车执行"
                  className="h-8 border-0 bg-transparent px-0 py-0 font-mono text-xs text-foreground shadow-none focus-visible:ring-0 focus-visible:border-0 placeholder:text-muted-foreground"
                />
                <Button
                  size="icon"
                  onClick={onSubmit}
                  disabled={!input.trim() || isSubmitting}
                  title="执行命令"
                  aria-label="执行命令"
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
