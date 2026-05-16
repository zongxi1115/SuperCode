import { useCallback, useEffect, useRef, useState } from 'react';
import { ChatPanel } from '@/components/app/chat-panel';
import { EditorPanel } from '@/components/app/editor-panel';
import { ResizableHandle } from '@/components/app/resizable-handle';
import { Sidebar } from '@/components/app/sidebar';
import { WebPreviewPanel } from '@/components/app/web-preview-panel';
import { TerminalPanel } from '@/components/app/terminal-panel';
import { WorkspacePicker } from '@/components/app/workspace-picker';
import type {
  ChatMessage,
  ContentBlock,
  DirectoryNode,
  FileTreeNode,
  ManagedProcessPayload,
  ModelOption,
  SessionContextPayload,
  SessionHistoryItem,
  SessionPayload,
  TerminalSnapshotPayload,
  WorkspaceOption,
} from '@/lib/app-types';
import {
  clearLastSession,
  findDirectoryNode,
  getLastSession,
  hydrateMessages,
  saveLastSession,
  updateDirectoryNodeTree,
  workspaceOptionsToDirectoryNodes,
} from '@/lib/app-utils';

const DEFAULT_WEB_PREVIEW_URL = 'http://localhost:5173';

function getPreviewUrlFromToolPayload(payload: { preview_url?: unknown; output?: unknown }) {
  if (typeof payload.preview_url === 'string' && payload.preview_url.trim()) {
    return payload.preview_url;
  }
  if (
    payload.output &&
    typeof payload.output === 'object' &&
    'resolved_url' in payload.output &&
    typeof payload.output.resolved_url === 'string' &&
    payload.output.resolved_url.trim()
  ) {
    return payload.output.resolved_url;
  }
  return null;
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [fileTree, setFileTree] = useState<FileTreeNode[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [terminalOutput, setTerminalOutput] = useState('');
  const [terminalInput, setTerminalInput] = useState('');
  const [isTerminalSubmitting, setIsTerminalSubmitting] = useState(false);
  const [terminalCwd, setTerminalCwd] = useState('');
  const [terminalBackend, setTerminalBackend] = useState('subprocess');
  const [terminalSupportsInterrupt, setTerminalSupportsInterrupt] = useState(false);
  const [managedProcesses, setManagedProcesses] = useState<ManagedProcessPayload[]>([]);
  const [isStoppingProcesses, setIsStoppingProcesses] = useState(false);
  const [selectedFileContent, setSelectedFileContent] = useState('');
  const [selectedFilePath, setSelectedFilePath] = useState('');
  const [backendMode, setBackendMode] = useState<'agent' | 'demo'>('demo');
  const [startupError, setStartupError] = useState<string | null>(null);
  const [directoryTree, setDirectoryTree] = useState<DirectoryNode[]>([]);
  const [directoryExpanded, setDirectoryExpanded] = useState<Set<string>>(new Set());
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [isSessionBooting, setIsSessionBooting] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [isFileTreeCollapsed, setIsFileTreeCollapsed] = useState(false);
  const [isContextOpen, setIsContextOpen] = useState(false);
  const [isContextLoading, setIsContextLoading] = useState(false);
  const [sessionContext, setSessionContext] = useState<SessionContextPayload | null>(null);
  const [isTerminalOpen, setIsTerminalOpen] = useState(false);
  const [hasTerminalBeenOpened, setHasTerminalBeenOpened] = useState(false);
  const [isWebPreviewOpen, setIsWebPreviewOpen] = useState(false);
  const [webPreviewUrl, setWebPreviewUrl] = useState(DEFAULT_WEB_PREVIEW_URL);
  const [elementAttachments, setElementAttachments] = useState<{ id: string; selector: string; html: string }[]>([]);
  const [chatPanelWidth, setChatPanelWidth] = useState(820);
  const [sessionHistory, setSessionHistory] = useState<SessionHistoryItem[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const activeRequestRef = useRef<AbortController | null>(null);

  const applyTerminalSnapshot = useCallback((data: Partial<TerminalSnapshotPayload>) => {
    setTerminalOutput((prev) => data.output ?? prev);
    setTerminalCwd((prev) => data.cwd ?? prev);
    setTerminalBackend((prev) => data.backend ?? prev);
    setTerminalSupportsInterrupt((prev) => data.supportsInterrupt ?? prev);
  }, []);

  const refreshTerminalState = useCallback(
    async (options?: {
      targetSessionId?: string;
      includeFileTree?: boolean;
      includeProcesses?: boolean;
      silent?: boolean;
    }) => {
      const currentSessionId = options?.targetSessionId ?? sessionId;
      if (!currentSessionId) {
        if (options?.includeProcesses) {
          setManagedProcesses([]);
        }
        return;
      }

      try {
        const query = new URLSearchParams();
        if (options?.includeFileTree) {
          query.set('include_file_tree', 'true');
        }
        if (options?.includeProcesses) {
          query.set('include_processes', 'true');
        }
        const res = await fetch(
          `http://localhost:8000/api/sessions/${currentSessionId}/terminal${query.size ? `?${query.toString()}` : ''}`
        );
        if (!res.ok) {
          throw new Error('读取终端状态失败');
        }
        const data: TerminalSnapshotPayload = await res.json();
        applyTerminalSnapshot(data);
        if (Array.isArray(data.fileTree)) {
          setFileTree(data.fileTree);
        }
        if (options?.includeProcesses) {
          setManagedProcesses(Array.isArray(data.processes) ? data.processes : []);
        }
      } catch (error) {
        if (!options?.silent) {
          console.error(error);
        }
      }
    },
    [applyTerminalSnapshot, sessionId]
  );

  const refreshFileTreeAfterTerminalActivity = useCallback(
    (targetSessionId?: string) => {
      void refreshTerminalState({
        targetSessionId,
        includeFileTree: true,
        includeProcesses: isTerminalOpen,
        silent: true,
      });
    },
    [isTerminalOpen, refreshTerminalState]
  );

  const loadSessionContext = useCallback(
    async (options?: { silent?: boolean; targetSessionId?: string }) => {
      const targetSessionId = options?.targetSessionId ?? sessionId;
      if (!targetSessionId) return;

      const silent = options?.silent ?? false;
      if (!silent) {
        setIsContextLoading(true);
      }

      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${targetSessionId}/context`);
        if (!res.ok) {
          throw new Error('读取上下文失败');
        }
        const data: SessionContextPayload = await res.json();
        setSessionContext(data);
      } catch (error) {
        console.error(error);
      } finally {
        if (!silent) {
          setIsContextLoading(false);
        }
      }
    },
    [sessionId]
  );

  const [shouldRestoreSession] = useState(() => {
    const lastSession = getLastSession();
    return !!(lastSession && lastSession.workspace);
  });

  const [initialWorkspace] = useState(() => {
    const lastSession = getLastSession();
    return lastSession?.workspace ?? '';
  });

  const [showWorkspacePicker, setShowWorkspacePicker] = useState(() => {
    const lastSession = getLastSession();
    return !(lastSession && lastSession.workspace);
  });

  const [customWorkspace, setCustomWorkspace] = useState(() => {
    const lastSession = getLastSession();
    return lastSession?.workspace ?? '';
  });

  const [selectedWorkspace, setSelectedWorkspace] = useState(() => {
    const lastSession = getLastSession();
    return lastSession?.workspace ?? '';
  });

  useEffect(() => {
    fetch('http://localhost:8000/api/workspaces')
      .then((res) => res.json())
      .then((data: { workspaces: WorkspaceOption[] }) => {
        const options = data.workspaces ?? [];
        setDirectoryTree(workspaceOptionsToDirectoryNodes(options));
        if (data.workspaces?.length && !initialWorkspace) {
          setSelectedWorkspace(data.workspaces[0].value);
        }
      })
      .catch(console.error);

    fetch('http://localhost:8000/api/models')
      .then((res) => res.json())
      .then((data: { models: ModelOption[] }) => {
        setModelOptions(data.models ?? []);
      })
      .catch(console.error);
  }, [initialWorkspace]);

  const applySessionPayload = useCallback((data: SessionPayload) => {
    setSessionId(data.sessionId);
    setBackendMode(data.mode);
    setStartupError(data.startupError ?? null);
    setSelectedWorkspace(data.workspace);
    setSelectedModelId(data.model ?? null);
    setMessages(hydrateMessages(data.messages ?? [], data.thoughts, data.toolCalls));
    setFileTree(data.fileTree ?? []);
    setTerminalOutput(data.terminalOutput ?? '');
    setTerminalCwd(data.workspace ?? '');
    setTerminalBackend('subprocess');
    setTerminalSupportsInterrupt(false);
    setManagedProcesses([]);
    setWebPreviewUrl(data.previewUrl ?? DEFAULT_WEB_PREVIEW_URL);
    setSelectedFilePath(data.selectedFilePath ?? '');
    setSelectedFileContent(data.selectedFileContent ?? '');
    setSessionContext(null);
    setIsContextOpen(false);
    setIsTerminalOpen(false);
    setHasTerminalBeenOpened(false);
    saveLastSession(data.workspace);
    setShowWorkspacePicker(false);
  }, []);

  const loadSessionHistory = useCallback(async () => {
    setIsHistoryLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/sessions/history');
      if (!res.ok) {
        throw new Error('读取历史会话失败');
      }
      const data = await res.json();
      setSessionHistory(data.sessions ?? []);
    } catch (error) {
      console.error(error);
    } finally {
      setIsHistoryLoading(false);
    }
  }, []);

  const createSessionWithWorkspace = useCallback(async (workspace: string) => {
    setIsSessionBooting(true);
    setSessionError(null);

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 60000);

      const res = await fetch('http://localhost:8000/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace, model: selectedModelId }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(errorText || '创建会话失败');
      }
      const data: SessionPayload = await res.json();
      applySessionPayload(data);
      await loadSessionHistory();
    } catch (error) {
      console.error(error);
      if (error instanceof DOMException && error.name === 'AbortError') {
        setSessionError('创建会话超时（60秒），请检查后端是否正常运行');
      } else {
        setSessionError(error instanceof Error ? error.message : '创建会话失败');
      }
    } finally {
      setIsSessionBooting(false);
    }
  }, [applySessionPayload, loadSessionHistory, selectedModelId]);

  const hasRestoredRef = useRef(false);

  useEffect(() => {
    if (hasRestoredRef.current) return;
    if (!shouldRestoreSession || !initialWorkspace) return;

    hasRestoredRef.current = true;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 45000);

    createSessionWithWorkspace(initialWorkspace)
      .catch((err) => {
        console.error('自动恢复会话失败:', err);
        setShowWorkspacePicker(true);
        clearLastSession();
      })
      .finally(() => clearTimeout(timeoutId));
  }, [shouldRestoreSession, initialWorkspace, createSessionWithWorkspace]);

  useEffect(() => {
    void loadSessionHistory();
  }, [loadSessionHistory]);

  useEffect(() => {
    if (!sessionId || !hasTerminalBeenOpened || !isTerminalOpen) return;

    const pollTerminalState = () =>
      refreshTerminalState({
        targetSessionId: sessionId,
        includeProcesses: true,
        silent: true,
      });

    void pollTerminalState();
    const intervalId = setInterval(pollTerminalState, 1000);
    return () => clearInterval(intervalId);
  }, [hasTerminalBeenOpened, isTerminalOpen, refreshTerminalState, sessionId]);

  const createSession = async () => {
    const workspace = customWorkspace.trim() || selectedWorkspace;
    if (!workspace) {
      setSessionError('请选择或输入一个工作区路径');
      return;
    }
    await createSessionWithWorkspace(workspace);
  };

  const loadDirectoryChildren = async (path: string) => {
    const existing = findDirectoryNode(directoryTree, path);
    if (existing?.loaded) {
      return;
    }

    try {
      const query = new URLSearchParams({ path });
      const res = await fetch(`http://localhost:8000/api/directories?${query.toString()}`);
      const data = await res.json();
      const children = workspaceOptionsToDirectoryNodes(data.children ?? []);
      setDirectoryTree((prev) =>
        updateDirectoryNodeTree(prev, path, (node) => ({
          ...node,
          children,
          loaded: true
        }))
      );
    } catch (error) {
      console.error(error);
    }
  };

  const handleDirectoryExpandedChange = (nextExpanded: Set<string>) => {
    const currentExpanded = directoryExpanded;
    setDirectoryExpanded(nextExpanded);
    for (const path of nextExpanded) {
      if (!currentExpanded.has(path)) {
        void loadDirectoryChildren(path);
      }
    }
  };

  const loadFile = async (path: string) => {
    if (!sessionId) return;

    setSelectedFilePath(path);
    try {
      const query = new URLSearchParams({ session_id: sessionId, path });
      const res = await fetch(`http://localhost:8000/api/files?${query.toString()}`);
      const data = await res.json();
      setSelectedFilePath(data.selectedFilePath ?? path);
      setSelectedFileContent(data.selectedFileContent ?? '');
    } catch (error) {
      console.error(error);
    }
  };

  useEffect(() => {
    if (!sessionId) return;
    void loadSessionContext({ silent: true });
  }, [loadSessionContext, sessionId]);

  const sendTerminalCommand = useCallback(async () => {
    if (!sessionId || isTerminalSubmitting) {
      return;
    }

    const command = terminalInput;
    setTerminalInput('');
    setIsTerminalSubmitting(true);
    try {
      const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/terminal/input`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command, submit: true }),
      });
      if (!res.ok) {
        throw new Error('终端命令发送失败');
      }
      const data: TerminalSnapshotPayload = await res.json();
      applyTerminalSnapshot(data);
      refreshFileTreeAfterTerminalActivity(sessionId);
    } catch (error) {
      console.error(error);
    } finally {
      setIsTerminalSubmitting(false);
    }
  }, [applyTerminalSnapshot, isTerminalSubmitting, refreshFileTreeAfterTerminalActivity, sessionId, terminalInput]);

  const interruptTerminal = useCallback(async () => {
    if (!sessionId || isTerminalSubmitting || !terminalSupportsInterrupt) {
      return;
    }

    setIsTerminalSubmitting(true);
    try {
      const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/terminal/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'interrupt' }),
      });
      if (!res.ok) {
        throw new Error('终端中断失败');
      }
      const data: TerminalSnapshotPayload = await res.json();
      applyTerminalSnapshot(data);
      refreshFileTreeAfterTerminalActivity(sessionId);
    } catch (error) {
      console.error(error);
    } finally {
      setIsTerminalSubmitting(false);
    }
  }, [applyTerminalSnapshot, isTerminalSubmitting, refreshFileTreeAfterTerminalActivity, sessionId, terminalSupportsInterrupt]);

  const clearTerminal = useCallback(async () => {
    if (!sessionId || isTerminalSubmitting) {
      return;
    }

    setIsTerminalSubmitting(true);
    try {
      const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/terminal/clear`, {
        method: 'POST',
      });
      if (!res.ok) {
        throw new Error('终端清空失败');
      }
      const data: TerminalSnapshotPayload = await res.json();
      applyTerminalSnapshot(data);
    } catch (error) {
      console.error(error);
    } finally {
      setIsTerminalSubmitting(false);
    }
  }, [applyTerminalSnapshot, isTerminalSubmitting, sessionId]);

  const handleTerminalToggle = useCallback(() => {
    setHasTerminalBeenOpened(true);
    setIsTerminalOpen((prev) => !prev);
  }, []);

  const terminateManagedProcess = useCallback(
    async (terminalId: string) => {
      if (!sessionId || !terminalId) return;
      setIsStoppingProcesses(true);
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/processes/${terminalId}/terminate`, {
          method: 'POST',
        });
        if (!res.ok) {
          throw new Error('终止 AI 进程失败');
        }
        await refreshTerminalState({
          targetSessionId: sessionId,
          includeProcesses: true,
        });
      } catch (error) {
        console.error(error);
      } finally {
        setIsStoppingProcesses(false);
      }
    },
    [refreshTerminalState, sessionId]
  );

  const stopManagedProcesses = useCallback(
    async (targetSessionId?: string) => {
      const currentSessionId = targetSessionId ?? sessionId;
      if (!currentSessionId) return;
      setIsStoppingProcesses(true);
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${currentSessionId}/stop`, {
          method: 'POST',
        });
        if (!res.ok) {
          throw new Error('停止 AI 执行失败');
        }
        const data = await res.json();
        setManagedProcesses(Array.isArray(data.remaining) ? data.remaining : []);
      } catch (error) {
        console.error(error);
      } finally {
        setIsStoppingProcesses(false);
      }
    },
    [sessionId]
  );

  const handleContextOpenChange = useCallback(
    (open: boolean) => {
      setIsContextOpen(open);
      if (open) {
        void loadSessionContext();
      }
    },
    [loadSessionContext]
  );

  const restoreSession = useCallback(
    async (targetSessionId: string) => {
      if (!targetSessionId || targetSessionId === sessionId) {
        return;
      }

      setIsSessionBooting(true);
      setSessionError(null);
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);

        const res = await fetch(`http://localhost:8000/api/sessions/${targetSessionId}`, {
          signal: controller.signal,
        });
        clearTimeout(timeoutId);

        if (!res.ok) {
          throw new Error('恢复历史会话失败');
        }
        const data: SessionPayload = await res.json();
        applySessionPayload(data);
      } catch (error) {
        console.error(error);
        if (error instanceof DOMException && error.name === 'AbortError') {
          setSessionError('恢复会话超时，请重试');
        } else {
          setSessionError(error instanceof Error ? error.message : '恢复历史会话失败');
        }
      } finally {
        setIsSessionBooting(false);
      }
    },
    [applySessionPayload, sessionId]
  );

  const handleModelChange = useCallback(
    async (modelId: string) => {
      if (!sessionId) return;
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/model`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: modelId }),
        });
        if (!res.ok) {
          const errText = await res.text();
          throw new Error(errText || '切换模型失败');
        }
        const data = await res.json();
        setSelectedModelId(data.model ?? modelId);
        setBackendMode(data.mode ?? 'agent');
        setStartupError(null);
        setSessionError(null);
        setWebPreviewUrl(data.previewUrl ?? DEFAULT_WEB_PREVIEW_URL);
        setSessionContext((prev) =>
          prev
            ? {
                ...prev,
                model: data.model ?? prev.model,
                mode: data.mode ?? prev.mode,
              }
            : prev
        );
      } catch (error) {
        console.error(error);
        setSessionError(error instanceof Error ? error.message : '切换模型失败');
      }
    },
    [sessionId],
  );

  const handleNewSession = useCallback(() => {
    void createSessionWithWorkspace(selectedWorkspace);
  }, [createSessionWithWorkspace, selectedWorkspace]);

  const handleDeleteHistory = useCallback(
    async (targetSessionId: string) => {
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${targetSessionId}`, {
          method: 'DELETE',
        });
        if (!res.ok) {
          throw new Error('删除历史会话失败');
        }

        const remainingItems = sessionHistory.filter((item) => item.sessionId !== targetSessionId);
        setSessionHistory(remainingItems);

        if (targetSessionId !== sessionId) {
          return;
        }

        const nextItem = remainingItems[0];
        if (nextItem) {
          await restoreSession(nextItem.sessionId);
          return;
        }

        setSessionId(null);
        setMessages([]);
        setFileTree([]);
        setTerminalOutput('');
        setTerminalCwd('');
        setTerminalBackend('subprocess');
        setTerminalSupportsInterrupt(false);
        setSelectedFileContent('');
        setSelectedFilePath('');
        setSessionContext(null);
        setIsContextOpen(false);
        setShowWorkspacePicker(true);
        clearLastSession();
      } catch (error) {
        console.error(error);
        setSessionError(error instanceof Error ? error.message : '删除历史会话失败');
      } finally {
        void loadSessionHistory();
      }
    },
    [loadSessionHistory, restoreSession, sessionHistory, sessionId]
  );

  const sendMessage = async (msg: string) => {
    if (!msg.trim() || !sessionId || isLoading) return;

    setInput('');
    setIsLoading(true);
    const abortController = new AbortController();
    activeRequestRef.current = abortController;
    setMessages((prev) => [...prev, { id: Math.random().toString(), role: 'user', content: msg }]);

    try {
      const res = await fetch('http://localhost:8000/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: msg }),
        signal: abortController.signal,
      });

      if (!res.body) return;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentAssistantId = '';
      const toolNamesById = new Map<string, string>();

      const updateAssistantMessage = (
        assistantId: string,
        updater: (message: ChatMessage) => ChatMessage
      ) => {
        setMessages((prev) => {
          let found = false;
          const next = prev.map((message) => {
            if (message.id === assistantId && message.role === 'assistant') {
              found = true;
              return updater(message);
            }
            return message;
          });

          if (found) {
            return next;
          }

          return [
            ...next,
            updater({ id: assistantId, role: 'assistant', content: '', thoughts: '', toolCalls: [], parts: [] })
          ];
        });
      };

      const processEvent = async (eventStr: string) => {
        if (!eventStr.startsWith('data: ')) return;

        try {
          const rawData = eventStr
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.replace(/^data:\s?/, ''))
            .join('\n');
          if (!rawData || rawData === '[DONE]') return;

          const data = JSON.parse(rawData);
          const appendToLastPart = (message: ChatMessage, partType: 'thinking' | 'text', delta: string): ContentBlock[] => {
            const parts = message.parts ?? [];
            const last = parts[parts.length - 1];
            if (last && last.type === partType) {
              return [...parts.slice(0, -1), { ...last, text: last.text + delta }];
            }
            return [...parts, { type: partType, text: delta }];
          };

          const updateToolPart = (
            assistantId: string,
            toolCallId: string,
            updater: (toolCall: ToolCallRecord) => ToolCallRecord
          ) => {
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              toolCalls: (message.toolCalls ?? []).map((tc) =>
                tc.id === toolCallId ? updater(tc) : tc
              ),
              parts: (message.parts ?? []).map((part) =>
                part.type === 'tool_call' && part.toolCall.id === toolCallId
                  ? { ...part, toolCall: updater(part.toolCall) }
                  : part
              )
            }));
          };

          const upsertToolPart = (
            assistantId: string,
            toolCallId: string,
            createToolCall: () => ToolCallRecord,
            updater: (toolCall: ToolCallRecord) => ToolCallRecord
          ) => {
            updateAssistantMessage(assistantId, (message) => {
              let found = false;
              const toolCalls = (message.toolCalls ?? []).map((tc) => {
                if (tc.id !== toolCallId) return tc;
                found = true;
                return updater(tc);
              });
              const nextToolCalls = found ? toolCalls : [...toolCalls, updater(createToolCall())];

              let foundPart = false;
              const parts = (message.parts ?? []).map((part) => {
                if (part.type !== 'tool_call' || part.toolCall.id !== toolCallId) {
                  return part;
                }
                foundPart = true;
                return { ...part, toolCall: updater(part.toolCall) };
              });
              const nextParts = foundPart
                ? parts
                : [...parts, { type: 'tool_call' as const, toolCall: updater(createToolCall()) }];

              return {
                ...message,
                toolCalls: nextToolCalls,
                parts: nextParts
              };
            });
          };

          const handleToolResultSideEffects = (payload: Record<string, unknown>) => {
            const toolName = String(payload.name ?? '');
            const outputPayload = (
              payload.output &&
              typeof payload.output === 'object' &&
              !Array.isArray(payload.output)
            ) ? payload.output as Record<string, unknown> : undefined;
            if (
              toolName === 'execute' ||
              toolName === 'excecute' ||
              toolName === 'terminal_input' ||
              toolName === 'terminal_wait'
            ) {
              if (typeof payload.terminal_output === 'string') {
                applyTerminalSnapshot({ output: payload.terminal_output });
              } else if (typeof payload.output === 'string') {
                applyTerminalSnapshot({ output: payload.output });
              }
              refreshFileTreeAfterTerminalActivity(sessionId ?? undefined);
            }
            if (
              ['write_file', 'replace_file', 'apply_patch'].includes(toolName) ||
              (toolName === 'delete_file' && outputPayload?.requires_confirmation !== true)
            ) {
              void refreshTerminalState({
                includeFileTree: true,
                includeProcesses: isTerminalOpen,
              });
            }
            if (toolName === 'open_browser') {
              const previewUrl = getPreviewUrlFromToolPayload(payload);
              if (previewUrl) {
                setWebPreviewUrl(previewUrl);
                setIsWebPreviewOpen(true);
              }
            }
          };

          if (data.type === 'start') {
            currentAssistantId = data.messageId || currentAssistantId || Math.random().toString();
            updateAssistantMessage(currentAssistantId, (message) => message);
          } else if (data.type === 'text-delta') {
            currentAssistantId = currentAssistantId || Math.random().toString();
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...message,
              content: `${message.content}${data.delta ?? ''}`,
              parts: appendToLastPart(message, 'text', data.delta ?? '')
            }));
          } else if (data.type === 'reasoning-delta') {
            const assistantId = currentAssistantId;
            if (!assistantId) return;
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              thoughts: `${message.thoughts ?? ''}${data.delta ?? ''}`,
              parts: appendToLastPart(message, 'thinking', data.delta ?? '')
            }));
          } else if (data.type === 'tool-input-available') {
            const assistantId = currentAssistantId;
            if (!assistantId) return;
            const toolCallRecord = {
              id: String(data.toolCallId ?? Math.random()),
              name: String(data.toolName ?? 'tool'),
              arguments: data.input ?? {},
              streamedInput: undefined,
              state: 'running' as const
            };
            toolNamesById.set(toolCallRecord.id, toolCallRecord.name);
            upsertToolPart(
              assistantId,
              toolCallRecord.id,
              () => toolCallRecord,
              (toolCall) => ({
                ...toolCall,
                name: toolCallRecord.name,
                arguments: toolCallRecord.arguments,
                streamedInput: undefined,
                state: 'running'
              })
            );
            if (toolCallRecord.name === 'read_file' && typeof toolCallRecord.arguments?.filename === 'string') {
              void loadFile(toolCallRecord.arguments.filename);
            }
          } else if (data.type === 'tool-input-start') {
            const assistantId = currentAssistantId;
            const toolCallId = String(data.toolCallId ?? '');
            if (!assistantId || !toolCallId) return;
            const toolName = String(data.toolName ?? toolNamesById.get(toolCallId) ?? 'tool');
            toolNamesById.set(toolCallId, toolName);
            upsertToolPart(
              assistantId,
              toolCallId,
              () => ({ id: toolCallId, name: toolName, arguments: {}, streamedInput: '', state: 'running' }),
              (toolCall) => ({
                ...toolCall,
                name: toolName,
                streamedInput: toolCall.streamedInput ?? '',
                state: 'running'
              })
            );
          } else if (data.type === 'tool-input-delta') {
            const assistantId = currentAssistantId;
            const toolCallId = String(data.toolCallId ?? '');
            if (!assistantId || !toolCallId) return;
            const delta = String(data.inputTextDelta ?? '');
            const toolName = toolNamesById.get(toolCallId) ?? 'tool';
            upsertToolPart(
              assistantId,
              toolCallId,
              () => ({ id: toolCallId, name: toolName, arguments: {}, streamedInput: '', state: 'running' }),
              (toolCall) => ({
                ...toolCall,
                streamedInput: `${toolCall.streamedInput ?? ''}${delta}`,
                state: 'running'
              })
            );
          } else if (data.type === 'tool-output-available') {
            const assistantId = currentAssistantId;
            const toolCallId = String(data.toolCallId ?? '');
            if (!assistantId || !toolCallId) return;
            updateToolPart(assistantId, toolCallId, (toolCall) => ({
              ...toolCall,
              output: data.output,
              state: 'completed'
            }));
          } else if (data.type === 'data-tool-result') {
            const payload = (data.data ?? {}) as Record<string, unknown>;
            const assistantId = String(payload.assistant_id ?? currentAssistantId);
            const toolCallId = String(payload.id ?? '');
            if (!assistantId || !toolCallId) return;
            const toolName = String(payload.name ?? toolNamesById.get(toolCallId) ?? 'tool');
            toolNamesById.set(toolCallId, toolName);
            handleToolResultSideEffects(payload);
            const nextState =
              typeof payload.state === 'string'
                ? payload.state
                : payload.success === false
                  ? 'error'
                  : 'completed';
            updateToolPart(assistantId, toolCallId, (toolCall) => ({
              ...toolCall,
              ...payload,
              id: toolCallId,
              name: toolName,
              approval: (
                payload.approval &&
                typeof payload.approval === 'object' &&
                !Array.isArray(payload.approval)
              ) ? payload.approval as ToolCallRecord['approval'] : toolCall.approval,
              errorMessage: typeof payload.error_message === 'string' ? payload.error_message : toolCall.errorMessage,
              state: nextState as ToolCallRecord['state']
            }));
          } else if (data.type === 'data-plan-steps') {
            const steps = data.data?.steps;
            if (Array.isArray(steps)) {
              setPlanSteps(steps);
            }
          } else if (data.type === 'data-terminal-output') {
            if (typeof data.data?.output === 'string') {
              applyTerminalSnapshot({ output: data.data.output });
            }
          } else if (data.type === 'data-preview-url') {
            if (typeof data.data?.url === 'string') {
              setWebPreviewUrl(data.data.url);
              setIsWebPreviewOpen(true);
            }
          } else if (data.type === 'data-assistant-reset') {
            currentAssistantId = data.data?.id || currentAssistantId || Math.random().toString();
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...message,
              content: '',
              parts: (message.parts ?? []).filter((p) => p.type !== 'text')
            }));
          } else if (data.type === 'data-tool-call') {
            return;
          } else if (typeof data.type === 'string' && data.type.startsWith('data-')) {
            const assistantId = currentAssistantId;
            if (!assistantId) return;
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              parts: [...(message.parts ?? []), { type: 'data' as const, dataType: data.type, data: data.data }]
            }));
          } else if (data.type === 'error') {
            currentAssistantId = currentAssistantId || Math.random().toString();
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...message,
              content: `${message.content}${data.errorText ?? ''}`,
              parts: appendToLastPart(message, 'text', data.errorText ?? '')
            }));
          } else if (data.type === 'assistant_started') {
            currentAssistantId = data.payload.id || currentAssistantId || Math.random().toString();
            updateAssistantMessage(currentAssistantId, (message) => message);
          } else if (data.type === 'assistant_delta') {
            currentAssistantId = data.payload.id || currentAssistantId || Math.random().toString();
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...message,
              content: `${message.content}${data.payload.delta ?? ''}`,
              parts: appendToLastPart(message, 'text', data.payload.delta ?? '')
            }));
          } else if (data.type === 'assistant_reset') {
            currentAssistantId = data.payload.id || currentAssistantId || Math.random().toString();
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...message,
              content: '',
              parts: (message.parts ?? []).filter((p) => p.type !== 'text')
            }));
          } else if (data.type === 'thought_delta') {
            const assistantId = data.payload.assistant_id || currentAssistantId;
            if (!assistantId) return;
            currentAssistantId = assistantId;
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              thoughts: `${message.thoughts ?? ''}${data.payload.delta ?? ''}`,
              parts: appendToLastPart(message, 'thinking', data.payload.delta ?? '')
            }));
          } else if (data.type === 'thought') {
            const assistantId = data.payload.assistant_id || currentAssistantId;
            if (!assistantId) return;
            currentAssistantId = assistantId;
            updateAssistantMessage(assistantId, (message) => {
              const nextThought = String(data.payload.thought ?? '');
              if (!nextThought || message.thoughts?.trim()) {
                return message;
              }
              const newParts = appendToLastPart(message, 'thinking', nextThought);
              return {
                ...message,
                thoughts: nextThought,
                parts: newParts
              };
            });
          } else if (data.type === 'tool_call') {
            const assistantId = data.payload.assistant_id || currentAssistantId;
            if (!assistantId) return;
            currentAssistantId = assistantId;
            const toolCallRecord = { ...data.payload, state: 'running' as const };
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              toolCalls: [...(message.toolCalls ?? []), toolCallRecord],
              parts: [...(message.parts ?? []), { type: 'tool_call' as const, toolCall: toolCallRecord }]
            }));
            if (data.payload.name === 'read_file' && typeof data.payload.arguments?.filename === 'string') {
              void loadFile(data.payload.arguments.filename);
            }
          } else if (data.type === 'tool_result') {
            handleToolResultSideEffects(data.payload);
            const assistantId = data.payload.assistant_id || currentAssistantId;
            if (!assistantId) return;
            currentAssistantId = assistantId;
            const updatedTool = {
              errorMessage: data.payload.error_message ?? undefined,
              state: data.payload.success ? 'completed' as const : 'error' as const
            };
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              toolCalls: (message.toolCalls ?? []).map((tc) =>
                tc.id === data.payload.id
                  ? { ...tc, ...data.payload, errorMessage: data.payload.error_message ?? tc.errorMessage, state: data.payload.success ? 'completed' : 'error' }
                  : tc
              ),
              parts: (message.parts ?? []).map((p) =>
                p.type === 'tool_call' && p.toolCall.id === data.payload.id
                  ? { ...p, toolCall: { ...p.toolCall, ...data.payload, ...updatedTool } }
                  : p
              )
            }));
          }
        } catch (error) {
          console.error('Failed to parse SSE event', error, eventStr);
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() ?? '';

        for (const eventStr of events) {
          await processEvent(eventStr);
        }
      }

      if (buffer.trim()) {
        await processEvent(buffer);
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        return;
      }
      console.error(e);
    } finally {
      if (activeRequestRef.current === abortController) {
        activeRequestRef.current = null;
      }
      setIsLoading(false);
      void refreshTerminalState({
        includeProcesses: isTerminalOpen,
        silent: true,
      });
      void loadSessionContext({ silent: !isContextOpen });
      void loadSessionHistory();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const resolveDeleteConfirmation = useCallback(
    async (toolCallId: string, approved: boolean) => {
      if (!sessionId) return;

      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/tools/${toolCallId}/confirm-delete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ approved }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(String(data.detail ?? data.error_message ?? '确认删除失败'));
        }

        setMessages((prev) =>
          prev.map((message) => ({
            ...message,
            toolCalls: (message.toolCalls ?? []).map((toolCall) =>
              toolCall.id === toolCallId
                ? {
                    ...toolCall,
                    output: data.output,
                    success: data.success ?? toolCall.success,
                    errorMessage: data.error_message ?? toolCall.errorMessage,
                    approval: data.approval ?? toolCall.approval,
                    state: data.state ?? toolCall.state,
                  }
                : toolCall
            ),
            parts: (message.parts ?? []).map((part) =>
              part.type === 'tool_call' && part.toolCall.id === toolCallId
                ? {
                    ...part,
                    toolCall: {
                      ...part.toolCall,
                      output: data.output,
                      success: data.success ?? part.toolCall.success,
                      errorMessage: data.error_message ?? part.toolCall.errorMessage,
                      approval: data.approval ?? part.toolCall.approval,
                      state: data.state ?? part.toolCall.state,
                    },
                  }
                : part
            ),
          }))
        );

        if (data.selectedFileCleared) {
          setSelectedFilePath('');
          setSelectedFileContent('');
        }

        if (approved) {
          void refreshTerminalState({
            includeFileTree: true,
            includeProcesses: isTerminalOpen,
          });
        }
      } catch (error) {
        console.error(error);
      }
    },
    [isTerminalOpen, refreshTerminalState, sessionId]
  );

  const stopMessage = useCallback(() => {
    if (sessionId) {
      void stopManagedProcesses(sessionId);
    }
    activeRequestRef.current?.abort();
    activeRequestRef.current = null;
    setIsLoading(false);
  }, [sessionId, stopManagedProcesses]);

  const toggleSidebar = useCallback(() => {
    setIsSidebarCollapsed((prev) => !prev);
  }, []);

  const toggleFileTree = useCallback(() => {
    setIsFileTreeCollapsed((prev) => !prev);
  }, []);

  const handleSelectOtherProject = useCallback(() => {
    clearLastSession();
    setSessionId(null);
    setMessages([]);
    setFileTree([]);
    setTerminalOutput('');
    setTerminalCwd('');
    setTerminalBackend('subprocess');
    setTerminalSupportsInterrupt(false);
    setManagedProcesses([]);
    setSelectedFileContent('');
    setSelectedFilePath('');
    setBackendMode('demo');
    setStartupError(null);
    setSessionError(null);
      setSessionContext(null);
      setIsContextOpen(false);
      setIsTerminalOpen(false);
      setHasTerminalBeenOpened(false);
      setIsWebPreviewOpen(false);
      setWebPreviewUrl(DEFAULT_WEB_PREVIEW_URL);
      setElementAttachments([]);
      setShowWorkspacePicker(true);
  }, []);

  if (showWorkspacePicker || !sessionId) {
    return (
      <WorkspacePicker
        shouldRestoreSession={shouldRestoreSession}
        customWorkspace={customWorkspace}
        sessionError={sessionError}
        isSessionBooting={isSessionBooting}
        selectedWorkspace={selectedWorkspace}
        directoryTree={directoryTree}
        directoryExpanded={directoryExpanded}
        onDirectoryExpandedChange={handleDirectoryExpandedChange}
        onCustomWorkspaceChange={setCustomWorkspace}
        onSelectWorkspace={(path) => {
          setSelectedWorkspace(path);
          setCustomWorkspace('');
        }}
        onCreateSession={createSession}
      />
    );
  }

  return (
    <div className="flex h-screen bg-background text-foreground text-sm font-sans w-full overflow-hidden">
      <Sidebar
        currentSessionId={sessionId}
        historyItems={sessionHistory}
        isHistoryLoading={isHistoryLoading}
        isCollapsed={isSidebarCollapsed}
        selectedWorkspace={selectedWorkspace}
        backendMode={backendMode}
        startupError={startupError}
        width={sidebarWidth}
        onNewSession={handleNewSession}
        onSelectHistory={(targetSessionId) => void restoreSession(targetSessionId)}
        onDeleteHistory={(targetSessionId) => void handleDeleteHistory(targetSessionId)}
        onToggle={toggleSidebar}
        onSelectOtherProject={handleSelectOtherProject}
      />
      {!isSidebarCollapsed && (
        <ResizableHandle
          side="left"
          onResize={(delta) => setSidebarWidth((prev) => Math.min(Math.max(prev + delta, 220), 480))}
        />
      )}
      <div style={{ width: chatPanelWidth }} className="flex-shrink-0">
        <ChatPanel
        contextData={sessionContext}
        isContextLoading={isContextLoading}
        isContextOpen={isContextOpen}
        messages={messages}
        input={input}
        isLoading={isLoading}
        model={selectedModelId}
        modelOptions={modelOptions}
        onModelChange={handleModelChange}
        onContextOpenChange={handleContextOpenChange}
        onInputChange={setInput}
        onKeyDown={handleKeyDown}
        onSendMessage={() => void sendMessage(input)}
        onStopMessage={stopMessage}
        onResolveDeleteConfirmation={resolveDeleteConfirmation}
        elementAttachments={elementAttachments}
        onRemoveElementAttachment={(id) => setElementAttachments((prev) => prev.filter((e) => e.id !== id))}
        />
      </div>
      <ResizableHandle
        side="left"
        onResize={(delta) => setChatPanelWidth((prev) => Math.min(Math.max(prev + delta, 400), 1000))}
      />
      <div className="flex-1 flex flex-col min-w-0">
        <EditorPanel
          fileTree={fileTree}
          selectedFilePath={selectedFilePath}
          selectedFileContent={selectedFileContent}
          isFileTreeCollapsed={isFileTreeCollapsed}
          onToggleFileTree={toggleFileTree}
          onLoadFile={loadFile}
          sessionId={sessionId}
          isWebPreviewOpen={isWebPreviewOpen}
          onToggleWebPreview={() => setIsWebPreviewOpen((prev) => !prev)}
          onPreviewHtml={(content, fileName) => {
            const blob = new Blob([content], { type: 'text/html' });
            const blobUrl = URL.createObjectURL(blob);
            setWebPreviewUrl(blobUrl);
            setIsWebPreviewOpen(true);
          }}
        />
        <TerminalPanel
          output={terminalOutput}
          input={terminalInput}
          cwd={terminalCwd}
          backend={terminalBackend}
          isOpen={isTerminalOpen}
          isSubmitting={isTerminalSubmitting}
          supportsInterrupt={terminalSupportsInterrupt}
          isStoppingProcesses={isStoppingProcesses}
          processes={managedProcesses}
          onInputChange={setTerminalInput}
          onSubmit={() => void sendTerminalCommand()}
          onInterrupt={() => void interruptTerminal()}
          onToggle={handleTerminalToggle}
          onClear={() => void clearTerminal()}
          onRefreshProcesses={() => void refreshTerminalState({ includeProcesses: true })}
          onStopAllProcesses={() => void stopManagedProcesses()}
          onTerminateProcess={(terminalId) => void terminateManagedProcess(terminalId)}
        />
      </div>
      <WebPreviewPanel
        isOpen={isWebPreviewOpen}
        onToggle={() => setIsWebPreviewOpen((prev) => !prev)}
        url={webPreviewUrl}
        onUrlChange={setWebPreviewUrl}
        onSelectElement={(html, selector) => {
          setElementAttachments((prev) => [
            ...prev,
            { id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, selector, html },
          ]);
        }}
      />
    </div>
  );
}
