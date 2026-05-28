"use client";

import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  ManagedProcessPayload,
  TerminalSocketClientMessage,
  TerminalSocketServerMessage,
} from "@/lib/app-types";
import { AnimatePresence, motion } from "motion/react";
import {
  ChevronDown,
  Eraser,
  PlugZap,
  RefreshCw,
  Square,
  Terminal as TerminalIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

type TerminalPanelProps = {
  sessionId: string | null;
  cwd: string;
  backend: string;
  isOpen: boolean;
  isStoppingProcesses: boolean;
  processes: ManagedProcessPayload[];
  onRuntimeStatusChange: (status: {
    cwd?: string | null;
    backend?: string;
    supportsInterrupt?: boolean;
    supportsResize?: boolean;
  }) => void;
  onToggle: () => void;
  onRefreshProcesses: () => void;
  onStopAllProcesses: () => void;
  onTerminateProcess: (terminalId: string) => void;
};

function buildTerminalWebSocketUrl(sessionId: string) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//localhost:3001/api/sessions/${sessionId}/terminal/ws`;
}

function safeParseTerminalMessage(data: MessageEvent["data"]): TerminalSocketServerMessage | null {
  if (typeof data !== "string") {
    return null;
  }

  try {
    const parsed = JSON.parse(data) as TerminalSocketServerMessage;
    return parsed && typeof parsed.type === "string" ? parsed : null;
  } catch {
    return null;
  }
}

export function TerminalPanel({
  sessionId,
  cwd,
  backend,
  isOpen,
  isStoppingProcesses,
  processes,
  onRuntimeStatusChange,
  onToggle,
  onRefreshProcesses,
  onStopAllProcesses,
  onTerminateProcess,
}: TerminalPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const resizeTimerRef = useRef<number | null>(null);
  const outputFrameRef = useRef<number | null>(null);
  const outputBufferRef = useRef<string[]>([]);
  const lastResizeRef = useRef<{ cols: number; rows: number } | null>(null);
  const supportsResizeRef = useRef(false);
  const connectedSessionRef = useRef<string | null>(null);
  const [connectionState, setConnectionState] = useState<"idle" | "connecting" | "open" | "closed" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  const sendSocketMessage = useCallback((message: TerminalSocketClientMessage) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return false;
    }
    socket.send(JSON.stringify(message));
    return true;
  }, []);

  const flushTerminalOutput = useCallback(() => {
    outputFrameRef.current = null;
    const terminal = terminalRef.current;
    const output = outputBufferRef.current.join("");
    outputBufferRef.current = [];
    if (terminal && output) {
      terminal.write(output);
    }
  }, []);

  const enqueueTerminalOutput = useCallback((output: string) => {
    if (!output) {
      return;
    }
    outputBufferRef.current.push(output);
    if (outputFrameRef.current === null) {
      outputFrameRef.current = window.requestAnimationFrame(flushTerminalOutput);
    }
  }, [flushTerminalOutput]);

  const clearQueuedTerminalOutput = useCallback(() => {
    outputBufferRef.current = [];
    if (outputFrameRef.current !== null) {
      window.cancelAnimationFrame(outputFrameRef.current);
      outputFrameRef.current = null;
    }
  }, []);

  const sendTerminalResize = useCallback(() => {
    const terminal = terminalRef.current;
    if (!terminal || (!supportsResizeRef.current && backend !== "winpty")) {
      return;
    }

    const nextSize = { cols: terminal.cols, rows: terminal.rows };
    const lastSize = lastResizeRef.current;
    if (lastSize?.cols === nextSize.cols && lastSize.rows === nextSize.rows) {
      return;
    }

    lastResizeRef.current = nextSize;
    sendSocketMessage({ type: "resize", ...nextSize });
  }, [backend, sendSocketMessage]);

  const fitTerminal = useCallback(() => {
    const fitAddon = fitAddonRef.current;
    const terminal = terminalRef.current;
    if (!fitAddon || !terminal || !containerRef.current) {
      return;
    }

    try {
      fitAddon.fit();
    } catch {
      // xterm can throw during first layout while the panel is still animating.
      return;
    }

    if (resizeTimerRef.current !== null) {
      window.clearTimeout(resizeTimerRef.current);
    }
    resizeTimerRef.current = window.setTimeout(() => {
      resizeTimerRef.current = null;
      sendTerminalResize();
    }, 120);
  }, [sendTerminalResize]);

  const connectTerminal = useCallback(() => {
    if (!sessionId || !isOpen || !terminalRef.current) {
      return;
    }

    if (
      socketRef.current &&
      socketRef.current.readyState <= WebSocket.OPEN &&
      connectedSessionRef.current === sessionId
    ) {
      return;
    }

    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }

    connectedSessionRef.current = sessionId;
    setConnectionState("connecting");
    setErrorMessage("");

    const socket = new WebSocket(buildTerminalWebSocketUrl(sessionId));
    socketRef.current = socket;

    socket.addEventListener("open", () => {
      setConnectionState("open");
      fitTerminal();
      terminalRef.current?.focus();
    });

    socket.addEventListener("message", (event) => {
      const message = safeParseTerminalMessage(event.data);
      if (!message) {
        return;
      }

      if (message.type === "output") {
        enqueueTerminalOutput(message.data);
        return;
      }

      if (message.type === "status") {
        supportsResizeRef.current = message.supportsResize === true;
        onRuntimeStatusChange(message);
        if (message.supportsResize === true) {
          window.requestAnimationFrame(fitTerminal);
        }
        return;
      }

      if (message.type === "clear") {
        clearQueuedTerminalOutput();
        terminalRef.current?.clear();
        return;
      }

      if (message.type === "error") {
        clearQueuedTerminalOutput();
        setConnectionState("error");
        setErrorMessage(message.message);
        terminalRef.current?.writeln(`\r\n[terminal] ${message.message}`);
      }
    });

    socket.addEventListener("close", () => {
      if (socketRef.current === socket) {
        socketRef.current = null;
      }
      setConnectionState((current) => (current === "error" ? current : "closed"));
    });

    socket.addEventListener("error", () => {
      setConnectionState("error");
      setErrorMessage("终端连接失败");
    });
  }, [clearQueuedTerminalOutput, enqueueTerminalOutput, fitTerminal, isOpen, onRuntimeStatusChange, sessionId]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const terminal = new Terminal({
      cursorBlink: true,
      cursorStyle: "block",
      fontFamily: '"Cascadia Mono", "JetBrains Mono", Consolas, "Courier New", monospace',
      fontSize: 12,
      lineHeight: 1.25,
      scrollback: 8000,
      allowTransparency: true,
      theme: {
        background: "#111314",
        foreground: "#d9ded8",
        cursor: "#f4c95d",
        cursorAccent: "#111314",
        selectionBackground: "#4a5d58",
        black: "#111314",
        red: "#e06c75",
        green: "#98c379",
        yellow: "#e5c07b",
        blue: "#61afef",
        magenta: "#c678dd",
        cyan: "#56b6c2",
        white: "#d9ded8",
        brightBlack: "#5b625f",
        brightRed: "#ff7b86",
        brightGreen: "#b3df91",
        brightYellow: "#f3d98b",
        brightBlue: "#7cc7ff",
        brightMagenta: "#dfa3f7",
        brightCyan: "#7bd7e4",
        brightWhite: "#f2f5f1",
      },
    });
    const fitAddon = new FitAddon();
    const webLinksAddon = new WebLinksAddon((event, uri) => {
      event.preventDefault();
      window.open(uri, "_blank", "noopener,noreferrer");
    });

    terminal.loadAddon(fitAddon);
    terminal.loadAddon(webLinksAddon);
    terminal.open(containerRef.current!);
    terminalRef.current = terminal;
    fitAddonRef.current = fitAddon;

    const dataDisposable = terminal.onData((data) => {
      sendSocketMessage({ type: "input", data });
    });

    const keyDisposable = terminal.onKey(({ domEvent }) => {
      if ((domEvent.ctrlKey || domEvent.metaKey) && domEvent.key.toLowerCase() === "k") {
        domEvent.preventDefault();
        terminal.clear();
      }
    });

    resizeObserverRef.current = new ResizeObserver(() => {
      window.requestAnimationFrame(fitTerminal);
    });
    resizeObserverRef.current.observe(containerRef.current!);

    window.requestAnimationFrame(() => {
      fitTerminal();
      connectTerminal();
    });

    return () => {
      dataDisposable.dispose();
      keyDisposable.dispose();
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
      clearQueuedTerminalOutput();
      terminal.dispose();
      terminalRef.current = null;
      fitAddonRef.current = null;
    };
  }, [connectTerminal, fitTerminal, isOpen, sendSocketMessage]);

  useEffect(() => {
    if (!isOpen) {
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
      return;
    }
    connectTerminal();
  }, [connectTerminal, isOpen]);

  useEffect(() => {
    if (!isOpen || !sessionId || connectionState !== "closed") {
      return;
    }
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
    }
    reconnectTimerRef.current = window.setTimeout(() => {
      reconnectTimerRef.current = null;
      connectTerminal();
    }, 1200);

    return () => {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
  }, [connectTerminal, connectionState, isOpen, sessionId]);

  useEffect(() => {
    return () => {
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
      if (resizeTimerRef.current !== null) {
        window.clearTimeout(resizeTimerRef.current);
      }
      clearQueuedTerminalOutput();
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      socketRef.current?.close();
    };
  }, []);

  const handleClear = useCallback(() => {
    clearQueuedTerminalOutput();
    terminalRef.current?.clear();
    sendSocketMessage({ type: "clear" });
  }, [clearQueuedTerminalOutput, sendSocketMessage]);

  const handleInterrupt = useCallback(() => {
    sendSocketMessage({ type: "interrupt" });
    terminalRef.current?.focus();
  }, [sendSocketMessage]);

  const connectionLabel =
    connectionState === "open"
      ? "已连接"
      : connectionState === "connecting"
        ? "连接中"
        : connectionState === "error"
          ? "异常"
          : "未连接";

  return (
    <div className="flex flex-col shrink-0">
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 360, opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.24, ease: [0.25, 0.1, 0.25, 1] }}
            className="border-t bg-background text-foreground flex flex-col overflow-hidden"
          >
            <div className="border-b px-3 flex items-center justify-between shrink-0 bg-muted/40 h-9">
              <div className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                <TerminalIcon className="w-3.5 h-3.5 shrink-0" />
                <span className="shrink-0">PowerShell</span>
                <Badge variant="secondary" className="font-mono text-[10px] uppercase">
                  {backend === "winpty" ? "PTY" : "PIPE"}
                </Badge>
                <Badge
                  variant={connectionState === "open" ? "secondary" : connectionState === "error" ? "destructive" : "outline"}
                  className="font-mono text-[10px]"
                >
                  {connectionLabel}
                </Badge>
                <span className="truncate font-mono text-[11px]" title={cwd || "当前目录"}>
                  {cwd || "等待终端就绪"}
                </span>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleInterrupt}
                  disabled={connectionState !== "open"}
                  className="h-7 px-2 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                  title="发送 Ctrl+C 中断"
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
                  onClick={handleClear}
                  className="h-7 w-7 text-muted-foreground hover:bg-muted hover:text-foreground"
                  title="清空终端"
                >
                  <Eraser className="w-3.5 h-3.5" />
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
              <div className="relative min-h-0 overflow-hidden bg-[#111314]">
                <div
                  ref={containerRef}
                  className="h-full w-full overflow-hidden px-3 py-2 [&_.xterm]:h-full [&_.xterm-viewport]:!overflow-y-auto"
                  onMouseDown={() => terminalRef.current?.focus()}
                />
                {errorMessage && connectionState === "error" ? (
                  <div className="pointer-events-none absolute bottom-2 left-3 rounded border border-destructive/30 bg-destructive/10 px-2 py-1 text-[11px] text-destructive">
                    {errorMessage}
                  </div>
                ) : null}
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
                                  {process.status === "running"
                                    ? "运行中"
                                    : process.status === "orphaned"
                                      ? "残留"
                                      : process.status}
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
          {connectionState === "open" ? (
            <span className="h-2 w-2 rounded-full bg-emerald-500/70" />
          ) : (
            <PlugZap className="h-3.5 w-3.5 opacity-60" />
          )}
        </button>
      )}
    </div>
  );
}
