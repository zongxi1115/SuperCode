"use client";

import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  TerminalInfo,
  TerminalSocketClientMessage,
  TerminalSocketServerMessage,
} from "@/lib/app-types";
import { apiFetch, apiWebSocketUrl, openExternalUrl } from "@/lib/api-client";
import { AnimatePresence, motion } from "motion/react";
import {
  ChevronDown,
  Eraser,
  Plus,
  PlugZap,
  RefreshCw,
  Square,
  Terminal as TerminalIcon,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

type TerminalPanelProps = {
  sessionId: string | null;
  isOpen: boolean;
  terminalInfos: TerminalInfo[];
  activeTerminalId: string | null;
  onActiveTerminalChange: (id: string) => void;
  onRuntimeStatusChange: (status: {
    cwd?: string | null;
    backend?: string;
    terminalId?: string;
    supportsInterrupt?: boolean;
    supportsResize?: boolean;
  }) => void;
  onToggle: () => void;
  onRefreshTerminals: () => void;
  onCreateTerminal: (cwd?: string) => Promise<string | null>;
  onCloseTerminal: (terminalId: string) => Promise<void>;
  onTerminateProcess: (terminalId: string) => void;
};

type TerminalInstance = {
  terminalId: string;
  kind: "interactive" | "managed-process";
  xterm: Terminal;
  fitAddon: FitAddon;
  socket: WebSocket | null;
  connectedSessionId: string | null;
  connectionState: "idle" | "connecting" | "open" | "closed" | "error";
  errorMessage: string;
  outputBuffer: string[];
  outputFrame: number | null;
  writeQueue: string[];
  queuedWriteChars: number;
  isWriting: boolean;
  lastResize: { cols: number; rows: number } | null;
  supportsResize: boolean;
  cwd: string;
  backend: string;
  managedOutputOffset: number | null;
};

type ManagedProcessOutputPayload = {
  terminalId: string;
  output: string;
  startOffset: number;
  endOffset: number;
  truncated: boolean;
};

const XTERM_WRITE_CHUNK_CHARS = 65_536;
const XTERM_MAX_QUEUED_WRITE_CHARS = 384_000;
const MANAGED_PROCESS_OUTPUT_TAIL_CHARS = 64_000;

const XTERM_DARK_THEME = {
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
};

const XTERM_LIGHT_THEME = {
  background: "#eef2f7",
  foreground: "#0f172a",
  cursor: "#2563eb",
  cursorAccent: "#eef2f7",
  selectionBackground: "#c7d2fe",
  black: "#0f172a",
  red: "#b91c1c",
  green: "#166534",
  yellow: "#713f12",
  blue: "#1d4ed8",
  magenta: "#6d28d9",
  cyan: "#0e7490",
  white: "#334155",
  brightBlack: "#475569",
  brightRed: "#dc2626",
  brightGreen: "#15803d",
  brightYellow: "#854d0e",
  brightBlue: "#2563eb",
  brightMagenta: "#7c3aed",
  brightCyan: "#0891b2",
  brightWhite: "#0f172a",
};

function getXtermTheme(isDarkTheme: boolean) {
  return isDarkTheme ? XTERM_DARK_THEME : XTERM_LIGHT_THEME;
}

function buildTerminalWebSocketUrl(sessionId: string, terminalId?: string | null) {
  const base = apiWebSocketUrl(`/api/sessions/${sessionId}/terminal/ws`);
  if (terminalId) {
    const separator = base.includes("?") ? "&" : "?";
    return `${base}${separator}terminal_id=${encodeURIComponent(terminalId)}`;
  }
  return base;
}

function safeParseTerminalMessage(data: MessageEvent["data"]): TerminalSocketServerMessage | null {
  if (typeof data !== "string") return null;
  try {
    const parsed = JSON.parse(data) as TerminalSocketServerMessage;
    return parsed && typeof parsed.type === "string" ? parsed : null;
  } catch {
    return null;
  }
}

function createXtermInstance(isDarkTheme: boolean): { terminal: Terminal; fitAddon: FitAddon } {
  const terminal = new Terminal({
    cursorBlink: true,
    cursorStyle: "block",
    fontFamily: '"Cascadia Mono", "JetBrains Mono", Consolas, "Courier New", monospace',
    fontSize: 12,
    lineHeight: 1.25,
    scrollback: 3000,
    allowTransparency: true,
    theme: getXtermTheme(isDarkTheme),
  });
  const fitAddon = new FitAddon();
  const webLinksAddon = new WebLinksAddon((event, uri) => {
    event.preventDefault();
    openExternalUrl(uri);
  });
  terminal.loadAddon(fitAddon);
  terminal.loadAddon(webLinksAddon);
  return { terminal, fitAddon };
}

export function TerminalPanel({
  sessionId,
  isOpen,
  terminalInfos,
  activeTerminalId,
  onActiveTerminalChange,
  onRuntimeStatusChange,
  onToggle,
  onRefreshTerminals,
  onCreateTerminal,
  onCloseTerminal,
  onTerminateProcess,
}: TerminalPanelProps) {
  const instancesRef = useRef<Map<string, TerminalInstance>>(new Map());
  const containerRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const panelContainerRef = useRef<HTMLDivElement>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const reconnectTimersRef = useRef<Map<string, number>>(new Map());
  const resizeTimersRef = useRef<Map<string, number>>(new Map());
  const openedSetRef = useRef<Set<string>>(new Set());
  const dataDisposablesRef = useRef<Map<string, { dispose(): void }>>(new Map());
  const keyDisposablesRef = useRef<Map<string, { dispose(): void }>>(new Map());
  const pendingFocusTerminalIdRef = useRef<string | null>(null);
  const pendingFocusActiveTerminalRef = useRef(false);

  const [isDarkTheme, setIsDarkTheme] = useState(() => {
    return document.documentElement.classList.contains("dark");
  });
  const [, forceUpdate] = useState(0);
  const triggerRender = useCallback(() => forceUpdate((n) => n + 1), []);

  const getInstance = useCallback((terminalId: string) => {
    return instancesRef.current.get(terminalId);
  }, []);

  const requestTerminalFocus = useCallback((terminalId: string | null) => {
    if (terminalId) {
      pendingFocusTerminalIdRef.current = terminalId;
      pendingFocusActiveTerminalRef.current = false;
      return;
    }
    pendingFocusActiveTerminalRef.current = true;
  }, []);

  const consumeTerminalFocusRequest = useCallback((terminalId: string) => {
    if (pendingFocusTerminalIdRef.current === terminalId) {
      pendingFocusTerminalIdRef.current = null;
      return true;
    }
    if (pendingFocusActiveTerminalRef.current) {
      pendingFocusActiveTerminalRef.current = false;
      return true;
    }
    return false;
  }, []);

  const sendSocketMessage = useCallback((terminalId: string, message: TerminalSocketClientMessage) => {
    const inst = getInstance(terminalId);
    if (!inst?.socket || inst.socket.readyState !== WebSocket.OPEN) return false;
    inst.socket.send(JSON.stringify(message));
    return true;
  }, [getInstance]);

  const drainTerminalOutput = useCallback(function drainTerminalOutput(terminalId: string) {
    const inst = getInstance(terminalId);
    if (!inst || inst.isWriting) return;
    const nextOutput = inst.writeQueue.shift();
    if (!nextOutput) return;

    const chunk = nextOutput.length > XTERM_WRITE_CHUNK_CHARS
      ? nextOutput.slice(0, XTERM_WRITE_CHUNK_CHARS)
      : nextOutput;
    const remainder = nextOutput.length > XTERM_WRITE_CHUNK_CHARS
      ? nextOutput.slice(XTERM_WRITE_CHUNK_CHARS)
      : "";
    if (remainder) {
      inst.writeQueue.unshift(remainder);
    }
    inst.queuedWriteChars = Math.max(0, inst.queuedWriteChars - chunk.length);
    inst.isWriting = true;
    inst.xterm.write(chunk, () => {
      inst.isWriting = false;
      if (inst.writeQueue.length > 0) {
        window.setTimeout(() => drainTerminalOutput(terminalId), 0);
      }
    });
  }, [getInstance]);

  const queueTerminalWrite = useCallback((terminalId: string, output: string) => {
    const inst = getInstance(terminalId);
    if (!inst || !output) return;
    inst.writeQueue.push(output);
    inst.queuedWriteChars += output.length;
    while (inst.queuedWriteChars > XTERM_MAX_QUEUED_WRITE_CHARS && inst.writeQueue.length > 1) {
      const dropped = inst.writeQueue.shift() ?? "";
      inst.queuedWriteChars = Math.max(0, inst.queuedWriteChars - dropped.length);
    }
    drainTerminalOutput(terminalId);
  }, [drainTerminalOutput, getInstance]);

  const flushOutput = useCallback((terminalId: string) => {
    const inst = getInstance(terminalId);
    if (!inst) return;
    inst.outputFrame = null;
    const output = inst.outputBuffer.join("");
    inst.outputBuffer = [];
    queueTerminalWrite(terminalId, output);
  }, [getInstance, queueTerminalWrite]);

  const enqueueOutput = useCallback((terminalId: string, output: string) => {
    const inst = getInstance(terminalId);
    if (!inst || !output) return;
    inst.outputBuffer.push(output);
    if (inst.outputFrame === null) {
      inst.outputFrame = window.requestAnimationFrame(() => flushOutput(terminalId));
    }
  }, [flushOutput, getInstance]);

  const clearQueuedOutput = useCallback((terminalId: string) => {
    const inst = getInstance(terminalId);
    if (!inst) return;
    inst.outputBuffer = [];
    if (inst.outputFrame !== null) {
      window.cancelAnimationFrame(inst.outputFrame);
      inst.outputFrame = null;
    }
    inst.writeQueue = [];
    inst.queuedWriteChars = 0;
  }, [getInstance]);

  const loadManagedProcessOutput = useCallback(async (terminalId: string) => {
    if (!sessionId) return;
    const inst = getInstance(terminalId);
    if (!inst) return;

    const query = new URLSearchParams();
    query.set("tail_chars", String(MANAGED_PROCESS_OUTPUT_TAIL_CHARS));
    if (inst.managedOutputOffset !== null) {
      query.set("after_offset", String(inst.managedOutputOffset));
    }

    try {
      const res = await apiFetch(
        `/api/sessions/${sessionId}/processes/${terminalId}/output?${query.toString()}`
      );
      if (!res.ok) return;
      const data = await res.json() as ManagedProcessOutputPayload;
      const currentInst = getInstance(terminalId);
      if (!currentInst) return;

      const previousOffset = currentInst.managedOutputOffset;
      if (previousOffset !== null && data.endOffset <= previousOffset) return;

      let output = data.output;
      if (previousOffset === null || data.startOffset > previousOffset) {
        clearQueuedOutput(terminalId);
        currentInst.xterm.clear();
      } else if (data.startOffset < previousOffset) {
        output = output.slice(previousOffset - data.startOffset);
      }
      if (output) {
        queueTerminalWrite(terminalId, output);
      }
      currentInst.managedOutputOffset = data.endOffset;
    } catch {
      return;
    }
  }, [clearQueuedOutput, getInstance, queueTerminalWrite, sessionId]);

  const sendResize = useCallback((terminalId: string) => {
    const inst = getInstance(terminalId);
    if (!inst) return;
    if (!inst.supportsResize && inst.backend !== "winpty") return;
    const nextSize = { cols: inst.xterm.cols, rows: inst.xterm.rows };
    const lastSize = inst.lastResize;
    if (lastSize?.cols === nextSize.cols && lastSize.rows === nextSize.rows) return;
    inst.lastResize = nextSize;
    sendSocketMessage(terminalId, { type: "resize", ...nextSize });
  }, [getInstance, sendSocketMessage]);

  const fitTerminal = useCallback((terminalId: string) => {
    const inst = getInstance(terminalId);
    const container = containerRefs.current.get(terminalId);
    if (!inst || !container) return;
    try { inst.fitAddon.fit(); } catch { return; }
    const timerMap = resizeTimersRef.current;
    if (timerMap.has(terminalId)) window.clearTimeout(timerMap.get(terminalId)!);
    timerMap.set(terminalId, window.setTimeout(() => {
      timerMap.delete(terminalId);
      sendResize(terminalId);
    }, 120));
  }, [getInstance, sendResize]);

  const connectTerminal = useCallback((terminalId: string) => {
    const inst = getInstance(terminalId);
    if (!inst || !sessionId || !isOpen) return;
    if (inst.socket && inst.socket.readyState <= WebSocket.OPEN && inst.connectedSessionId === sessionId) return;
    if (inst.socket) { inst.socket.close(); inst.socket = null; }

    inst.connectedSessionId = sessionId;
    inst.connectionState = "connecting";
    inst.errorMessage = "";
    triggerRender();

    const wsUrl = buildTerminalWebSocketUrl(sessionId, terminalId);
    const socket = new WebSocket(wsUrl);
    inst.socket = socket;

    socket.addEventListener("open", () => {
      inst.connectionState = "open";
      triggerRender();
      fitTerminal(terminalId);
    });

    socket.addEventListener("message", (event) => {
      const message = safeParseTerminalMessage(event.data);
      if (!message) return;

      if (message.type === "output") {
        enqueueOutput(terminalId, message.data);
        return;
      }

      if (message.type === "status") {
        inst.supportsResize = message.supportsResize === true;
        if (message.cwd) inst.cwd = message.cwd;
        if (message.backend) inst.backend = message.backend;
        onRuntimeStatusChange({ ...message, terminalId });
        if (message.supportsResize === true) {
          window.requestAnimationFrame(() => fitTerminal(terminalId));
        }
        triggerRender();
        return;
      }

      if (message.type === "clear") {
        clearQueuedOutput(terminalId);
        inst.xterm.clear();
        return;
      }

      if (message.type === "error") {
        clearQueuedOutput(terminalId);
        inst.connectionState = "error";
        inst.errorMessage = message.message;
        triggerRender();
        inst.xterm.writeln(`\r\n[terminal] ${message.message}`);
      }
    });

    socket.addEventListener("close", () => {
      if (inst.socket === socket) inst.socket = null;
      inst.connectionState = inst.connectionState === "error" ? inst.connectionState : "closed";
      triggerRender();
    });

    socket.addEventListener("error", () => {
      inst.connectionState = "error";
      inst.errorMessage = "终端连接失败";
      triggerRender();
    });
  }, [clearQueuedOutput, enqueueOutput, fitTerminal, getInstance, isOpen, onRuntimeStatusChange, sessionId, triggerRender]);

  const ensureInstance = useCallback((info: TerminalInfo) => {
    const existing = getInstance(info.terminalId);
    if (existing) {
      if (info.cwd && info.cwd !== existing.cwd) existing.cwd = info.cwd;
      if (info.backend && info.backend !== existing.backend) existing.backend = info.backend;
      return existing;
    }

    const { terminal, fitAddon } = createXtermInstance(isDarkTheme);
    const inst: TerminalInstance = {
      terminalId: info.terminalId,
      kind: info.kind,
      xterm: terminal,
      fitAddon,
      socket: null,
      connectedSessionId: null,
      connectionState: "idle",
      errorMessage: "",
      outputBuffer: [],
      outputFrame: null,
      writeQueue: [],
      queuedWriteChars: 0,
      isWriting: false,
      lastResize: null,
      supportsResize: false,
      cwd: info.cwd || "",
      backend: info.backend || "subprocess",
      managedOutputOffset: null,
    };
    instancesRef.current.set(info.terminalId, inst);

    if (info.kind === "interactive") {
      const dataDisposable = terminal.onData((data) => {
        sendSocketMessage(info.terminalId, { type: "input", data });
      });
      dataDisposablesRef.current.set(info.terminalId, dataDisposable);
    }

    const keyDisposable = terminal.onKey(({ domEvent }) => {
      if ((domEvent.ctrlKey || domEvent.metaKey) && domEvent.key.toLowerCase() === "k") {
        domEvent.preventDefault();
        terminal.clear();
      }
    });
    keyDisposablesRef.current.set(info.terminalId, keyDisposable);

    return inst;
  }, [getInstance, isDarkTheme, sendSocketMessage]);

  useEffect(() => {
    const root = document.documentElement;
    const updateTheme = () => {
      setIsDarkTheme(root.classList.contains("dark"));
    };
    updateTheme();
    const observer = new MutationObserver(updateTheme);
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const theme = getXtermTheme(isDarkTheme);
    for (const [, inst] of instancesRef.current) {
      inst.xterm.options.theme = theme;
    }
  }, [isDarkTheme]);

  const disposeInstance = useCallback((terminalId: string) => {
    const inst = instancesRef.current.get(terminalId);
    if (!inst) return;
    dataDisposablesRef.current.get(terminalId)?.dispose();
    dataDisposablesRef.current.delete(terminalId);
    keyDisposablesRef.current.get(terminalId)?.dispose();
    keyDisposablesRef.current.delete(terminalId);
    if (inst.socket) { inst.socket.close(); inst.socket = null; }
    if (inst.outputFrame !== null) window.cancelAnimationFrame(inst.outputFrame);
    inst.xterm.dispose();
    instancesRef.current.delete(terminalId);
    containerRefs.current.delete(terminalId);
    openedSetRef.current.delete(terminalId);
    resizeTimersRef.current.delete(terminalId);
    const reconnectTimer = reconnectTimersRef.current.get(terminalId);
    if (reconnectTimer !== undefined) { window.clearTimeout(reconnectTimer); reconnectTimersRef.current.delete(terminalId); }
  }, []);

  // Sync instances with terminalInfos
  useEffect(() => {
    if (!isOpen) return;
    const currentIds = new Set(terminalInfos.map((t) => t.terminalId));
    let newProcessId: string | null = null;
    for (const info of terminalInfos) {
      const isNew = !instancesRef.current.has(info.terminalId);
      ensureInstance(info);
      if (
        isNew &&
        !newProcessId &&
        info.kind === "managed-process" &&
        (info.status === "running" || info.status === "orphaned")
      ) {
        newProcessId = info.terminalId;
      }
    }
    for (const [id] of instancesRef.current) {
      if (!currentIds.has(id)) {
        disposeInstance(id);
      }
    }
    // Auto-switch to new AI process tab
    if (newProcessId) {
      onActiveTerminalChange(newProcessId);
    }
  }, [terminalInfos, isOpen, ensureInstance, disposeInstance, onActiveTerminalChange]);

  // Auto-select active tab
  useEffect(() => {
    if (!isOpen || terminalInfos.length === 0) return;
    if (activeTerminalId && terminalInfos.some((t) => t.terminalId === activeTerminalId)) return;
    const defaultTerminal = terminalInfos.find((t) => t.isDefault);
    onActiveTerminalChange(defaultTerminal?.terminalId ?? terminalInfos[0].terminalId);
  }, [isOpen, terminalInfos, activeTerminalId, onActiveTerminalChange]);

  // Open xterm in container when active tab changes & re-fit
  useEffect(() => {
    if (!isOpen || !activeTerminalId) return;
    const inst = getInstance(activeTerminalId);
    if (!inst) return;
    const activeInfo = terminalInfos.find((terminal) => terminal.terminalId === activeTerminalId);
    if (!activeInfo) return;
    const container = containerRefs.current.get(activeTerminalId);
    if (!container) return;

    if (!openedSetRef.current.has(activeTerminalId)) {
      inst.xterm.open(container);
      openedSetRef.current.add(activeTerminalId);
    }

    // Delay fit + connect until the container is actually visible (raf isn't always enough)
    const fitRaf = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        fitTerminal(activeTerminalId);
        const shouldFocus = consumeTerminalFocusRequest(activeTerminalId);
        if (activeInfo.kind === "interactive" && shouldFocus) {
          inst.xterm.focus();
        }
        if (activeInfo.kind === "interactive" && inst.connectionState === "idle") {
          connectTerminal(activeTerminalId);
        }
        if (activeInfo.kind === "managed-process") {
          void loadManagedProcessOutput(activeTerminalId);
        }
      });
    });

    return () => window.cancelAnimationFrame(fitRaf);
  }, [isOpen, activeTerminalId, terminalInfos, getInstance, fitTerminal, connectTerminal, consumeTerminalFocusRequest, loadManagedProcessOutput]);

  // Connect all interactive terminals when panel opens
  useEffect(() => {
    if (!isOpen || !sessionId) return;
    for (const info of terminalInfos) {
      if (info.kind === "interactive" && info.isAlive) {
        const inst = getInstance(info.terminalId);
        if (inst && inst.connectionState === "idle") {
          connectTerminal(info.terminalId);
        }
      }
    }
  }, [isOpen, sessionId, terminalInfos, getInstance, connectTerminal]);

  // ResizeObserver on the panel container
  useEffect(() => {
    if (!isOpen) return;
    const el = panelContainerRef.current;
    if (!el) return;
    resizeObserverRef.current = new ResizeObserver(() => {
      if (activeTerminalId) fitTerminal(activeTerminalId);
    });
    resizeObserverRef.current.observe(el);
    return () => {
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
    };
  }, [isOpen, activeTerminalId, fitTerminal]);

  // Auto-reconnect disconnected terminals
  useEffect(() => {
    if (!isOpen || !sessionId) return;
    const reconnectIds: string[] = [];
    for (const info of terminalInfos) {
      if (info.kind !== "interactive" || !info.isAlive) continue;
      const inst = getInstance(info.terminalId);
      if (inst && inst.connectionState === "closed") {
        reconnectIds.push(info.terminalId);
      }
    }
    if (reconnectIds.length === 0) return;

    const timers = reconnectTimersRef.current;
    for (const id of reconnectIds) {
      if (timers.has(id)) continue;
      timers.set(id, window.setTimeout(() => {
        timers.delete(id);
        connectTerminal(id);
      }, 1200));
    }
    return () => {
      for (const id of reconnectIds) {
        const t = timers.get(id);
        if (t !== undefined) { window.clearTimeout(t); timers.delete(id); }
      }
    };
  }, [isOpen, sessionId, terminalInfos, getInstance, connectTerminal]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      for (const [, inst] of instancesRef.current) {
        if (inst.socket) inst.socket.close();
        if (inst.outputFrame !== null) window.cancelAnimationFrame(inst.outputFrame);
        inst.xterm.dispose();
      }
      instancesRef.current.clear();
      containerRefs.current.clear();
      openedSetRef.current.clear();
      for (const [, d] of dataDisposablesRef.current) d.dispose();
      for (const [, d] of keyDisposablesRef.current) d.dispose();
      for (const [, t] of reconnectTimersRef.current) window.clearTimeout(t);
      for (const [, t] of resizeTimersRef.current) window.clearTimeout(t);
    };
  }, []);

  // Close sockets when panel closes
  useEffect(() => {
    if (isOpen) return;
    pendingFocusTerminalIdRef.current = null;
    pendingFocusActiveTerminalRef.current = false;
    for (const [, inst] of instancesRef.current) {
      if (inst.socket) { inst.socket.close(); inst.socket = null; }
      inst.connectionState = "idle";
    }
  }, [isOpen]);

  const handleClear = useCallback(() => {
    if (!activeTerminalId) return;
    clearQueuedOutput(activeTerminalId);
    const inst = getInstance(activeTerminalId);
    inst?.xterm.clear();
    sendSocketMessage(activeTerminalId, { type: "clear" });
  }, [activeTerminalId, clearQueuedOutput, getInstance, sendSocketMessage]);

  const handleInterrupt = useCallback(() => {
    if (!activeTerminalId) return;
    sendSocketMessage(activeTerminalId, { type: "interrupt" });
    getInstance(activeTerminalId)?.xterm.focus();
  }, [activeTerminalId, getInstance, sendSocketMessage]);

  const handleCreateTerminal = useCallback(() => {
    const preferredCwd =
      (activeTerminalId ? getInstance(activeTerminalId)?.cwd : null)
      || terminalInfos.find((terminal) => terminal.isDefault)?.cwd
      || undefined;
    void onCreateTerminal(preferredCwd).then((terminalId) => {
      if (!terminalId) return;
      requestTerminalFocus(terminalId);
      onActiveTerminalChange(terminalId);
    });
  }, [activeTerminalId, getInstance, onActiveTerminalChange, onCreateTerminal, requestTerminalFocus, terminalInfos]);

  const handleCloseTab = useCallback((terminalId: string) => {
    const info = terminalInfos.find((t) => t.terminalId === terminalId);
    if (!info) return;
    if (info.isDefault) return;
    if (info.kind === "managed-process") {
      onTerminateProcess(terminalId);
      return;
    }
    void onCloseTerminal(terminalId);
  }, [onCloseTerminal, onTerminateProcess, terminalInfos]);

  const handleSelectTerminal = useCallback((terminalId: string) => {
    requestTerminalFocus(terminalId);
    onActiveTerminalChange(terminalId);
    if (terminalId === activeTerminalId) {
      getInstance(terminalId)?.xterm.focus();
      pendingFocusTerminalIdRef.current = null;
    }
  }, [activeTerminalId, getInstance, onActiveTerminalChange, requestTerminalFocus]);

  const handleToggleTerminal = useCallback(() => {
    if (!isOpen) requestTerminalFocus(activeTerminalId);
    onToggle();
  }, [activeTerminalId, isOpen, onToggle, requestTerminalFocus]);

  const activeInfo = activeTerminalId
    ? terminalInfos.find((terminal) => terminal.terminalId === activeTerminalId) ?? null
    : null;
  const activeInst = activeTerminalId ? getInstance(activeTerminalId) : null;

  const connectionLabel = activeInfo?.kind === "managed-process"
    ? (
      activeInfo.status === "running"
        ? "运行中"
        : activeInfo.status === "orphaned"
          ? "后台运行"
          : activeInfo.status === "completed"
            ? "已完成"
            : activeInfo.status === "terminated"
              ? "已终止"
              : activeInfo.status === "unknown"
                ? "状态未知"
                : activeInfo.status || "进程中"
    )
    : activeInst?.connectionState === "open"
      ? "已连接"
      : activeInst?.connectionState === "connecting"
        ? "连接中"
        : activeInst?.connectionState === "error"
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
            {/* Tab bar */}
            <div className="flex items-center h-9 shrink-0 bg-muted/30 border-b px-1 gap-0.5 overflow-x-auto">
              {terminalInfos.map((info) => {
                const inst = getInstance(info.terminalId);
                const isActive = info.terminalId === activeTerminalId;
                const isConnected = inst?.connectionState === "open";
                const hasError = inst?.connectionState === "error";
                return (
                  <button
                    key={info.terminalId}
                    onClick={() => handleSelectTerminal(info.terminalId)}
                    className={`
                      flex items-center gap-1.5 h-7 px-2.5 rounded-t text-[11px] shrink-0
                      transition-colors relative group border border-b-0 border-transparent
                      ${isActive
                        ? "bg-background text-foreground border-border"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                      }
                    `}
                    title={info.kind === "managed-process" ? info.command ?? info.name : info.cwd ?? info.name}
                  >
                    <TerminalIcon className="w-3 h-3 shrink-0" />
                    <span className="truncate max-w-[120px]">{info.kind === "managed-process" ? (info.command?.split(" ").slice(0, 2).join(" ") ?? info.terminalId) : info.name}</span>
                    {isConnected && (
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500/80 shrink-0" />
                    )}
                    {hasError && (
                      <span className="h-1.5 w-1.5 rounded-full bg-destructive/80 shrink-0" />
                    )}
                    {!info.isDefault && (
                      <span
                        onClick={(e) => { e.stopPropagation(); handleCloseTab(info.terminalId); }}
                        className="ml-0.5 opacity-0 group-hover:opacity-100 transition-opacity hover:text-destructive"
                      >
                        <X className="w-3 h-3" />
                      </span>
                    )}
                    {isActive && (
                      <span className="absolute bottom-0 left-0 right-0 h-[2px] bg-primary" />
                    )}
                  </button>
                );
              })}
              <Button
                variant="ghost"
                size="icon"
                onClick={handleCreateTerminal}
                className="h-7 w-7 shrink-0 text-muted-foreground hover:text-foreground hover:bg-muted/60"
                title="新建终端"
              >
                <Plus className="w-3.5 h-3.5" />
              </Button>
              <div className="flex-1" />
              <div className="flex items-center gap-0.5 pr-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleInterrupt}
                  disabled={!activeInst || activeInst.connectionState !== "open" || activeInst.kind === "managed-process"}
                  className="h-7 px-2 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                  title="发送 Ctrl+C 中断"
                >
                  Ctrl+C
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onRefreshTerminals}
                  className="h-7 w-7 text-muted-foreground hover:bg-muted hover:text-foreground"
                  title="刷新终端列表"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleClear}
                  disabled={!activeInst || activeInst.kind === "managed-process"}
                  className="h-7 w-7 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                  title="清空终端"
                >
                  <Eraser className="w-3.5 h-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleToggleTerminal}
                  className="h-7 w-7 text-muted-foreground hover:bg-muted hover:text-foreground"
                  title="关闭终端面板"
                >
                  <ChevronDown className="w-4 h-4" />
                </Button>
              </div>
            </div>

            {/* Status bar for active terminal */}
            <div className="flex items-center h-7 shrink-0 bg-muted/20 border-b px-3 gap-2">
              <div className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground">
                <Badge variant="secondary" className="font-mono text-[10px] uppercase">
                  {activeInst?.backend === "winpty" ? "PTY" : activeInst?.backend === "managed" ? "AI" : "PIPE"}
                </Badge>
                <Badge
                  variant={activeInst?.connectionState === "open" ? "secondary" : activeInst?.connectionState === "error" ? "destructive" : "outline"}
                  className="font-mono text-[10px]"
                >
                  {connectionLabel}
                </Badge>
                <span className="truncate font-mono text-[11px]" title={activeInst?.cwd || "当前目录"}>
                  {activeInst?.cwd || "等待终端就绪"}
                </span>
              </div>
              {activeInst?.kind === "managed-process" && activeTerminalId && (
                <Button
                  size="xs"
                  variant="destructive"
                  onClick={() => onTerminateProcess(activeTerminalId)}
                  className="ml-auto"
                >
                  <Square className="size-3 fill-current" />
                  终止进程
                </Button>
              )}
            </div>

            {/* Terminal containers */}
            <div ref={panelContainerRef} className="relative flex-1 overflow-hidden bg-[#eef2f7] dark:bg-[#111314]">
              {terminalInfos.map((info) => {
                const isActive = info.terminalId === activeTerminalId;
                const inst = getInstance(info.terminalId);
                return (
                  <div
                    key={info.terminalId}
                    ref={(el) => {
                      if (el) containerRefs.current.set(info.terminalId, el);
                    }}
                    className={`
                      absolute inset-0 overflow-hidden px-3 py-2
                      [&_.xterm]:h-full [&_.xterm-viewport]:!overflow-y-auto
                      [&_.xterm-screen]:bg-[#eef2f7] dark:[&_.xterm-screen]:bg-[#111314]
                      [&_.xterm-viewport]:bg-[#eef2f7] dark:[&_.xterm-viewport]:bg-[#111314]
                      ${isActive ? "z-10" : "z-0 invisible pointer-events-none"}
                    `}
                    onMouseDown={() => {
                      if (isActive) inst?.xterm.focus();
                    }}
                  />
                );
              })}
              {activeInst?.errorMessage && activeInst.connectionState === "error" ? (
                <div className="pointer-events-none absolute bottom-2 left-3 z-20 rounded border border-destructive/30 bg-destructive/10 px-2 py-1 text-[11px] text-destructive">
                  {activeInst.errorMessage}
                </div>
              ) : null}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {!isOpen && (
        <button
          onClick={handleToggleTerminal}
          className="w-full h-9 flex items-center justify-center gap-2 border-t bg-background text-muted-foreground text-xs hover:text-foreground hover:bg-muted/40 transition-colors shrink-0"
        >
          <TerminalIcon className="w-3.5 h-3.5" />
          终端
          {terminalInfos.some((t) => t.kind === "interactive" && t.isAlive) ? (
            <span className="h-2 w-2 rounded-full bg-emerald-500/70" />
          ) : (
            <PlugZap className="h-3.5 w-3.5 opacity-60" />
          )}
        </button>
      )}
    </div>
  );
}
