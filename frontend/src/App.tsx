import { useCallback, useEffect, useRef, useState } from 'react';
import { ChatPanel } from '@/components/app/chat-panel';
import { EditorPanel, type PlanData } from '@/components/app/editor-panel';
import { ResizableHandle } from '@/components/app/resizable-handle';
import { Sidebar } from '@/components/app/sidebar';
import { TerminalPanel } from '@/components/app/terminal-panel';
import { SettingsDialog } from '@/components/app/settings-dialog';
import { WorkspacePicker } from '@/components/app/workspace-picker';
import type {
  AgentMode,
  AppSettings,
  ChatMessage,
  CodeChangeRecord,
  CompletionActionKey,
  ContentBlock,
  DirectoryNode,
  FileTreeNode,
  ManagedProcessPayload,
  ModelConfigPayload,
  ModelOption,
  RecentProject,
  SessionContextPayload,
  SessionContextCompressionPayload,
  SessionHistoryItem,
  SessionPayload,
  SkillSummary,
  TerminalSnapshotPayload,
  ToolCallRecord,
  UIModelProvider,
  WorkspaceOption,
} from '@/lib/app-types';
import {
  addRecentProject,
  clearLastSession,
  findDirectoryNode,
  getLastSession,
  getRecentProjects,
  hydrateMessages,
  removeRecentProject,
  saveLastSession,
  updateDirectoryNodeTree,
  workspaceOptionsToDirectoryNodes,
} from '@/lib/app-utils';
import {
  buildPlanDraftMarkdown,
  normalizePlanDraft,
  parseStreamingPlanDraft,
  resolvePlanDraftTitle,
} from '@/lib/plan-draft';

import { PanelRightOpen, PanelRightClose, Settings2 } from 'lucide-react';
import { Button } from '@/components/ui/button';

const DEFAULT_WEB_PREVIEW_URL = 'http://localhost:5173';
const CONTEXT_COMPRESSION_USAGE_THRESHOLD = 0.7;

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

function resolveSelectedModelId(
  data: Pick<SessionPayload, 'model' | 'modelId' | 'envFile'>,
  modelOptions: ModelOption[],
) {
  const uniqueRef = data.modelId ?? data.envFile ?? null;
  if (uniqueRef) {
    const exactMatch = modelOptions.find(
      (option) => option.id === uniqueRef || option.envFile === uniqueRef,
    );
    return exactMatch?.id ?? uniqueRef;
  }

  const modelName = data.model ?? null;
  if (!modelName) {
    return null;
  }

  const nameMatches = modelOptions.filter(
    (option) => option.name === modelName || option.model === modelName,
  );
  if (nameMatches.length === 1) {
    return nameMatches[0].id;
  }
  return null;
}

function normalizeReasoningEffort(value?: string | null) {
  const normalized = value?.trim().toLowerCase();
  return normalized ? normalized : null;
}

function decodeMentionTokenValue(value: string) {
  return value.replace(/\\\]/g, ']');
}

function extractSelectedSkillIds(message: string) {
  const skillIds: string[] = [];
  const seen = new Set<string>();
  const mentionTokenRe = /@\[((?:\\.|[^\]])*)\]/g;
  let match: RegExpExecArray | null;

  while ((match = mentionTokenRe.exec(message)) !== null) {
    const decoded = decodeMentionTokenValue(match[1] ?? '');
    if (!decoded.toLowerCase().startsWith('skill:')) {
      continue;
    }
    const skillId = decoded.split(':', 2)[1]?.trim();
    if (!skillId || seen.has(skillId)) {
      continue;
    }
    seen.add(skillId);
    skillIds.push(skillId);
  }

  return skillIds;
}

function mergeCodeChanges(
  current: CodeChangeRecord[],
  incoming: CodeChangeRecord[],
) {
  if (!incoming.length) {
    return current;
  }

  const recordsById = new Map(current.map((record) => [record.id, record]));
  for (const record of incoming) {
    if (!record?.id) continue;
    recordsById.set(record.id, record);
  }
  return Array.from(recordsById.values()).sort((a, b) => a.timestamp - b.timestamp);
}

async function readApiError(response: Response, fallback: string) {
  try {
    const text = await response.text();
    if (text.trim()) {
      try {
        const data = JSON.parse(text) as { detail?: unknown; error?: unknown; message?: unknown };
        const detail = data.detail ?? data.error ?? data.message;
        if (typeof detail === 'string' && detail.trim()) {
          return detail;
        }
      } catch {
        return text;
      }
    }
  } catch {
    // ignore read errors
  }

  return fallback;
}

async function copyTextToClipboard(text: string) {
  const value = text.trim();
  if (!value) {
    return;
  }

  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.setAttribute('readonly', 'true');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [codeChanges, setCodeChanges] = useState<CodeChangeRecord[]>([]);
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
  const [planData, setPlanData] = useState<PlanData | null>(null);
  const [backendMode, setBackendMode] = useState<'agent' | 'demo'>('demo');
  const [startupError, setStartupError] = useState<string | null>(null);
  const [directoryTree, setDirectoryTree] = useState<DirectoryNode[]>([]);
  const [directoryExpanded, setDirectoryExpanded] = useState<Set<string>>(new Set());
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [isSessionBooting, setIsSessionBooting] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isRightPanelCollapsed, setIsRightPanelCollapsed] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [isGitPanelOpen, setIsGitPanelOpen] = useState(false);  const [isContextOpen, setIsContextOpen] = useState(false);
  const [isContextLoading, setIsContextLoading] = useState(false);
  const [sessionContext, setSessionContext] = useState<SessionContextPayload | null>(null);
  const [isTerminalOpen, setIsTerminalOpen] = useState(false);
  const [hasTerminalBeenOpened, setHasTerminalBeenOpened] = useState(false);
  const [isWebPreviewOpen, setIsWebPreviewOpen] = useState(false);
  const [webPreviewUrl, setWebPreviewUrl] = useState(DEFAULT_WEB_PREVIEW_URL);
  const [elementAttachments, setElementAttachments] = useState<{ id: string; selector: string; html: string; sourceUrl?: string }[]>([]);
  const [chatPanelWidth, setChatPanelWidth] = useState(820);
  const [sessionHistory, setSessionHistory] = useState<SessionHistoryItem[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [recentProjects, setRecentProjects] = useState<RecentProject[]>(() => getRecentProjects());
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [selectedReasoningEffort, setSelectedReasoningEffort] = useState<string | null>(null);
  const [selectedAgentMode, setSelectedAgentMode] = useState<AgentMode>('auto');
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [availableSkills, setAvailableSkills] = useState<SkillSummary[]>([]);
  const [isModelConfigOpen, setIsModelConfigOpen] = useState(false);
  const [appSettings, setAppSettings] = useState<AppSettings>({ autoApprove: false });
  const [visualModelProviders, setVisualModelProviders] = useState<UIModelProvider[]>([]);
  const [envModelConfigs, setEnvModelConfigs] = useState<ModelOption[]>([]);
  const [modelConfigPath, setModelConfigPath] = useState<string | null>(null);
  const [completionActionState, setCompletionActionState] = useState<{
    messageId: string;
    action: CompletionActionKey;
  } | null>(null);
  const activeRequestRef = useRef<AbortController | null>(null);
  const activeStreamSessionIdRef = useRef<string | null>(null);
  const currentSessionIdRef = useRef<string | null>(null);

  useEffect(() => {
    currentSessionIdRef.current = sessionId;
  }, [sessionId]);

  const openPlanDraftPanel = useCallback((title: string, markdown: string) => {
    setPlanData({ title, markdown });
    setIsRightPanelCollapsed(false);
  }, []);

  const showStreamingPlanDraft = useCallback(
    (
      preview?: {
        title?: string;
        summary?: string;
        overview?: string;
        keySteps?: string[];
        markdown?: string;
      },
      fallbackTitle = '正在设计计划',
    ) => {
      const title = resolvePlanDraftTitle(preview, fallbackTitle);
      const markdown = buildPlanDraftMarkdown(preview, title);
      openPlanDraftPanel(title, markdown);
    },
    [openPlanDraftPanel],
  );

  const findAssistantIdByToolCallId = useCallback((toolCallId: string) => {
    for (const message of messages) {
      if (message.role !== 'assistant') continue;
      if ((message.toolCalls ?? []).some((toolCall) => toolCall.id === toolCallId)) {
        return message.id;
      }
    }
    return null;
  }, [messages]);

  const findToolCallById = useCallback((toolCallId: string) => {
    for (const message of messages) {
      const found = (message.toolCalls ?? []).find((toolCall) => toolCall.id === toolCallId);
      if (found) {
        return found;
      }
    }
    return null;
  }, [messages]);

  const applyTerminalSnapshot = useCallback((data: Partial<TerminalSnapshotPayload>) => {
    setTerminalOutput((prev) => data.output ?? prev);
    setTerminalCwd((prev) => data.cwd ?? prev);
    setTerminalBackend((prev) => data.backend ?? prev);
    setTerminalSupportsInterrupt((prev) => data.supportsInterrupt ?? prev);
  }, []);

  const appendCodeChanges = useCallback((incoming: CodeChangeRecord[]) => {
    setCodeChanges((prev) => {
      const merged = mergeCodeChanges(prev, incoming);
      setSessionContext((current) =>
        current
          ? {
              ...current,
              codeChangeCount: merged.length,
              recentCodeChanges: merged.slice(-8),
            }
          : current
      );
      return merged;
    });
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
        setAvailableSkills(data.availableSkills ?? []);
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

  const [shouldRestoreSession, setShouldRestoreSession] = useState(() => {
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

  const loadModels = useCallback(async () => {
    const res = await fetch('http://localhost:8000/api/models');
    const data: { models: ModelOption[] } = await res.json();
    const nextOptions = data.models ?? [];
    setModelOptions(nextOptions);
    setSelectedModelId((prev) => {
      if (prev && nextOptions.some((option) => option.id === prev)) {
        return prev;
      }
      return nextOptions[0]?.id ?? prev ?? null;
    });
    return nextOptions;
  }, []);

  const loadAppSettings = useCallback(async () => {
    const res = await fetch('http://localhost:8000/api/settings');
    const data = await res.json();
    setAppSettings(data);
    return data;
  }, []);

  const saveAppSettings = useCallback(async (settings: AppSettings) => {
    const res = await fetch('http://localhost:8000/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(String(data.detail ?? '保存设置失败'));
    }
    setAppSettings(data);
  }, []);

  const loadModelConfigs = useCallback(async () => {
    const res = await fetch('http://localhost:8000/api/model-configs');
    const data: ModelConfigPayload = await res.json();
    setVisualModelProviders(data.providers ?? []);
    setEnvModelConfigs(data.envConfigs ?? []);
    setModelConfigPath(data.configPath ?? null);
    await loadAppSettings();
    return data;
  }, [loadAppSettings]);

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
        const nextOptions = data.models ?? [];
        setModelOptions(nextOptions);
        setSelectedModelId((prev) => {
          if (prev && nextOptions.some((option) => option.id === prev)) {
            return prev;
          }
          return nextOptions[0]?.id ?? prev ?? null;
        });
      })
      .catch(console.error);

    fetch('http://localhost:8000/api/model-configs')
      .then((res) => res.json())
      .then((data: ModelConfigPayload) => {
        setVisualModelProviders(data.providers ?? []);
        setEnvModelConfigs(data.envConfigs ?? []);
        setModelConfigPath(data.configPath ?? null);
      })
      .catch(console.error);
  }, [initialWorkspace]);

  const syncVisibleSessionSnapshot = useCallback((data: SessionPayload) => {
    setBackendMode(data.mode);
    setStartupError(data.startupError ?? null);
    setSelectedModelId((prev) => resolveSelectedModelId(data, modelOptions) ?? prev ?? null);
    setSelectedReasoningEffort(normalizeReasoningEffort(data.reasoningEffort));
    setMessages(hydrateMessages(data.messages ?? [], data.thoughts, data.toolCalls));
    setCodeChanges(data.codeChanges ?? []);
    setFileTree(data.fileTree ?? []);
    setTerminalOutput(data.terminalOutput ?? '');
    setWebPreviewUrl(data.previewUrl ?? DEFAULT_WEB_PREVIEW_URL);
    setSelectedFilePath(data.selectedFilePath ?? '');
    setSelectedFileContent(data.selectedFileContent ?? '');
    setAvailableSkills(data.availableSkills ?? []);
    setIsLoading(Boolean(data.isGenerating));
  }, [modelOptions]);

  const fetchSessionSnapshot = useCallback(async (targetSessionId: string) => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);
    try {
      const res = await fetch(`http://localhost:8000/api/sessions/${targetSessionId}`, {
        signal: controller.signal,
      });
      if (!res.ok) {
        throw new Error(await readApiError(res, '读取会话快照失败'));
      }
      return await res.json() as SessionPayload;
    } finally {
      clearTimeout(timeoutId);
    }
  }, []);

  const refreshVisibleSessionSnapshot = useCallback(async (targetSessionId: string) => {
    const data = await fetchSessionSnapshot(targetSessionId);
    if (currentSessionIdRef.current === targetSessionId) {
      syncVisibleSessionSnapshot(data);
    }
    return data;
  }, [fetchSessionSnapshot, syncVisibleSessionSnapshot]);

  const applySessionPayload = useCallback((data: SessionPayload) => {
    setSessionId(data.sessionId);
    setSelectedWorkspace(data.workspace);
    syncVisibleSessionSnapshot(data);
    setTerminalCwd(data.workspace ?? '');
    setTerminalBackend('subprocess');
    setTerminalSupportsInterrupt(false);
    setManagedProcesses([]);
    setSessionContext(null);
    setIsContextOpen(false);
    setIsTerminalOpen(false);
    setHasTerminalBeenOpened(false);
    saveLastSession(data.workspace);
    addRecentProject(data.workspace);
    setRecentProjects(getRecentProjects());
    setShowWorkspacePicker(false);
  }, [syncVisibleSessionSnapshot]);

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
        body: JSON.stringify({
          workspace,
          model: selectedModelId,
          reasoning_effort: selectedReasoningEffort,
          agent_type: selectedAgentMode === 'auto' ? undefined : selectedAgentMode,
        }),
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
  }, [applySessionPayload, loadSessionHistory, selectedAgentMode, selectedModelId, selectedReasoningEffort]);

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
        setShouldRestoreSession(false);
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

  const handleOpenRecentProject = async (workspace: string) => {
    setSelectedWorkspace(workspace);
    setCustomWorkspace('');
    await createSessionWithWorkspace(workspace);
  };

  const handleRemoveRecentProject = (workspace: string) => {
    removeRecentProject(workspace);
    setRecentProjects(getRecentProjects());
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

  const saveFile = useCallback(
    async (path: string, content: string) => {
      if (!sessionId) return;

      const query = new URLSearchParams({ session_id: sessionId, path });
      const res = await fetch(`http://localhost:8000/api/files?${query.toString()}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(String(data.error ?? '保存失败'));
      }

      if (data.codeChange && typeof data.codeChange === 'object') {
        appendCodeChanges([data.codeChange as CodeChangeRecord]);
      }

      setSelectedFileContent(content);
      void refreshTerminalState({
        targetSessionId: sessionId,
        includeFileTree: true,
        includeProcesses: isTerminalOpen,
        silent: true,
      });
    },
    [appendCodeChanges, isTerminalOpen, refreshTerminalState, sessionId],
  );

  useEffect(() => {
    if (!sessionId) return;
    void loadSessionContext({ silent: true });
  }, [loadSessionContext, sessionId]);

  useEffect(() => {
    if (!sessionId || !isLoading) return;
    const interval = setInterval(() => {
      void loadSessionContext({ silent: true });
    }, 20_000);
    return () => clearInterval(interval);
  }, [isLoading, loadSessionContext, sessionId]);

  useEffect(() => {
    if (!sessionId || !isLoading || activeStreamSessionIdRef.current === sessionId) {
      return;
    }

    let disposed = false;

    const syncSnapshot = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}`);
        if (!res.ok) {
          throw new Error('同步会话状态失败');
        }
        const data: SessionPayload = await res.json();
        if (disposed || currentSessionIdRef.current !== sessionId) {
          return;
        }
        syncVisibleSessionSnapshot(data);
        await loadSessionContext({ silent: true, targetSessionId: sessionId });
      } catch (error) {
        if (!disposed) {
          console.error(error);
        }
      }
    };

    void syncSnapshot();
    const intervalId = setInterval(() => {
      void syncSnapshot();
    }, 1000);

    return () => {
      disposed = true;
      clearInterval(intervalId);
    };
  }, [isLoading, loadSessionContext, sessionId, syncVisibleSessionSnapshot]);

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
        const data = await fetchSessionSnapshot(targetSessionId);
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
    [applySessionPayload, fetchSessionSnapshot, sessionId]
  );

  const handleModelChange = useCallback(
    async (modelId: string) => {
      if (!sessionId) return;
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/model`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: modelId,
            reasoning_effort: selectedReasoningEffort,
          }),
        });
        if (!res.ok) {
          const errText = await res.text();
          throw new Error(errText || '切换模型失败');
        }
        const data = await res.json();
        setSelectedModelId((prev) => resolveSelectedModelId(data, modelOptions) ?? prev ?? modelId);
        setSelectedReasoningEffort(normalizeReasoningEffort(data.reasoningEffort));
        setBackendMode(data.mode ?? 'agent');
        setStartupError(null);
        setSessionError(null);
        setWebPreviewUrl(data.previewUrl ?? DEFAULT_WEB_PREVIEW_URL);
        setSessionContext((prev) =>
          prev
            ? {
                ...prev,
                model: data.model ?? prev.model,
                reasoningEffort: data.reasoningEffort ?? prev.reasoningEffort,
                mode: data.mode ?? prev.mode,
              }
            : prev
        );
      } catch (error) {
        console.error(error);
        setSessionError(error instanceof Error ? error.message : '切换模型失败');
      }
    },
    [modelOptions, selectedReasoningEffort, sessionId],
  );

  const handleReasoningEffortChange = useCallback(
    async (reasoningEffort: string) => {
      const normalized = normalizeReasoningEffort(reasoningEffort);
      const previous = selectedReasoningEffort;
      setSelectedReasoningEffort(normalized);
      if (!sessionId) {
        return;
      }
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/model`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: selectedModelId,
            reasoning_effort: normalized,
          }),
        });
        if (!res.ok) {
          const errText = await res.text();
          throw new Error(errText || '切换思考程度失败');
        }
        const data = await res.json();
        setSelectedModelId((prev) => resolveSelectedModelId(data, modelOptions) ?? prev ?? selectedModelId);
        setSelectedReasoningEffort(normalizeReasoningEffort(data.reasoningEffort));
        setBackendMode(data.mode ?? 'agent');
        setStartupError(null);
        setSessionError(null);
        setSessionContext((prev) =>
          prev
            ? {
                ...prev,
                model: data.model ?? prev.model,
                reasoningEffort: data.reasoningEffort ?? prev.reasoningEffort,
                mode: data.mode ?? prev.mode,
              }
            : prev
        );
      } catch (error) {
        console.error(error);
        setSelectedReasoningEffort(previous);
        setSessionError(error instanceof Error ? error.message : '切换思考程度失败');
      }
    },
    [modelOptions, selectedModelId, selectedReasoningEffort, sessionId],
  );

  const handleNewSession = useCallback(() => {
    void createSessionWithWorkspace(selectedWorkspace);
  }, [createSessionWithWorkspace, selectedWorkspace]);

  const saveModelProviders = useCallback(
    async (providers: UIModelProvider[]) => {
      const res = await fetch('http://localhost:8000/api/model-configs', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ providers }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(String(data.detail ?? '保存模型配置失败'));
      }
      setVisualModelProviders(data.providers ?? []);
      setEnvModelConfigs(data.envConfigs ?? []);
      setModelConfigPath(data.configPath ?? null);
      await loadModels();
    },
    [loadModels],
  );

  const discoverProviderModels = useCallback(async (provider: UIModelProvider) => {
    const res = await fetch('http://localhost:8000/api/model-configs/discover-models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(provider),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(String(data.detail ?? '拉取模型列表失败'));
    }
    return Array.isArray(data.models) ? (data.models as string[]) : [];
  }, []);

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
        setCodeChanges([]);
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

  const streamAssistantResponse = useCallback(async ({
    url,
    body,
    streamSessionId,
    initialAssistantId,
    userVisibleMessage,
    clearComposer,
  }: {
    url: string;
    body: Record<string, unknown>;
    streamSessionId: string;
    initialAssistantId?: string | null;
    userVisibleMessage?: string | null;
    clearComposer?: boolean;
  }) => {
    if (!streamSessionId || isLoading) return;

    if (clearComposer) {
      setInput('');
      setElementAttachments([]);
    }
    if (userVisibleMessage) {
      setMessages((prev) => [...prev, { id: Math.random().toString(), role: 'user', content: userVisibleMessage }]);
    }

    setIsLoading(true);
    const abortController = new AbortController();
    activeRequestRef.current = abortController;
    activeStreamSessionIdRef.current = streamSessionId;

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: abortController.signal,
      });

      if (!res.body) return;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentAssistantId = initialAssistantId ?? '';
      const toolNamesById = new Map<string, string>();
      const toolInputBuffersById = new Map<string, string>();
      const isVisibleStreamSession = () => currentSessionIdRef.current === streamSessionId;

      const updateAssistantMessage = (
        assistantId: string,
        updater: (message: ChatMessage) => ChatMessage
      ) => {
        if (!isVisibleStreamSession()) {
          return;
        }
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

          const syncGitCommitStatusPreview = async (
            assistantId: string,
            toolCallId: string,
          ) => {
            if (!isVisibleStreamSession()) {
              return;
            }
            try {
              const res = await fetch(`http://localhost:8000/api/sessions/${streamSessionId}/git/status`);
              if (!res.ok) {
                return;
              }
              const data = await res.json();
              const changedFiles = Array.isArray(data.changedFiles) ? data.changedFiles as string[] : [];
              updateToolPart(assistantId, toolCallId, (toolCall) => {
                const existingOutput = (
                  toolCall.output &&
                  typeof toolCall.output === 'object' &&
                  !Array.isArray(toolCall.output)
                ) ? toolCall.output as Record<string, unknown> : {};

                return {
                  ...toolCall,
                  output: {
                    ...existingOutput,
                    changed_files: changedFiles,
                    has_changes: changedFiles.length > 0,
                  },
                };
              });
            } catch (error) {
              console.error(error);
            }
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
            if (!isVisibleStreamSession()) {
              return;
            }
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
              refreshFileTreeAfterTerminalActivity(streamSessionId);
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
            if (toolCallRecord.name === 'save_plan') {
              showStreamingPlanDraft(normalizePlanDraft(toolCallRecord.arguments));
            }
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
            if (
              isVisibleStreamSession() &&
              toolCallRecord.name === 'read_file' &&
              typeof toolCallRecord.arguments?.filename === 'string'
            ) {
              void loadFile(toolCallRecord.arguments.filename);
            }
          } else if (data.type === 'tool-input-start') {
            const assistantId = currentAssistantId;
            const toolCallId = String(data.toolCallId ?? '');
            if (!assistantId || !toolCallId) return;
            const toolName = String(data.toolName ?? toolNamesById.get(toolCallId) ?? 'tool');
            toolNamesById.set(toolCallId, toolName);
            toolInputBuffersById.set(toolCallId, '');
            if (toolName === 'save_plan') {
              showStreamingPlanDraft(undefined);
            }
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
            const nextBufferedInput = `${toolInputBuffersById.get(toolCallId) ?? ''}${delta}`;
            toolInputBuffersById.set(toolCallId, nextBufferedInput);
            if (toolName === 'save_plan') {
              showStreamingPlanDraft(parseStreamingPlanDraft(nextBufferedInput));
            }
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
            if (
              toolName === 'save_plan' &&
              payload.output &&
              typeof payload.output === 'object' &&
              !Array.isArray(payload.output)
            ) {
              const normalizedDraft = normalizePlanDraft(
                (payload.output as Record<string, unknown>).plan,
              );
              if (normalizedDraft) {
                showStreamingPlanDraft(normalizedDraft, '计划草案');
              }
            }
            handleToolResultSideEffects(payload);
            const nextState: ToolCallRecord['state'] =
              typeof payload.state === 'string' && (payload.state === 'input-requested' || payload.state === 'approval-requested')
                ? payload.state
                : payload.success === false
                  ? 'error'
                  : 'completed';
            const inputRequest =
              payload.input_request &&
              typeof payload.input_request === 'object' &&
              !Array.isArray(payload.input_request)
                ? payload.input_request as ToolCallRecord['inputRequest']
                : undefined;
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
              inputRequest: inputRequest ?? toolCall.inputRequest,
              errorMessage: typeof payload.error_message === 'string' ? payload.error_message : toolCall.errorMessage,
              state: nextState as ToolCallRecord['state']
            }));
            if (toolName === 'git_commit' && nextState === 'approval-requested') {
              void syncGitCommitStatusPreview(assistantId, toolCallId);
            }
          } else if (data.type === 'data-plan-steps') {
            const steps = data.data?.steps;
            void steps;
          } else if (data.type === 'data-session-state') {
            const payload = (
              data.data &&
              typeof data.data === 'object' &&
              !Array.isArray(data.data)
            ) ? data.data as Partial<SessionContextPayload> : {};
            setSessionContext((prev) =>
              prev
                ? {
                    ...prev,
                    agentType: payload.agentType ?? prev.agentType,
                    phase: payload.phase ?? prev.phase,
                    deployState: payload.deployState ?? prev.deployState,
                    planState: payload.planState ?? prev.planState,
                    codeChangeCount: payload.codeChangeCount ?? prev.codeChangeCount,
                    recentCodeChanges: payload.recentCodeChanges ?? prev.recentCodeChanges,
                  }
                : prev
            );
          } else if (data.type === 'data-code-change') {
            const payload = (
              data.data &&
              typeof data.data === 'object' &&
              !Array.isArray(data.data)
            ) ? data.data as CodeChangeRecord : null;
            if (payload) {
              appendCodeChanges([payload]);
            }
          } else if (data.type === 'data-terminal-output') {
            if (typeof data.data?.output === 'string' && isVisibleStreamSession()) {
              applyTerminalSnapshot({ output: data.data.output });
            }
          } else if (data.type === 'data-preview-url') {
            if (typeof data.data?.url === 'string' && isVisibleStreamSession()) {
              setWebPreviewUrl(data.data.url);
              setIsWebPreviewOpen(true);
            }
          } else if (data.type === 'data-plan-draft') {
            showStreamingPlanDraft(normalizePlanDraft(data.data), '计划草案');
            const assistantId = currentAssistantId;
            if (!assistantId) return;
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              parts: [...(message.parts ?? []), { type: 'data' as const, dataType: data.type, data: data.data }]
            }));
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
            if (data.payload.name === 'save_plan') {
              showStreamingPlanDraft(normalizePlanDraft(data.payload.arguments));
            }
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              toolCalls: [...(message.toolCalls ?? []), toolCallRecord],
              parts: [...(message.parts ?? []), { type: 'tool_call' as const, toolCall: toolCallRecord }]
            }));
            if (
              isVisibleStreamSession() &&
              data.payload.name === 'read_file' &&
              typeof data.payload.arguments?.filename === 'string'
            ) {
              void loadFile(data.payload.arguments.filename);
            }
          } else if (data.type === 'tool_result') {
            handleToolResultSideEffects(data.payload);
            const assistantId = data.payload.assistant_id || currentAssistantId;
            if (!assistantId) return;
            currentAssistantId = assistantId;
            const payloadState = typeof data.payload.state === 'string' ? data.payload.state : undefined;
            const effectiveState: ToolCallRecord['state'] =
              payloadState === 'input-requested' ? 'input-requested' :
              payloadState === 'approval-requested' ? 'approval-requested' :
              data.payload.success ? 'completed' : 'error';
            const inputRequest =
              data.payload.input_request &&
              typeof data.payload.input_request === 'object' &&
              !Array.isArray(data.payload.input_request)
                ? data.payload.input_request as ToolCallRecord['inputRequest']
                : undefined;
            const updatedTool: Partial<ToolCallRecord> = {
              errorMessage: data.payload.error_message ?? undefined,
              state: effectiveState,
              ...(inputRequest ? { inputRequest } : {}),
            };
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              toolCalls: (message.toolCalls ?? []).map((tc) =>
                tc.id === data.payload.id
                  ? { ...tc, ...data.payload, ...updatedTool, errorMessage: data.payload.error_message ?? tc.errorMessage }
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
      if (activeStreamSessionIdRef.current === streamSessionId) {
        activeStreamSessionIdRef.current = null;
      }
      if (currentSessionIdRef.current === streamSessionId) {
        setIsLoading(false);
        void refreshTerminalState({
          includeProcesses: isTerminalOpen,
          silent: true,
        });
        void loadSessionContext({ silent: !isContextOpen });
      }
      void loadSessionHistory();
    }
  }, [appendCodeChanges, applyTerminalSnapshot, isContextOpen, isLoading, isTerminalOpen, loadFile, loadSessionContext, loadSessionHistory, refreshFileTreeAfterTerminalActivity, refreshTerminalState, showStreamingPlanDraft]);

  const sendMessage = async (msg: string, elements?: { selector: string; html: string; sourceUrl?: string }[]) => {
    if ((!msg.trim() && (!elements || elements.length === 0)) || !sessionId || isLoading) return;

    const selectedSkills = extractSelectedSkillIds(msg);
    let finalMsg = msg.trim() || '请修改这个元素';
    if (elements && elements.length > 0) {
      const elementContext = elements.map((el, i) => {
        const urlPart = el.sourceUrl ? `\n来源页面: ${el.sourceUrl}` : '';
        return `[元素${i + 1} 选择器: ${el.selector}]${urlPart}\n${el.html}`;
      }).join('\n\n');
      finalMsg = `${elementContext}\n\n${finalMsg}`;
    }

    await streamAssistantResponse({
      url: 'http://localhost:8000/api/chat/stream',
      body: {
        session_id: sessionId,
        message: finalMsg,
        agent_mode: selectedAgentMode,
        skills: selectedSkills,
      },
      streamSessionId: sessionId,
      userVisibleMessage: finalMsg,
      clearComposer: true,
    });
  };

  const continueAfterConfirmation = useCallback(async (assistantId: string) => {
    if (!sessionId || !assistantId) return;

    await streamAssistantResponse({
      url: 'http://localhost:8000/api/chat/continue',
      body: { session_id: sessionId, assistant_id: assistantId },
      streamSessionId: sessionId,
      initialAssistantId: assistantId,
      clearComposer: false,
    });
  }, [sessionId, streamAssistantResponse]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input, elementAttachments.length > 0 ? elementAttachments : undefined);
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

        if (data.codeChange && typeof data.codeChange === 'object') {
          appendCodeChanges([data.codeChange as CodeChangeRecord]);
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
        if (data.shouldContinue) {
          const assistantId = typeof data.assistantId === 'string' && data.assistantId
            ? data.assistantId
            : findAssistantIdByToolCallId(toolCallId);
          if (assistantId) {
            void continueAfterConfirmation(assistantId);
          }
        }
      } catch (error) {
        console.error(error);
      }
    },
    [appendCodeChanges, continueAfterConfirmation, findAssistantIdByToolCallId, isTerminalOpen, refreshTerminalState, sessionId]
  );

  const resolveGitConfirmation = useCallback(
    async (toolCallId: string, type: 'commit' | 'tag', approved: boolean) => {
      if (!sessionId) return;

      try {
        const endpoint = type === 'commit' ? 'confirm-commit' : 'confirm-tag';
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/tools/${toolCallId}/${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ approved }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(String(data.detail ?? data.error_message ?? '确认操作失败'));
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

        if (approved) {
          void refreshTerminalState({
            includeFileTree: true,
            includeProcesses: isTerminalOpen,
          });
        }
        if (data.shouldContinue) {
          const assistantId = typeof data.assistantId === 'string' && data.assistantId
            ? data.assistantId
            : findAssistantIdByToolCallId(toolCallId);
          if (assistantId) {
            void continueAfterConfirmation(assistantId);
          }
        }
      } catch (error) {
        console.error(error);
      }
    },
    [continueAfterConfirmation, findAssistantIdByToolCallId, isTerminalOpen, refreshTerminalState, sessionId]
  );

  const resolveConnectInput = useCallback(
    async (toolCallId: string, values: Record<string, string>) => {
      if (!sessionId) return;

      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/tools/${toolCallId}/connect`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ values }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(String(data.detail ?? '连接失败'));
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
                    state: (data.state ?? 'output-available') as ToolCallRecord['state'],
                    inputRequest: undefined,
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
                      state: (data.state ?? 'output-available') as ToolCallRecord['state'],
                      inputRequest: undefined,
                    },
                  }
                : part
            ),
          }))
        );

        if (data.shouldContinue) {
          const assistantId = typeof data.assistantId === 'string' && data.assistantId
            ? data.assistantId
            : findAssistantIdByToolCallId(toolCallId);
          if (assistantId) {
            void continueAfterConfirmation(assistantId);
          }
        }
      } catch (error) {
        console.error(error);
      }
    },
    [continueAfterConfirmation, findAssistantIdByToolCallId, sessionId]
  );

  const resolvePlanQuestionsInput = useCallback(
    async (
      toolCallId: string,
      answers: Record<string, { value: string | string[]; otherText?: string }>,
    ) => {
      if (!sessionId) return;

      const toolCall = findToolCallById(toolCallId);
      const questions = toolCall?.inputRequest?.questions;
      if (!toolCall || !Array.isArray(questions)) {
        throw new Error('未找到计划问题定义');
      }

      const payloadAnswers = questions.map((question) => {
        const rawAnswer = answers[question.id];
        if (question.type === 'short_text') {
          return {
            questionId: question.id,
            text: typeof rawAnswer?.value === 'string' ? rawAnswer.value : '',
          };
        }
        return {
          questionId: question.id,
          selectedOptionIds: Array.isArray(rawAnswer?.value)
            ? rawAnswer.value
            : typeof rawAnswer?.value === 'string' && rawAnswer.value
              ? [rawAnswer.value]
              : [],
          otherText: rawAnswer?.otherText,
        };
      });

      const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/tools/${toolCallId}/input`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers: payloadAnswers }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(String(data.detail ?? '提交失败'));
      }

      setMessages((prev) =>
        prev.map((message) => ({
          ...message,
          toolCalls: (message.toolCalls ?? []).map((currentToolCall) =>
            currentToolCall.id === toolCallId
              ? {
                  ...currentToolCall,
                  output: data.output,
                  success: data.success ?? currentToolCall.success,
                  errorMessage: data.error_message ?? currentToolCall.errorMessage,
                  state: (data.state ?? 'output-available') as ToolCallRecord['state'],
                }
              : currentToolCall
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
                    state: (data.state ?? 'output-available') as ToolCallRecord['state'],
                  },
                }
              : part
          ),
        }))
      );

      if (data.shouldContinue) {
        const assistantId = typeof data.assistantId === 'string' && data.assistantId
          ? data.assistantId
          : findAssistantIdByToolCallId(toolCallId);
        if (assistantId) {
          void continueAfterConfirmation(assistantId);
        }
      }
    },
    [continueAfterConfirmation, findAssistantIdByToolCallId, findToolCallById, sessionId]
  );

  const stopMessage = useCallback(() => {
    if (sessionId) {
      void stopManagedProcesses(sessionId);
    }
    activeRequestRef.current?.abort();
    activeRequestRef.current = null;
    setIsLoading(false);
  }, [sessionId, stopManagedProcesses]);

  const handleCopyAssistantMessage = useCallback(async (message: ChatMessage) => {
    if (message.role !== 'assistant' || !message.content.trim()) {
      return;
    }
    try {
      await copyTextToClipboard(message.content);
    } catch (error) {
      console.error(error);
    }
  }, []);

  const handleCompressConversation = useCallback(
    async (message: ChatMessage) => {
      if (!sessionId) {
        return;
      }

      setCompletionActionState({ messageId: message.id, action: 'compress' });
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/context/compress`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            mode: 'apply',
            usageThreshold: CONTEXT_COMPRESSION_USAGE_THRESHOLD,
          }),
        });
        const data = await res.json() as SessionContextCompressionPayload | { detail?: string };
        if (!res.ok) {
          throw new Error(String((data as { detail?: string }).detail ?? '压缩会话失败'));
        }
        if (!(data as SessionContextCompressionPayload).applied) {
          return;
        }

        await refreshVisibleSessionSnapshot(sessionId);
        if ((data as SessionContextCompressionPayload).updatedContext) {
          setSessionContext((data as SessionContextCompressionPayload).updatedContext ?? null);
        } else {
          await loadSessionContext({ silent: true, targetSessionId: sessionId });
        }
        await loadSessionHistory();
      } catch (error) {
        console.error(error);
      } finally {
        setCompletionActionState(null);
      }
    },
    [loadSessionContext, loadSessionHistory, refreshVisibleSessionSnapshot, sessionId]
  );

  const handleForkConversation = useCallback(
    async (message: ChatMessage) => {
      if (!sessionId) {
        return;
      }

      setCompletionActionState({ messageId: message.id, action: 'fork' });
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/fork`, {
          method: 'POST',
        });
        if (!res.ok) {
          throw new Error(await readApiError(res, '派生分支失败'));
        }
        const data = await res.json() as SessionPayload;
        applySessionPayload(data);
        await loadSessionHistory();
        await loadSessionContext({ silent: true, targetSessionId: data.sessionId });
      } catch (error) {
        console.error(error);
      } finally {
        setCompletionActionState(null);
      }
    },
    [applySessionPayload, loadSessionContext, loadSessionHistory, sessionId]
  );

  const handleRestoreConversation = useCallback(
    async (message: ChatMessage) => {
      if (!sessionId || message.role !== 'assistant' || !message.id) {
        return;
      }

      setCompletionActionState({ messageId: message.id, action: 'restore' });
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/restore`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messageId: message.id }),
        });
        if (!res.ok) {
          throw new Error(await readApiError(res, '还原对话失败'));
        }
        const data = await res.json() as SessionPayload;
        syncVisibleSessionSnapshot(data);
        await loadSessionContext({ silent: true, targetSessionId: sessionId });
        await loadSessionHistory();
      } catch (error) {
        console.error(error);
      } finally {
        setCompletionActionState(null);
      }
    },
    [loadSessionContext, loadSessionHistory, sessionId, syncVisibleSessionSnapshot]
  );

  const handleCompletionAction = useCallback(
    (action: CompletionActionKey, message: ChatMessage) => {
      switch (action) {
        case 'copy':
          void handleCopyAssistantMessage(message);
          break;
        case 'compress':
          void handleCompressConversation(message);
          break;
        case 'fork':
          void handleForkConversation(message);
          break;
        case 'restore':
          void handleRestoreConversation(message);
          break;
        default:
          break;
      }
    },
    [
      handleCompressConversation,
      handleCopyAssistantMessage,
      handleForkConversation,
      handleRestoreConversation,
    ]
  );

  const toggleSidebar = useCallback(() => {
    setIsSidebarCollapsed((prev) => !prev);
  }, []);

  const toggleRightPanel = useCallback(() => {
    setIsRightPanelCollapsed((prev) => !prev);
  }, []);

  const handleSelectOtherProject = useCallback(() => {
    clearLastSession();
    setShouldRestoreSession(false);
    setSessionId(null);
    setMessages([]);
    setCodeChanges([]);
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
        recentProjects={recentProjects}
        onDirectoryExpandedChange={handleDirectoryExpandedChange}
        onCustomWorkspaceChange={setCustomWorkspace}
        onSelectWorkspace={(path) => {
          setSelectedWorkspace(path);
          setCustomWorkspace('');
        }}
        onCreateSession={createSession}
        onOpenRecentProject={handleOpenRecentProject}
        onRemoveRecentProject={handleRemoveRecentProject}
      />
    );
  }

  return (
    <div className="flex flex-col h-screen bg-background text-foreground text-sm font-sans w-full overflow-hidden">
      <header className="flex items-center h-10 px-3 border-b bg-muted/30 flex-shrink-0 gap-2">
        <div className="flex items-center gap-2">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" className="text-primary">
            <path d="M8 4L2 12L8 20" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M16 4L22 12L16 20" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M14 3L10 21" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
          <span className="text-sm font-bold tracking-tight">Super Code</span>
        </div>
        <div className="flex-1" />
        <div className="text-[11px] text-muted-foreground truncate max-w-[300px]" title={selectedWorkspace}>{selectedWorkspace}</div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-2 rounded-full px-3 text-xs"
          onClick={() => {
            void loadModelConfigs().catch(console.error);
            setIsModelConfigOpen(true);
          }}
          title="模型与供应商设置"
        >
          <Settings2 className="w-3.5 h-3.5" />
          设置
        </Button>
        <Button variant="ghost" size="icon" onClick={toggleRightPanel} className="h-7 w-7 ml-2" title={isRightPanelCollapsed ? '展开右侧面板' : '收起右侧面板'}>
          {isRightPanelCollapsed ? <PanelRightOpen className="w-4 h-4" /> : <PanelRightClose className="w-4 h-4" />}
        </Button>
      </header>
      <div className="flex flex-1 min-h-0">
      <Sidebar
        currentSessionId={sessionId}
        historyItems={sessionHistory}
        isHistoryLoading={isHistoryLoading}
        isCollapsed={isSidebarCollapsed}
        selectedWorkspace={selectedWorkspace}
        backendMode={backendMode}
        startupError={startupError}
        width={sidebarWidth}
        isGitPanelOpen={isGitPanelOpen}
        onGitPanelToggle={() => setIsGitPanelOpen((prev) => !prev)}
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
      <div style={isRightPanelCollapsed ? undefined : { width: chatPanelWidth }} className={isRightPanelCollapsed ? 'flex-1' : 'flex-shrink-0'}>
        <ChatPanel
        sessionId={sessionId}
        contextData={sessionContext}
        codeChanges={codeChanges}
        isContextLoading={isContextLoading}
        isContextOpen={isContextOpen}
        messages={messages}
        input={input}
        isLoading={isLoading}
        model={selectedModelId}
        reasoningEffort={selectedReasoningEffort}
        modelOptions={modelOptions}
        fileTree={fileTree}
        onModelChange={handleModelChange}
        onReasoningEffortChange={handleReasoningEffortChange}
        onContextOpenChange={handleContextOpenChange}
        onInputChange={setInput}
        onKeyDown={handleKeyDown}
        onSendMessage={() => void sendMessage(input, elementAttachments.length > 0 ? elementAttachments : undefined)}
        availableSkills={availableSkills}
        onStopMessage={stopMessage}
        onResolveDeleteConfirmation={resolveDeleteConfirmation}
        onResolveGitConfirmation={resolveGitConfirmation}
        onResolveConnectInput={resolveConnectInput}
        onResolvePlanQuestionsInput={resolvePlanQuestionsInput}
        onViewPlan={openPlanDraftPanel}
        agentMode={selectedAgentMode}
        onAgentModeChange={setSelectedAgentMode}
        elementAttachments={elementAttachments}
        onRemoveElementAttachment={(id) => setElementAttachments((prev) => prev.filter((e) => e.id !== id))}
        onCompletionAction={handleCompletionAction}
        activeCompletionAction={completionActionState}
        />
      </div>
      {!isRightPanelCollapsed && (
      <ResizableHandle
        side="left"
        onResize={(delta) => setChatPanelWidth((prev) => Math.min(Math.max(prev + delta, 400), 1000))}
      />
      )}
      {!isRightPanelCollapsed && (
      <>
      <div className="flex-1 flex flex-col min-w-0">
        <EditorPanel
          fileTree={fileTree}
          selectedFilePath={selectedFilePath}
          selectedFileContent={selectedFileContent}
          onLoadFile={loadFile}
          onSaveFile={saveFile}
          sessionId={sessionId}
          isWebPreviewOpen={isWebPreviewOpen}
          onToggleWebPreview={() => setIsWebPreviewOpen((prev) => !prev)}
          webPreviewUrl={webPreviewUrl}
          onWebPreviewUrlChange={setWebPreviewUrl}
          onSelectPreviewElement={(html, selector) => {
            setElementAttachments((prev) => [
              ...prev,
              { id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, selector, html, sourceUrl: webPreviewUrl },
            ]);
          }}
          planData={planData}
          onPlanSave={async (markdown) => {
            if (!planData) return;
            const nextPlan = { ...planData, markdown };
            setPlanData(nextPlan);

            if (!sessionId) return;
            try {
              const response = await fetch(`http://localhost:8000/api/sessions/${sessionId}/plan-draft`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  title: nextPlan.title,
                  markdown: nextPlan.markdown,
                }),
              });
              const payload = await response.json();
              if (!response.ok) {
                throw new Error(String(payload.detail ?? '保存计划草案失败'));
              }
              if (payload.planState && typeof payload.planState === 'object') {
                setSessionContext((prev) =>
                  prev
                    ? {
                        ...prev,
                        planState: payload.planState,
                      }
                    : prev,
                );
              }
            } catch (error) {
              console.error('保存计划草案失败:', error);
            }
          }}
          onClosePlan={() => setPlanData(null)}
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
      </>
      )}
      </div>
      {isModelConfigOpen ? (
        <SettingsDialog
          open={isModelConfigOpen}
          onOpenChange={setIsModelConfigOpen}
          providers={visualModelProviders}
          envConfigs={envModelConfigs}
          configPath={modelConfigPath}
          settings={appSettings}
          onSaveProviders={saveModelProviders}
          onDiscoverModels={discoverProviderModels}
          onSaveSettings={saveAppSettings}
        />
      ) : null}
    </div>
  );
}
