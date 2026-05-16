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

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [fileTree, setFileTree] = useState<FileTreeNode[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [terminalOutput, setTerminalOutput] = useState('');
  const [terminalInput, setTerminalInput] = useState('');
  const [isTerminalSubmitting, setIsTerminalSubmitting] = useState(false);
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
  const [isFileTreeCollapsed, setIsFileTreeCollapsed] = useState(false);
  const [isContextOpen, setIsContextOpen] = useState(false);
  const [isContextLoading, setIsContextLoading] = useState(false);
  const [sessionContext, setSessionContext] = useState<SessionContextPayload | null>(null);
  const [isTerminalOpen, setIsTerminalOpen] = useState(false);
  const [hasTerminalBeenOpened, setHasTerminalBeenOpened] = useState(false);
  const [isWebPreviewOpen, setIsWebPreviewOpen] = useState(false);
  const [chatPanelWidth, setChatPanelWidth] = useState(820);
  const [sessionHistory, setSessionHistory] = useState<SessionHistoryItem[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [selectedModelEnvFile, setSelectedModelEnvFile] = useState<string | null>(null);
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const activeRequestRef = useRef<AbortController | null>(null);

  const refreshFileTree = useCallback(
    async (targetSessionId?: string) => {
      const currentSessionId = targetSessionId ?? sessionId;
      if (!currentSessionId) return;

      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${currentSessionId}/file-tree`);
        if (!res.ok) {
          throw new Error('读取文件树失败');
        }
        const data = await res.json();
        if (data.fileTree) {
          setFileTree(data.fileTree);
        }
      } catch (error) {
        console.error(error);
      }
    },
    [sessionId]
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
    setSelectedModelEnvFile(data.envFile ?? null);
    setMessages(hydrateMessages(data.messages ?? [], data.thoughts, data.toolCalls));
    setFileTree(data.fileTree ?? []);
    setTerminalOutput(data.terminalOutput ?? '');
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
        body: JSON.stringify({ workspace, env_file: selectedModelEnvFile }),
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
  }, [applySessionPayload, loadSessionHistory]);

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

    const pollTerminal = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/terminal`);
        if (!res.ok) {
          return;
        }
        const data: TerminalSnapshotPayload = await res.json();
        setTerminalOutput(data.output ?? '');
      } catch {
        // silent fail for polling
      }
    };

    void pollTerminal();
    const intervalId = setInterval(pollTerminal, 1000);
    return () => clearInterval(intervalId);
  }, [hasTerminalBeenOpened, isTerminalOpen, sessionId]);

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
    if (!sessionId || !terminalInput.trim() || isTerminalSubmitting) {
      return;
    }

    const command = terminalInput.trim();
    setTerminalInput('');
    setIsTerminalSubmitting(true);
    try {
      const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/terminal/input`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command }),
      });
      if (!res.ok) {
        throw new Error('终端命令发送失败');
      }
      const data: TerminalSnapshotPayload = await res.json();
      setTerminalOutput(data.output ?? '');
    } catch (error) {
      console.error(error);
    } finally {
      setIsTerminalSubmitting(false);
    }
  }, [isTerminalSubmitting, sessionId, terminalInput]);

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
      setTerminalOutput(data.output ?? '');
    } catch (error) {
      console.error(error);
    } finally {
      setIsTerminalSubmitting(false);
    }
  }, [isTerminalSubmitting, sessionId]);

  const handleTerminalToggle = useCallback(() => {
    setHasTerminalBeenOpened(true);
    setIsTerminalOpen((prev) => !prev);
  }, []);

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
    async (envFile: string) => {
      if (!sessionId) return;
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/model`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ env_file: envFile }),
        });
        if (!res.ok) {
          const errText = await res.text();
          throw new Error(errText || '切换模型失败');
        }
        const data = await res.json();
        setSelectedModelEnvFile(data.envFile ?? envFile);
        setBackendMode(data.mode ?? 'agent');
        setStartupError(null);
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
          const data = JSON.parse(eventStr.replace('data: ', ''));
          const appendToLastPart = (message: ChatMessage, partType: 'thinking' | 'text', delta: string): ContentBlock[] => {
            const parts = message.parts ?? [];
            const last = parts[parts.length - 1];
            if (last && last.type === partType) {
              return [...parts.slice(0, -1), { ...last, text: last.text + delta }];
            }
            return [...parts, { type: partType, text: delta }];
          };

          if (data.type === 'assistant_started') {
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
            if (
              data.payload.name === 'execute' ||
              data.payload.name === 'excecute' ||
              data.payload.name === 'terminal_input' ||
              data.payload.name === 'terminal_wait'
            ) {
              if (typeof data.payload.terminal_output === 'string') {
                setTerminalOutput(data.payload.terminal_output);
              } else if (typeof data.payload.output === 'string') {
                setTerminalOutput(data.payload.output);
              }
            }
            if (['write_file', 'replace_file', 'delete_file'].includes(String(data.payload.name))) {
              void refreshFileTree();
            }
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

  const stopMessage = useCallback(() => {
    activeRequestRef.current?.abort();
    activeRequestRef.current = null;
    setIsLoading(false);
  }, []);

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
    setSelectedFileContent('');
    setSelectedFilePath('');
    setBackendMode('demo');
    setStartupError(null);
    setSessionError(null);
    setSessionContext(null);
    setIsContextOpen(false);
    setIsTerminalOpen(false);
    setHasTerminalBeenOpened(false);
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
        onNewSession={handleNewSession}
        onSelectHistory={(targetSessionId) => void restoreSession(targetSessionId)}
        onDeleteHistory={(targetSessionId) => void handleDeleteHistory(targetSessionId)}
        onToggle={toggleSidebar}
        onSelectOtherProject={handleSelectOtherProject}
      />
      <div style={{ width: chatPanelWidth }} className="flex-shrink-0">
        <ChatPanel
        contextData={sessionContext}
        isContextLoading={isContextLoading}
        isContextOpen={isContextOpen}
        messages={messages}
        input={input}
        isLoading={isLoading}
        model={selectedModelEnvFile}
        modelOptions={modelOptions}
        onModelChange={handleModelChange}
        onContextOpenChange={handleContextOpenChange}
        onInputChange={setInput}
        onKeyDown={handleKeyDown}
        onSendMessage={() => void sendMessage(input)}
        onStopMessage={stopMessage}
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
        />
        <TerminalPanel
          output={terminalOutput}
          input={terminalInput}
          isOpen={isTerminalOpen}
          isSubmitting={isTerminalSubmitting}
          onInputChange={setTerminalInput}
          onSubmit={() => void sendTerminalCommand()}
          onToggle={handleTerminalToggle}
          onClear={() => void clearTerminal()}
        />
      </div>
      <WebPreviewPanel isOpen={isWebPreviewOpen} onToggle={() => setIsWebPreviewOpen((prev) => !prev)} />
    </div>
  );
}
