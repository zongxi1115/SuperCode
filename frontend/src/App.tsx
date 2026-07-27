import { useCallback, useEffect, useRef, useState, type MouseEvent } from 'react';
import { ChatPanel } from '@/components/app/chat-panel';
import { EditorPanel, type CodeSelectionContext, type PlanData } from '@/components/app/editor-panel';
import type { Annotation } from '@/components/app/plan-rich-text-editor';
import { ResizableHandle } from '@/components/app/resizable-handle';
import { Sidebar } from '@/components/app/sidebar';
import { TerminalPanel } from '@/components/app/terminal-panel';
import { SettingsDialog } from '@/components/app/settings-dialog';
import { WorkspacePicker } from '@/components/app/workspace-picker';
import { KanbanBoard } from '@/components/kanban/kanban-board';
import { ProjectDocsPage } from '@/components/project-docs/project-docs-page';
import type { KanbanAiState, KanbanCard } from '@/lib/kanban-types';
import type {
  AgentMode,
  AppSettings,
  ChatAttachment,
  ChatMessage,
  CodeChangeRecord,
  CompletionActionKey,
  ContentBlock,
  DirectoryNode,
  FileTreeNode,
  ManagedProcessPayload,
  MCPServerConfig,
  MCPServersPayload,
  MCPServerTestResult,
  ModelConnectionTestResult,
  ModelConfigPayload,
  ModelOption,
  PlanStep,
  PluginSummary,
  RecentProject,
  SessionContextPayload,
  SessionContextCompressionPayload,
  SessionTokenUsage,
  SessionHistoryItem,
  SessionHistoryResponse,
  SessionExecutionMode,
  SessionPayload,
  SkillSummary,
  SubagentSnapshot,
  TerminalInfo,
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
import { apiFetch, apiUrl, openExternalUrl } from '@/lib/api-client';

import { ChevronDown, FolderOpen, Info, Minus, Moon, PanelRightOpen, PanelRightClose, Settings2, Square, Sun, X } from 'lucide-react';
import { SiCursor, SiVscodium, SiZedindustries } from '@icons-pack/react-simple-icons';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { message as appMessage } from '@/components/ui/message';
import { AnimatePresence, motion } from 'motion/react';
import { SplashScreen } from '@/components/app/splash-screen';

const DEFAULT_WEB_PREVIEW_URL = 'http://localhost:8888';
const DEFAULT_MODEL_STORAGE_KEY = 'supercode.defaultModelId';
const CONTEXT_COMPRESSION_USAGE_THRESHOLD = 0.8;
const STREAM_RETRY_LIMIT = 10;
const SESSION_HISTORY_PAGE_SIZE = 30;
const RETRYABLE_STREAM_STATUS = new Set([408, 425, 429, 500, 502, 503, 504]);
const STREAMING_TOOL_ID_PREFIX = 'streaming-';
const STREAMABLE_TOOL_NAMES = [
  'write_file',
  'replace_file',
  'apply_patch',
  'save_plan',
  'ask_plan_questions',
  'ask_user',
];

const PROJECT_OPEN_TARGETS = [
  { name: 'VS Code', command: 'code', icon: <SiVscodium size={14} color="#007ACC" /> },
  { name: 'Cursor', command: 'cursor', icon: <SiCursor size={14} color="#111827" /> },
  { name: 'Zed', command: 'zed', icon: <SiZedindustries size={14} color="#084CCF" /> },
];

type ViewTransitionDocument = Document & {
  startViewTransition?: (callback: () => void) => {
    ready: Promise<void>;
  };
};

type UrlAppState = {
  sessionId: string | null;
  activePlugin: string | null;
  filePath: string | null;
  isEditorOpen: boolean;
  isTerminalOpen: boolean;
  isWebPreviewOpen: boolean;
  isGitPanelOpen: boolean;
  isContextOpen: boolean;
};

const DEFAULT_URL_APP_STATE: UrlAppState = {
  sessionId: null,
  activePlugin: null,
  filePath: null,
  isEditorOpen: false,
  isTerminalOpen: false,
  isWebPreviewOpen: false,
  isGitPanelOpen: false,
  isContextOpen: false,
};

function readBooleanParam(searchParams: URLSearchParams, key: string) {
  const value = searchParams.get(key);
  return value === '1' || value === 'true';
}

function inferToolNameFromStreamingId(toolCallId: string) {
  if (!toolCallId.startsWith(STREAMING_TOOL_ID_PREFIX)) {
    return '';
  }
  const suffix = toolCallId.slice(STREAMING_TOOL_ID_PREFIX.length).trim();
  if (!suffix) {
    return '';
  }
  return STREAMABLE_TOOL_NAMES.find((name) => suffix === name || suffix.startsWith(`${name}-`)) ?? suffix;
}

function resolveStreamToolName(
  toolCallId: string,
  eventToolName: unknown,
  storedToolName?: string,
) {
  const directToolName = typeof eventToolName === 'string' ? eventToolName.trim() : '';
  if (directToolName && directToolName !== 'tool') {
    return directToolName;
  }
  if (storedToolName && storedToolName !== 'tool') {
    return storedToolName;
  }
  return inferToolNameFromStreamingId(toolCallId) || directToolName || storedToolName || 'tool';
}

function getUrlAppState(): UrlAppState {
  if (typeof window === 'undefined') {
    return DEFAULT_URL_APP_STATE;
  }

  const pathname = window.location.pathname.replace(/\/+$/, '') || '/';
  const searchParams = new URLSearchParams(window.location.search);
  const legacyHash = window.location.hash.slice(1);
  const sessionMatch = pathname.match(/^\/sessions\/([^/]+)(?:\/([^/]+))?$/);
  const pluginPath = sessionMatch?.[2] ?? pathname.slice(1);
  const pluginFromPath =
    pluginPath === 'kanban'
      ? 'kanban'
      : pluginPath === 'docs' || pluginPath === 'project-docs'
        ? 'project-docs'
        : null;
  const pluginFromHash = legacyHash.startsWith('/plugin/')
    ? legacyHash.replace('/plugin/', '')
    : null;
  const filePath = searchParams.get('file');

  return {
    sessionId: sessionMatch?.[1] ? decodeURIComponent(sessionMatch[1]) : null,
    activePlugin: pluginFromPath ?? pluginFromHash,
    filePath: filePath && filePath.trim() ? filePath : null,
    isEditorOpen: searchParams.get('panel') === 'editor' || Boolean(filePath),
    isTerminalOpen: readBooleanParam(searchParams, 'terminal'),
    isWebPreviewOpen: readBooleanParam(searchParams, 'preview'),
    isGitPanelOpen: readBooleanParam(searchParams, 'git'),
    isContextOpen: readBooleanParam(searchParams, 'context'),
  };
}

function buildUrlForAppState(state: UrlAppState) {
  const searchParams = new URLSearchParams();
  const pathBase = state.sessionId
    ? `/sessions/${encodeURIComponent(state.sessionId)}`
    : '/app';
  const pluginPath = state.activePlugin === 'kanban'
    ? 'kanban'
    : state.activePlugin === 'project-docs'
      ? 'docs'
      : null;
  const pathname = pluginPath
    ? state.sessionId ? `${pathBase}/${pluginPath}` : `/${pluginPath}`
    : pathBase;

  if (state.isEditorOpen) {
    searchParams.set('panel', 'editor');
  }
  if (state.filePath) {
    searchParams.set('file', state.filePath);
  }
  if (state.isTerminalOpen) {
    searchParams.set('terminal', '1');
  }
  if (state.isWebPreviewOpen) {
    searchParams.set('preview', '1');
  }
  if (state.isGitPanelOpen) {
    searchParams.set('git', '1');
  }
  if (state.isContextOpen) {
    searchParams.set('context', '1');
  }

  const query = searchParams.toString();
  return `${pathname}${query ? `?${query}` : ''}`;
}

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

function normalizeExecutionMode(value?: string | null): SessionExecutionMode {
  return value === 'worktree' ? 'worktree' : 'local';
}

function getPathLeaf(path?: string | null): string {
  const normalized = (path ?? '').replace(/\\/g, '/');
  const segments = normalized.split('/').filter(Boolean);
  return segments[segments.length - 1] || path || '';
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

function formatPlanAnnotations(annotations: Annotation[], title?: string) {
  const items = annotations
    .filter((annotation) => annotation.selectedText.trim() || annotation.text.trim())
    .map((annotation, index) => {
      const selectedText = annotation.selectedText.trim();
      const note = annotation.text.trim();
      return `${index + 1}. "${selectedText}"${note ? ` — ${note}` : ''}`;
    });

  if (items.length === 0) {
    return '';
  }

  const titleSuffix = title?.trim() ? ` (${title.trim()})` : '';
  return `\n\n---\n**批注${titleSuffix}:**\n${items.join('\n')}`;
}

function formatCodeSelectionContext(context: CodeSelectionContext) {
  const lineLabel =
    context.startLineNumber === context.endLineNumber
      ? `L${context.startLineNumber}`
      : `L${context.startLineNumber}-L${context.endLineNumber}`;
  const fenceLanguage = context.language && context.language !== 'plaintext' ? context.language : '';
  const selectedText = context.selectedText.replace(/\s+$/g, '');
  const longestFence = Math.max(
    2,
    ...Array.from(selectedText.matchAll(/`+/g), (match) => match[0].length),
  );
  const fence = '`'.repeat(Math.max(3, longestFence + 1));

  return [
    `引用代码：${context.filePath}:${lineLabel}`,
    `${fence}${fenceLanguage}`,
    selectedText,
    fence,
    '',
  ].join('\n');
}

function formatKanbanCardTaskPrompt(card: KanbanCard) {
  const lines = [
    `请根据这张看板卡片创建执行方案并开始完成它。`,
    '',
    `# ${card.title || '未命名卡片'}`,
    '',
    `- 状态：${card.status}`,
    `- 优先级：${card.priority}`,
  ];

  if (card.assignee?.trim()) {
    lines.push(`- 负责人：${card.assignee.trim()}`);
  }

  if (card.labels.length > 0) {
    lines.push(`- 标签：${card.labels.join(', ')}`);
  }

  const description = card.description.trim();
  if (description) {
    lines.push('', '## 描述', description);
  }

  lines.push(
    '',
    '请先确认你理解的目标和约束，然后直接推进实现；如果信息不足，请提出最少量的关键问题。',
  );

  return lines.join('\n');
}

function formatKanbanAiPhaseLabel(phase?: string) {
  switch (phase) {
    case 'planning':
      return 'AI 正在规划任务';
    case 'researching':
      return 'AI 正在阅读代码和上下文';
    case 'clarifying':
      return 'AI 正在梳理实现方向';
    case 'awaiting_user_input':
      return 'AI 等待补充信息';
    case 'executing':
      return 'AI 正在执行任务';
    case 'verifying':
      return 'AI 正在验证结果';
    case 'completed':
      return 'AI 任务已完成';
    case 'failed':
      return 'AI 任务执行失败';
    default:
      return 'AI 正在处理中';
  }
}

function buildKanbanAiState(options: {
  sessionId: string;
  startedAt: string;
  phase?: string;
  planSteps?: PlanStep[];
  status?: KanbanAiState['status'];
  result?: string | null;
  error?: string | null;
  finishedAt?: string | null;
}) {
  const planSteps = options.planSteps ?? [];
  const activeStep = planSteps.find((step) => step.status === 'running')
    ?? planSteps.find((step) => step.status === 'blocked')
    ?? null;
  const completed = planSteps.filter((step) => step.status === 'completed').length;
  const total = planSteps.length;
  const status = options.status
    ?? (options.error ? 'error' : options.finishedAt ? 'completed' : 'running');

  return {
    status,
    sessionId: options.sessionId,
    startedAt: options.startedAt,
    finishedAt: options.finishedAt ?? null,
    lastMessage: options.error || options.result || formatKanbanAiPhaseLabel(options.phase),
    activeStepTitle: activeStep?.title ?? null,
    result: options.result ?? null,
    error: options.error ?? null,
    planSteps,
    progress: total > 0 ? { completed, total } : null,
  } satisfies KanbanAiState;
}

function buildDefaultKanbanPlanSteps(): PlanStep[] {
  return [
    { id: 'card-step-1', title: '理解需求', description: 'AI 已接收卡片描述，正在梳理目标和约束。', status: 'running' },
    { id: 'card-step-2', title: '分析代码', description: '准备查看相关文件、上下文与现有实现。', status: 'pending' },
    { id: 'card-step-3', title: '实施修改', description: '准备落地代码、配置或文档改动。', status: 'pending' },
    { id: 'card-step-4', title: '整理结果', description: '准备汇总结果、验证情况与后续说明。', status: 'pending' },
  ];
}

function advanceKanbanPlanSteps(currentSteps: PlanStep[], toolName: string): PlanStep[] {
  const steps = (currentSteps.length > 0 ? currentSteps : buildDefaultKanbanPlanSteps()).map((step) => ({ ...step }));
  const normalizedToolName = toolName.trim().toLowerCase();
  const targetStepIndex =
    ['read_file', 'list_file', 'grep_file'].includes(normalizedToolName)
      ? 1
      : ['write_file', 'replace_file', 'apply_patch', 'delete_file'].includes(normalizedToolName)
        ? 2
        : ['execute', 'excecute', 'terminal_input', 'terminal_wait'].includes(normalizedToolName)
          ? 3
          : 0;

  steps.forEach((step, index) => {
    if (index < targetStepIndex) {
      step.status = 'completed';
    } else if (index === targetStepIndex) {
      step.status = 'running';
    } else if (step.status !== 'completed') {
      step.status = 'pending';
    }
  });

  if (targetStepIndex === 1) {
    steps[1].description = 'AI 正在读取项目结构、文件内容和引用关系。';
  } else if (targetStepIndex === 2) {
    steps[2].description = 'AI 正在把修改写回工作区。';
  } else if (targetStepIndex === 3) {
    steps[3].description = 'AI 正在执行命令、检查结果并整理输出。';
  }

  return steps;
}

function isAgentMode(value: unknown): value is AgentMode {
  return value === 'chat' || value === 'plan' || value === 'coding' || value === 'deploy' || value === 'super' || value === 'conflux';
}

function resolveAgentModeForRequest(value: unknown) {
  return isAgentMode(value) ? value : undefined;
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

class StreamHttpError extends Error {
  status: number;
  retryable: boolean;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'StreamHttpError';
    this.status = status;
    this.retryable = RETRYABLE_STREAM_STATUS.has(status);
  }
}

type SubagentStreamEvent = {
  event?: string;
  messageId?: string;
  subagentId?: string;
  title?: string;
  agentType?: string;
  task?: string;
  parentToolCallId?: string | null;
  parentAssistantId?: string | null;
  stepIndex?: number | null;
  message?: string;
  delta?: string;
  thought?: string;
  finalAnswer?: string;
  finalOutput?: string;
  usage?: unknown;
  toolCall?: Partial<ToolCallRecord> | null;
  toolResult?: {
    name?: string;
    tool_call_id?: string | null;
    toolCallId?: string | null;
    output?: unknown;
    success?: boolean | null;
    error_message?: string | null;
    errorMessage?: string | null;
  } | null;
  status?: string;
  error?: string | null;
};

type LoadSessionHistoryOptions = {
  offset?: number;
  append?: boolean;
};

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError';
}

function isCanceledError(error: unknown) {
  if (error instanceof DOMException) {
    return error.name === 'AbortError' || error.name === 'Canceled';
  }
  if (error instanceof Error) {
    return error.name === 'AbortError' || error.name === 'Canceled' || error.message === 'Canceled';
  }
  return false;
}

function getRetryDelayMs(retryIndex: number) {
  return 1000 * 2 ** retryIndex;
}

function formatRetryDelay(ms: number) {
  const seconds = ms / 1000;
  return Number.isInteger(seconds) ? `${seconds} 秒` : `${seconds.toFixed(1)} 秒`;
}

function mergeDirectoryNode(current: FileTreeNode, replacement: FileTreeNode): FileTreeNode {
  const currentChildren = current.children ?? [];
  const replacementChildren = replacement.children ?? [];
  const mergedChildren = replacementChildren.map((child) => {
    const existing = currentChildren.find((candidate) => candidate.path === child.path);
    if (
      existing?.type === 'folder' &&
      child.type === 'folder' &&
      existing.loaded &&
      !child.loaded
    ) {
      return {
        ...child,
        loaded: true,
        children: existing.children,
      };
    }
    return child;
  });

  return {
    ...replacement,
    loaded: replacement.loaded ?? true,
    children: mergedChildren,
  };
}

function applyDirectoryPatch(nodes: FileTreeNode[], directories: FileTreeNode[]) {
  let changed = false;

  const replaceInNodes = (currentNodes: FileTreeNode[]): FileTreeNode[] =>
    currentNodes.map((node) => {
      const replacement = directories.find((directory) => directory.path === node.path);
      if (replacement) {
        changed = true;
        return mergeDirectoryNode(node, replacement);
      }
      if (node.children?.length) {
        const nextChildren = replaceInNodes(node.children);
        if (nextChildren !== node.children) {
          return { ...node, children: nextChildren };
        }
      }
      return node;
    });

  const nextNodes = replaceInNodes(nodes);
  return changed ? nextNodes : null;
}

function findFileTreeNode(nodes: FileTreeNode[], path: string): FileTreeNode | null {
  for (const node of nodes) {
    if (node.path === path) {
      return node;
    }
    if (node.children?.length) {
      const child = findFileTreeNode(node.children, path);
      if (child) {
        return child;
      }
    }
  }
  return null;
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function normalizeAppSettings(settings: AppSettings): AppSettings {
  return {
    ...settings,
    finalAnswerRendering:
      settings.finalAnswerRendering === 'html' ? 'html' : 'markdown',
    embedding: {
      enabled: settings.embedding?.enabled ?? false,
      baseUrl: settings.embedding?.baseUrl ?? '',
      apiKey: settings.embedding?.apiKey ?? '',
      model: settings.embedding?.model ?? '',
    },
    imageGeneration: {
      enabled: settings.imageGeneration?.enabled ?? false,
      baseUrl: settings.imageGeneration?.baseUrl ?? '',
      apiKey: settings.imageGeneration?.apiKey ?? '',
      model: settings.imageGeneration?.model ?? '',
      size: settings.imageGeneration?.size ?? '1024x1024',
      quality: settings.imageGeneration?.quality ?? 'auto',
    },
    tinyfish: {
      enabled: settings.tinyfish?.enabled ?? false,
      apiKey: settings.tinyfish?.apiKey ?? '',
      searchUrl: settings.tinyfish?.searchUrl ?? 'https://api.search.tinyfish.ai',
      fetchUrl: settings.tinyfish?.fetchUrl ?? 'https://api.fetch.tinyfish.ai',
      timeout: settings.tinyfish?.timeout ?? 30,
    },
    memory: {
      enabled: settings.memory?.enabled ?? true,
      autoLearn: settings.memory?.autoLearn ?? true,
      global: settings.memory?.global ?? [],
      workspaces: settings.memory?.workspaces ?? {},
    },
  };
}

function waitForRetryDelay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }

    let timer: number;
    function cleanup() {
      signal.removeEventListener('abort', abort);
    }
    function abort() {
      window.clearTimeout(timer);
      cleanup();
      reject(new DOMException('Aborted', 'AbortError'));
    }
    timer = window.setTimeout(() => {
      cleanup();
      resolve();
    }, ms);
    signal.addEventListener('abort', abort, { once: true });
  });
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
  const [initialUrlState] = useState(getUrlAppState);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [codeChanges, setCodeChanges] = useState<CodeChangeRecord[]>([]);
  const [input, setInput] = useState('');
  const [composerFocusRevision, setComposerFocusRevision] = useState(0);
  const [fileTree, setFileTree] = useState<FileTreeNode[]>([]);
  const fileTreeRef = useRef<FileTreeNode[]>([]);
  const fileTreeRevisionRef = useRef(0);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [activePlugin, setActivePlugin] = useState<string | null>(initialUrlState.activePlugin);
  const [terminalCwd, setTerminalCwd] = useState('');
  const [terminalBackend, setTerminalBackend] = useState('subprocess');
  const [managedProcesses, setManagedProcesses] = useState<ManagedProcessPayload[]>([]);
  const [isStoppingProcesses, setIsStoppingProcesses] = useState(false);
  const [terminalInfos, setTerminalInfos] = useState<TerminalInfo[]>([]);
  const [activeTerminalId, setActiveTerminalId] = useState<string | null>(null);
  const [selectedFileContent, setSelectedFileContent] = useState('');
  const [selectedFilePath, setSelectedFilePath] = useState('');
  const [planData, setPlanData] = useState<PlanData | null>(null);
  const [planAnnotations, setPlanAnnotations] = useState<Annotation[]>([]);
  const [backendMode, setBackendMode] = useState<'agent' | 'demo'>('demo');
  const [startupError, setStartupError] = useState<string | null>(null);
  const [directoryTree, setDirectoryTree] = useState<DirectoryNode[]>([]);
  const [directoryExpanded, setDirectoryExpanded] = useState<Set<string>>(new Set());
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [isSessionBooting, setIsSessionBooting] = useState(false);
  const [initializeGitRepository, setInitializeGitRepository] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isRightPanelCollapsed, setIsRightPanelCollapsed] = useState(!initialUrlState.isEditorOpen);
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [isSidebarResizing, setIsSidebarResizing] = useState(false);
  const [isGitPanelOpen, setIsGitPanelOpen] = useState(initialUrlState.isGitPanelOpen);
  const [isContextOpen, setIsContextOpen] = useState(initialUrlState.isContextOpen);
  const [isContextLoading, setIsContextLoading] = useState(false);
  const [sessionContext, setSessionContext] = useState<SessionContextPayload | null>(null);
  const [isTerminalOpen, setIsTerminalOpen] = useState(initialUrlState.isTerminalOpen);
  const [hasTerminalBeenOpened, setHasTerminalBeenOpened] = useState(initialUrlState.isTerminalOpen);
  const [isWebPreviewOpen, setIsWebPreviewOpen] = useState(initialUrlState.isWebPreviewOpen);
  const [webPreviewUrl, setWebPreviewUrl] = useState(DEFAULT_WEB_PREVIEW_URL);
  const [elementAttachments, setElementAttachments] = useState<{ id: string; selector: string; html: string; sourceUrl?: string }[]>([]);
  const [chatPanelWidth, setChatPanelWidth] = useState(920);
  const [sessionHistory, setSessionHistory] = useState<SessionHistoryItem[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [sessionHistoryHasMore, setSessionHistoryHasMore] = useState(false);
  const [sessionHistoryNextOffset, setSessionHistoryNextOffset] = useState(0);
  const [recentProjects, setRecentProjects] = useState<RecentProject[]>(() => getRecentProjects());
  const [newSessionExecutionMode, setNewSessionExecutionMode] = useState<SessionExecutionMode>('local');
  const [currentSessionExecutionMode, setCurrentSessionExecutionMode] = useState<SessionExecutionMode>('local');
  const [currentBaseWorkspace, setCurrentBaseWorkspace] = useState('');
  const [currentWorktreeBranch, setCurrentWorktreeBranch] = useState<string | null>(null);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [defaultModelId, setDefaultModelId] = useState<string | null>(() => (
    localStorage.getItem(DEFAULT_MODEL_STORAGE_KEY) || null
  ));
  const [selectedReasoningEffort, setSelectedReasoningEffort] = useState<string | null>(null);
  const [selectedAgentMode, setSelectedAgentMode] = useState<AgentMode>('auto');
  const [isSuperAutopilotEnabled, setIsSuperAutopilotEnabled] = useState(false);
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [availablePlugins, setAvailablePlugins] = useState<PluginSummary[]>([]);
  const [availableSkills, setAvailableSkills] = useState<SkillSummary[]>([]);
  const [isModelConfigOpen, setIsModelConfigOpen] = useState(false);
  const [isAboutOpen, setIsAboutOpen] = useState(false);
  const [appSettings, setAppSettings] = useState<AppSettings>({
    autoApprove: false,
    thinkingRendering: 'text',
    finalAnswerRendering: 'markdown',
    bodyFontFamily:
      'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    bodyFontSize: 14,
    bodyLineHeight: 22,
    embedding: {
      enabled: false,
      baseUrl: '',
      apiKey: '',
      model: '',
    },
    imageGeneration: {
      enabled: false,
      baseUrl: '',
      apiKey: '',
      model: '',
      size: '1024x1024',
      quality: 'auto',
    },
    memory: {
      enabled: true,
      autoLearn: true,
      global: [],
      workspaces: {},
    },
  });
  const [visualModelProviders, setVisualModelProviders] = useState<UIModelProvider[]>([]);
  const [modelConfigPath, setModelConfigPath] = useState<string | null>(null);
  const [mcpServers, setMcpServers] = useState<MCPServerConfig[]>([]);
  const [mcpConfigPath, setMcpConfigPath] = useState<string | null>(null);
  const [completionActionState, setCompletionActionState] = useState<{
    messageId: string;
    action: CompletionActionKey;
  } | null>(null);
  const [isDarkMode, setIsDarkMode] = useState(() => {
    const stored = localStorage.getItem('theme');
    if (stored) return stored === 'dark';
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  });
  const activeRequestRef = useRef<AbortController | null>(null);
  const activeStreamSessionIdRef = useRef<string | null>(null);
  const currentSessionIdRef = useRef<string | null>(null);
  const fileTreeLoadingPathsRef = useRef<Set<string>>(new Set());
  const isApplyingUrlStateRef = useRef(false);
  const shouldDeferInitialUrlSyncRef = useRef(
    Boolean(initialUrlState.sessionId || initialUrlState.filePath || initialUrlState.isContextOpen),
  );

  useEffect(() => {
    currentSessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    if (selectedAgentMode !== 'super') {
      setIsSuperAutopilotEnabled(false);
    }
  }, [selectedAgentMode]);

  const applyTheme = useCallback((darkMode: boolean) => {
    document.documentElement.classList.toggle('dark', darkMode);
    localStorage.setItem('theme', darkMode ? 'dark' : 'light');
  }, []);

  useEffect(() => {
    applyTheme(isDarkMode);
  }, [applyTheme, isDarkMode]);

  const handleThemeToggle = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    const nextIsDarkMode = !isDarkMode;
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const viewTransitionDocument = document as ViewTransitionDocument;

    if (!viewTransitionDocument.startViewTransition || prefersReducedMotion) {
      setIsDarkMode(nextIsDarkMode);
      return;
    }

    const { clientX, clientY } = event;
    const endRadius = Math.hypot(
      Math.max(clientX, window.innerWidth - clientX),
      Math.max(clientY, window.innerHeight - clientY),
    );

    const transition = viewTransitionDocument.startViewTransition(() => {
      setIsDarkMode(nextIsDarkMode);
      applyTheme(nextIsDarkMode);
    });

    transition.ready
      .then(() => {
        document.documentElement.animate(
          {
            clipPath: [
              `circle(0px at ${clientX}px ${clientY}px)`,
              `circle(${endRadius}px at ${clientX}px ${clientY}px)`,
            ],
          },
          {
            duration: 520,
            easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
            pseudoElement: '::view-transition-new(root)',
          },
        );
      })
      .catch((error) => {
        if (!isCanceledError(error)) {
          console.error(error);
        }
      });
  }, [applyTheme, isDarkMode]);

  useEffect(() => {
    document.documentElement.style.setProperty('--font-sans', appSettings.bodyFontFamily);
    document.documentElement.style.setProperty('--app-body-font-size', `${appSettings.bodyFontSize}px`);
    document.documentElement.style.setProperty('--app-body-line-height', `${appSettings.bodyLineHeight}px`);
  }, [appSettings.bodyFontFamily, appSettings.bodyFontSize, appSettings.bodyLineHeight]);

  useEffect(() => {
    if (shouldDeferInitialUrlSyncRef.current) {
      return;
    }
    if (isApplyingUrlStateRef.current) {
      return;
    }

    const nextUrl = buildUrlForAppState({
      sessionId,
      activePlugin,
      filePath: !isRightPanelCollapsed && selectedFilePath ? selectedFilePath : null,
      isEditorOpen: !isRightPanelCollapsed,
      isTerminalOpen,
      isWebPreviewOpen,
      isGitPanelOpen,
      isContextOpen,
    });
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (currentUrl !== nextUrl || window.location.hash) {
      window.history.replaceState(null, '', nextUrl);
    }
  }, [
    activePlugin,
    isContextOpen,
    isGitPanelOpen,
    isRightPanelCollapsed,
    isTerminalOpen,
    isWebPreviewOpen,
    selectedFilePath,
    sessionId,
  ]);

  const openPlanDraftPanel = useCallback((title: string, markdown: string) => {
    setPlanData({ title, markdown });
    setPlanAnnotations([]);
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
    setTerminalCwd((prev) => data.cwd ?? prev);
    setTerminalBackend((prev) => data.backend ?? prev);
  }, []);

  const applyFileTreeSnapshot = useCallback((tree: FileTreeNode[], revision?: number | null) => {
    fileTreeRef.current = tree;
    setFileTree(tree);
    if (typeof revision === 'number' && Number.isFinite(revision)) {
      fileTreeRevisionRef.current = Math.max(fileTreeRevisionRef.current, revision);
    }
  }, []);

  const refreshFileTreeSnapshot = useCallback(async (targetSessionId?: string | null, force = false) => {
    const currentSessionId = targetSessionId ?? sessionId;
    if (!currentSessionId) return;

    const query = force ? '?force=true' : '';
    const res = await apiFetch(`/api/sessions/${currentSessionId}/file-tree${query}`);
    if (!res.ok) {
      throw new Error('刷新项目结构失败');
    }
    const data = await res.json();
    applyFileTreeSnapshot(Array.isArray(data.fileTree) ? data.fileTree : [], data.revision);
  }, [applyFileTreeSnapshot, sessionId]);

  const applyLoadedFileTreeDirectory = useCallback((directory: FileTreeNode, revision?: number | null) => {
    const currentTree = fileTreeRef.current;
    const nextTree = applyDirectoryPatch(currentTree, [directory]) ?? [directory];
    fileTreeRef.current = nextTree;
    setFileTree(nextTree);
    if (typeof revision === 'number' && Number.isFinite(revision)) {
      fileTreeRevisionRef.current = Math.max(fileTreeRevisionRef.current, revision);
    }
  }, []);

  const loadFileTreeDirectory = useCallback(async (path: string, force = false) => {
    const currentSessionId = currentSessionIdRef.current;
    if (!currentSessionId || !path) return;
    const existing = findFileTreeNode(fileTreeRef.current, path);
    if (existing?.type === 'folder' && existing.loaded && !force) {
      return;
    }
    const loadingPaths = fileTreeLoadingPathsRef.current;
    if (loadingPaths.has(path)) {
      return;
    }

    loadingPaths.add(path);
    try {
      const query = new URLSearchParams({ path });
      if (force) {
        query.set('force', 'true');
      }
      const res = await apiFetch(`/api/sessions/${currentSessionId}/file-tree?${query.toString()}`);
      if (!res.ok) {
        throw new Error('加载目录失败');
      }
      const data = await res.json();
      if (data.directory && typeof data.directory === 'object') {
        applyLoadedFileTreeDirectory(data.directory as FileTreeNode, data.revision);
      }
    } catch (error) {
      console.error(error);
    } finally {
      loadingPaths.delete(path);
    }
  }, [applyLoadedFileTreeDirectory]);

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
      includeOutput?: boolean;
      includeFileTree?: boolean;
      includeProcesses?: boolean;
      includeTerminals?: boolean;
      silent?: boolean;
    }) => {
      const currentSessionId = options?.targetSessionId ?? sessionId;
      if (!currentSessionId) {
        if (options?.includeProcesses) {
          setManagedProcesses([]);
        }
        if (options?.includeTerminals) {
          setTerminalInfos([]);
        }
        return;
      }

      try {
        if (options?.includeTerminals) {
          const terminalsRes = await apiFetch(
            `/api/sessions/${currentSessionId}/terminals`
          );
          if (terminalsRes.ok) {
            const terminalsData = await terminalsRes.json();
            const infos: TerminalInfo[] = Array.isArray(terminalsData.terminals)
              ? terminalsData.terminals
              : [];
            setTerminalInfos(infos);
            const defaultTerminal = infos.find((t) => t.isDefault);
            if (defaultTerminal) {
              setTerminalCwd(defaultTerminal.cwd ?? '');
              setTerminalBackend(defaultTerminal.backend);
            }
            const mp: ManagedProcessPayload[] = infos
              .filter((t) => t.kind === 'managed-process')
              .map((t) => ({
                terminalId: t.terminalId,
                command: t.command ?? '',
                rootPid: t.rootPid ?? 0,
                status: t.status ?? 'unknown',
                startedAt: t.startedAt ?? 0,
                returnCode: t.returnCode ?? null,
                terminatedAt: t.terminatedAt ?? null,
                processCount: t.processCount ?? 0,
                processes: [],
              }));
            setManagedProcesses(mp);
          }
        }

        const query = new URLSearchParams();
        query.set('include_output', options?.includeOutput ? 'true' : 'false');
        if (options?.includeFileTree) {
          query.set('include_file_tree', 'true');
        }
        if (options?.includeProcesses) {
          query.set('include_processes', 'true');
        }
        const res = await apiFetch(
          `/api/sessions/${currentSessionId}/terminal${query.size ? `?${query.toString()}` : ''}`
        );
        if (!res.ok) {
          throw new Error('读取终端状态失败');
        }
        const data: TerminalSnapshotPayload = await res.json();
        applyTerminalSnapshot(data);
        if (Array.isArray(data.fileTree)) {
          applyFileTreeSnapshot(data.fileTree, null);
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
    [applyFileTreeSnapshot, applyTerminalSnapshot, sessionId]
  );

  const refreshFileTreeAfterTerminalActivity = useCallback(
    (targetSessionId?: string) => {
      void refreshTerminalState({
        targetSessionId,
        includeFileTree: true,
        includeTerminals: isTerminalOpen,
        silent: true,
      });
    },
    [isTerminalOpen, refreshTerminalState]
  );

  useEffect(() => {
    if (!sessionId) return;

    const controller = new AbortController();
    let buffer = '';

    const parseSsePayload = (eventStr: string) => {
      const dataLines = eventStr
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart());
      if (dataLines.length === 0) return null;
      const rawData = dataLines.join('\n').trim();
      if (!rawData || rawData === '[DONE]') return null;
      return JSON.parse(rawData) as {
        type?: string;
        revision?: number;
        tree?: unknown;
        directories?: unknown;
      };
    };

    const handleFileTreeEvent = async (eventStr: string) => {
      const parsed = parseSsePayload(eventStr);
      if (!parsed) return;

      const revision = typeof parsed.revision === 'number' ? parsed.revision : 0;
      if (parsed.type === 'tree.snapshot' && Array.isArray(parsed.tree)) {
        const currentRevision = fileTreeRevisionRef.current;
        if (revision > 0 && revision < currentRevision) {
          return;
        }
        const nextTree = parsed.tree as FileTreeNode[];
        fileTreeRef.current = nextTree;
        setFileTree(nextTree);
        fileTreeRevisionRef.current = Math.max(currentRevision, revision);
        return;
      }

      if (parsed.type === 'tree.patch') {
        const currentRevision = fileTreeRevisionRef.current;
        if (revision > 0 && currentRevision > 0 && revision > currentRevision + 1) {
          await refreshFileTreeSnapshot(sessionId, true);
          return;
        }
        if (revision > 0 && revision < currentRevision) {
          return;
        }
        if (Array.isArray(parsed.tree)) {
          const nextTree = parsed.tree as FileTreeNode[];
          fileTreeRef.current = nextTree;
          setFileTree(nextTree);
        } else if (Array.isArray(parsed.directories)) {
          const nextTree = applyDirectoryPatch(fileTreeRef.current, parsed.directories as FileTreeNode[]);
          if (nextTree === null) {
            return;
          }
          fileTreeRef.current = nextTree;
          setFileTree(nextTree);
        }
        const nextRevision = Math.max(currentRevision, revision);
        fileTreeRevisionRef.current = nextRevision;
      }
    };

    const run = async () => {
      try {
        const revision = fileTreeRevisionRef.current;
        const query = revision > 0 ? `?since=${revision}` : '';
        const res = await apiFetch(`/api/sessions/${sessionId}/file-tree/events${query}`, {
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          throw new Error('连接项目结构事件流失败');
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
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
            await handleFileTreeEvent(eventStr);
          }
        }
        if (buffer.trim()) {
          await handleFileTreeEvent(buffer);
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          console.error(error);
          void refreshFileTreeSnapshot(sessionId, true).catch(console.error);
        }
      }
    };

    void run();

    return () => {
      controller.abort();
    };
  }, [refreshFileTreeSnapshot, sessionId]);

  const loadSessionContext = useCallback(
    async (options?: { silent?: boolean; targetSessionId?: string }) => {
      const targetSessionId = options?.targetSessionId ?? sessionId;
      if (!targetSessionId) return;

      const silent = options?.silent ?? false;
      if (!silent) {
        setIsContextLoading(true);
      }

      try {
        const res = await apiFetch(`/api/sessions/${targetSessionId}/context`);
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

  const handleClosePlanSteps = useCallback(async () => {
    setSessionContext((prev) =>
      prev
        ? {
            ...prev,
            planSteps: [],
          }
        : prev,
    );

    if (!sessionId) return;

    try {
      const res = await apiFetch(`/api/sessions/${sessionId}/tasks`, {
        method: 'DELETE',
      });
      const payload = await res.json();
      if (!res.ok) {
        throw new Error(String(payload.detail ?? '关闭计划失败'));
      }
      setSessionContext((prev) =>
        prev
          ? {
              ...prev,
              planState:
                payload.planState && typeof payload.planState === 'object'
                  ? payload.planState
                  : prev.planState,
              planSteps: Array.isArray(payload.planSteps)
                ? payload.planSteps as PlanStep[]
                : [],
            }
          : prev,
      );
    } catch (error) {
      console.error('关闭计划失败:', error);
      appMessage.error(getErrorMessage(error, '关闭计划失败'));
      void loadSessionContext({ silent: true });
    }
  }, [loadSessionContext, sessionId]);

  const [shouldRestoreSession, setShouldRestoreSession] = useState(() => {
    const lastSession = getLastSession();
    return !initialUrlState.sessionId && !!(lastSession && lastSession.workspace);
  });

  const [initialWorkspace] = useState(() => {
    const lastSession = getLastSession();
    return lastSession?.workspace ?? '';
  });

  const [showWorkspacePicker, setShowWorkspacePicker] = useState(() => {
    const lastSession = getLastSession();
    return !initialUrlState.sessionId && !(lastSession && lastSession.workspace);
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
    const res = await apiFetch('/api/models');
    const data: { models: ModelOption[] } = await res.json();
    const nextOptions = data.models ?? [];
    const storedDefaultModelId = localStorage.getItem(DEFAULT_MODEL_STORAGE_KEY) || null;
    const nextDefaultModelId =
      storedDefaultModelId && (nextOptions.length === 0 || nextOptions.some((option) => option.id === storedDefaultModelId))
        ? storedDefaultModelId
        : null;
    setModelOptions(nextOptions);
    setDefaultModelId(nextDefaultModelId);
    setSelectedModelId((prev) => {
      if (prev && nextOptions.some((option) => option.id === prev)) {
        return prev;
      }
      return nextDefaultModelId ?? nextOptions[0]?.id ?? prev ?? null;
    });
    return nextOptions;
  }, []);

  const loadAppSettings = useCallback(async () => {
    const res = await apiFetch('/api/settings');
    const data = normalizeAppSettings(await res.json());
    setAppSettings(data);
    return data;
  }, []);

  const saveAppSettings = useCallback(async (settings: AppSettings) => {
    const res = await apiFetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(String(data.detail ?? '保存设置失败'));
    }
    setAppSettings(normalizeAppSettings(data));
  }, []);

  const loadMcpServers = useCallback(async () => {
    const res = await apiFetch('/api/mcp/servers');
    const data: MCPServersPayload = await res.json();
    if (!res.ok) {
      throw new Error(String((data as { detail?: unknown }).detail ?? '读取 MCP 配置失败'));
    }
    setMcpServers(data.servers ?? []);
    setMcpConfigPath(data.configPath ?? null);
    return data;
  }, []);

  const loadModelConfigs = useCallback(async () => {
    const res = await apiFetch('/api/model-configs');
    const data: ModelConfigPayload = await res.json();
    setVisualModelProviders(data.providers ?? []);
    setModelConfigPath(data.configPath ?? null);
    await loadAppSettings();
    await loadMcpServers();
    return data;
  }, [loadAppSettings, loadMcpServers]);

  useEffect(() => {
    apiFetch('/api/workspaces')
      .then((res) => res.json())
      .then((data: { workspaces: WorkspaceOption[] }) => {
        const options = data.workspaces ?? [];
        setDirectoryTree(workspaceOptionsToDirectoryNodes(options));
        if (data.workspaces?.length && !initialWorkspace) {
          setSelectedWorkspace(data.workspaces[0].value);
        }
      })
      .catch(console.error);

    apiFetch('/api/models')
      .then((res) => res.json())
      .then((data: { models: ModelOption[] }) => {
        const nextOptions = data.models ?? [];
        const storedDefaultModelId = localStorage.getItem(DEFAULT_MODEL_STORAGE_KEY) || null;
        const nextDefaultModelId =
          storedDefaultModelId && (nextOptions.length === 0 || nextOptions.some((option) => option.id === storedDefaultModelId))
            ? storedDefaultModelId
            : null;
        setModelOptions(nextOptions);
        setDefaultModelId(nextDefaultModelId);
        setSelectedModelId((prev) => {
          if (prev && nextOptions.some((option) => option.id === prev)) {
            return prev;
          }
          return nextDefaultModelId ?? nextOptions[0]?.id ?? prev ?? null;
        });
      })
      .catch(console.error);

    apiFetch('/api/model-configs')
      .then((res) => res.json())
      .then((data: ModelConfigPayload) => {
        setVisualModelProviders(data.providers ?? []);
            setModelConfigPath(data.configPath ?? null);
      })
      .catch(console.error);

    apiFetch('/api/mcp/servers')
      .then((res) => res.json())
      .then((data: MCPServersPayload) => {
        setMcpServers(data.servers ?? []);
        setMcpConfigPath(data.configPath ?? null);
      })
      .catch(console.error);

    apiFetch('/api/plugins')
      .then((res) => res.json())
      .then((data: { plugins?: PluginSummary[] }) => {
        setAvailablePlugins(data.plugins ?? []);
      })
      .catch(console.error);
  }, [initialWorkspace]);

  const syncVisibleSessionSnapshot = useCallback((data: SessionPayload) => {
    setBackendMode(data.mode);
    const executionMode = normalizeExecutionMode(data.executionMode);
    setCurrentSessionExecutionMode(executionMode);
    setNewSessionExecutionMode(executionMode);
    setCurrentBaseWorkspace(data.baseWorkspace ?? data.workspace);
    setCurrentWorktreeBranch(data.worktreeBranch ?? null);
    setStartupError(data.startupError ?? null);
    if (isAgentMode(data.agentType)) {
      setSelectedAgentMode(data.agentType);
    }
    setSelectedModelId((prev) => resolveSelectedModelId(data, modelOptions) ?? prev ?? null);
    setSelectedReasoningEffort(normalizeReasoningEffort(data.reasoningEffort));
    setMessages(hydrateMessages(data.messages ?? [], data.thoughts, data.toolCalls));
    setCodeChanges(data.codeChanges ?? []);
    applyFileTreeSnapshot(data.fileTree ?? [], data.fileTreeRevision ?? null);
    setWebPreviewUrl(data.previewUrl ?? DEFAULT_WEB_PREVIEW_URL);
    setSelectedFilePath(data.selectedFilePath ?? '');
    setSelectedFileContent(data.selectedFileContent ?? '');
    setAvailableSkills(data.availableSkills ?? []);
    setIsLoading(Boolean(data.isGenerating));
  }, [applyFileTreeSnapshot, modelOptions]);

  const fetchSessionSnapshot = useCallback(async (targetSessionId: string) => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);
    try {
      const res = await apiFetch(`/api/sessions/${targetSessionId}`, {
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
    const baseWorkspace = data.baseWorkspace ?? data.workspace;
    currentSessionIdRef.current = data.sessionId;
    setSessionId(data.sessionId);
    setSelectedWorkspace(data.workspace);
    syncVisibleSessionSnapshot(data);
    setTerminalCwd(data.workspace ?? '');
    setTerminalBackend('subprocess');
    setManagedProcesses([]);
    setTerminalInfos([]);
    setActiveTerminalId(null);
    setSessionContext(null);
    setIsContextOpen(false);
    setIsTerminalOpen(false);
    setHasTerminalBeenOpened(false);
    setActivePlugin(null);
    saveLastSession(baseWorkspace);
    addRecentProject(baseWorkspace);
    setRecentProjects(getRecentProjects());
    setShowWorkspacePicker(false);
  }, [syncVisibleSessionSnapshot]);

  const loadSessionHistory = useCallback(async (options: LoadSessionHistoryOptions = {}) => {
    const offset = options.offset ?? 0;
    const append = options.append ?? false;
    setIsHistoryLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(SESSION_HISTORY_PAGE_SIZE),
        offset: String(offset),
      });
      const res = await apiFetch(`/api/sessions/history?${params.toString()}`);
      if (!res.ok) {
        throw new Error('读取历史会话失败');
      }
      const data = (await res.json()) as SessionHistoryResponse;
      const nextSessions = data.sessions ?? [];
      setSessionHistory((prev) => {
        if (!append) return nextSessions;
        const seen = new Set(prev.map((item) => item.sessionId));
        return [...prev, ...nextSessions.filter((item) => !seen.has(item.sessionId))];
      });
      setSessionHistoryHasMore(Boolean(data.hasMore));
      setSessionHistoryNextOffset(offset + nextSessions.length);
    } catch (error) {
      console.error(error);
    } finally {
      setIsHistoryLoading(false);
    }
  }, []);

  const loadMoreSessionHistory = useCallback(async () => {
    if (isHistoryLoading || !sessionHistoryHasMore) return;
    await loadSessionHistory({ offset: sessionHistoryNextOffset, append: true });
  }, [isHistoryLoading, loadSessionHistory, sessionHistoryHasMore, sessionHistoryNextOffset]);

  const persistKanbanCardAiState = useCallback(
    async (cardId: string, aiState: KanbanAiState | null) => {
      if (!selectedWorkspace || !cardId) return;
      try {
        const response = await apiFetch(
          `/api/workspaces/${encodeURIComponent(selectedWorkspace)}/kanban/cards/${cardId}`,
          {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ aiState }),
          },
        );
        if (!response.ok) {
          throw new Error(await readApiError(response, '更新卡片 AI 状态失败'));
        }
      } catch (error) {
        console.error(error);
        appMessage.error(getErrorMessage(error, '确认删除失败'));
      }
    },
    [selectedWorkspace],
  );

  const createSessionWithWorkspace = useCallback(async (
    workspace: string,
    options?: { agentMode?: AgentMode; executionMode?: SessionExecutionMode; initializeGitRepository?: boolean },
  ) => {
    setIsSessionBooting(true);
    setSessionError(null);

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 60000);
      const newSessionModelId =
        defaultModelId && (modelOptions.length === 0 || modelOptions.some((option) => option.id === defaultModelId))
          ? defaultModelId
          : selectedModelId;

      const res = await apiFetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace,
          initialize_git_repository: options?.initializeGitRepository ?? false,
          model: newSessionModelId,
          reasoning_effort: selectedReasoningEffort,
          agent_type: resolveAgentModeForRequest(options?.agentMode ?? selectedAgentMode),
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
      return data;
    } catch (error) {
      console.error(error);
      const errorMessage =
        error instanceof DOMException && error.name === 'AbortError'
          ? '创建会话超时（60秒），请检查后端是否正常运行'
          : getErrorMessage(error, '创建会话失败');
      if (error instanceof DOMException && error.name === 'AbortError') {
        setSessionError(errorMessage);
      } else {
        setSessionError(errorMessage);
      }
      appMessage.error(errorMessage);
      return null;
    } finally {
      setIsSessionBooting(false);
    }
  }, [applySessionPayload, defaultModelId, loadSessionHistory, modelOptions, selectedAgentMode, selectedModelId, selectedReasoningEffort]);

  const refreshPlugins = useCallback(async (targetSessionId?: string | null) => {
    const endpoint = targetSessionId ? `/api/sessions/${targetSessionId}/plugins` : '/api/plugins';
    const response = await apiFetch(endpoint);
    const data = await response.json() as { plugins?: PluginSummary[] };
    setAvailablePlugins(data.plugins ?? []);
    return data.plugins ?? [];
  }, []);

  useEffect(() => {
    void refreshPlugins(sessionId);
  }, [refreshPlugins, sessionId]);

  const setPluginLoaded = useCallback(async (targetSessionId: string, pluginId: string, loaded: boolean) => {
    const response = await apiFetch(`/api/sessions/${targetSessionId}/plugins/${pluginId}/${loaded ? 'load' : 'unload'}`, {
      method: 'POST',
    });
    const data = await response.json() as { plugin?: PluginSummary; detail?: string };
    if (!response.ok) {
      throw new Error(String(data.detail ?? '切换插件加载状态失败'));
    }
    if (data.plugin) {
      setAvailablePlugins((prev) =>
        prev.map((plugin) => (plugin.id === data.plugin?.id ? { ...plugin, ...data.plugin } : plugin)),
      );
    }
    await refreshPlugins(targetSessionId);
  }, [refreshPlugins]);

  const handleActivePluginChange = useCallback(
    async (pluginId: string | null) => {
      try {
        const previousPlugin = activePlugin;
        let targetSessionId = sessionId;
        if (!targetSessionId && pluginId) {
          const created = await createSessionWithWorkspace(currentBaseWorkspace || selectedWorkspace);
          targetSessionId = created?.sessionId ?? null;
        }

        if (targetSessionId && previousPlugin === 'project-docs' && pluginId !== 'project-docs') {
          await setPluginLoaded(targetSessionId, 'project-docs', false);
        }
        if (targetSessionId && pluginId === 'project-docs') {
          await setPluginLoaded(targetSessionId, 'project-docs', true);
        }
        setActivePlugin(pluginId);
      } catch (error) {
        console.error(error);
        appMessage.error(getErrorMessage(error, '切换插件失败'));
      }
    },
    [
      activePlugin,
      createSessionWithWorkspace,
      currentBaseWorkspace,
      selectedWorkspace,
      sessionId,
      setPluginLoaded,
    ],
  );

  useEffect(() => {
    if (!sessionId) return;
    const docsPlugin = availablePlugins.find((plugin) => plugin.id === 'project-docs');
    if (!docsPlugin) return;
    if (activePlugin === 'project-docs' && !docsPlugin.loaded) {
      void setPluginLoaded(sessionId, 'project-docs', true);
      return;
    }
    if (activePlugin !== 'project-docs' && docsPlugin.loaded) {
      void setPluginLoaded(sessionId, 'project-docs', false);
    }
  }, [activePlugin, availablePlugins, sessionId, setPluginLoaded]);

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

    const hasRunningManagedProcess = managedProcesses.some((process) =>
      process.status === 'running' || process.status === 'orphaned'
    );
    const shouldKeepPolling = isLoading || hasRunningManagedProcess;

    const pollTerminalState = () =>
      refreshTerminalState({
        targetSessionId: sessionId,
        includeTerminals: true,
        silent: true,
      });

    void pollTerminalState();
    if (!shouldKeepPolling) {
      return;
    }
    const intervalId = setInterval(pollTerminalState, 2500);
    return () => clearInterval(intervalId);
  }, [hasTerminalBeenOpened, isLoading, isTerminalOpen, managedProcesses.length, refreshTerminalState, sessionId]);

  const createSession = async () => {
    const workspace = customWorkspace.trim() || selectedWorkspace;
    if (!workspace) {
      setSessionError('请选择或输入一个工作区路径');
      appMessage.warning('请选择或输入一个工作区路径');
      return;
    }
    await createSessionWithWorkspace(workspace, { initializeGitRepository });
  };

  const handleOpenRecentProject = async (workspace: string) => {
    setSelectedWorkspace(workspace);
    setCustomWorkspace('');
    await createSessionWithWorkspace(workspace, { initializeGitRepository });
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
      const res = await apiFetch(`/api/directories?${query.toString()}`);
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
      appMessage.error(getErrorMessage(error, '读取目录失败'));
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

  const loadFileForSession = useCallback(async (targetSessionId: string, path: string) => {
    setSelectedFilePath(path);
    try {
      const query = new URLSearchParams({ session_id: targetSessionId, path });
      const res = await apiFetch(`/api/files?${query.toString()}`);
      const data = await res.json();
      setSelectedFilePath(data.selectedFilePath ?? path);
      setSelectedFileContent(data.selectedFileContent ?? '');
    } catch (error) {
      console.error(error);
      appMessage.error(getErrorMessage(error, '打开文件失败'));
    }
  }, []);

  const loadFile = useCallback(async (path: string) => {
    if (!sessionId) return;

    await loadFileForSession(sessionId, path);
  }, [loadFileForSession, sessionId]);

  const saveFile = useCallback(
    async (path: string, content: string) => {
      if (!sessionId) return;

      const query = new URLSearchParams({ session_id: sessionId, path });
      const res = await apiFetch(`/api/files?${query.toString()}`, {
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
        includeTerminals: isTerminalOpen,
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
        const res = await apiFetch(`/api/sessions/${sessionId}`);
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

  const handleTerminalToggle = useCallback(() => {
    setHasTerminalBeenOpened(true);
    setIsTerminalOpen((prev) => !prev);
  }, []);

  const createTerminal = useCallback(async (cwd?: string) => {
    if (!sessionId) return null;
    try {
      const res = await apiFetch(`/api/sessions/${sessionId}/terminals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cwd: cwd || undefined }),
      });
      if (!res.ok) throw new Error('创建终端失败');
      const data = await res.json();
      const newTerminalId = data.terminalId as string;
      await refreshTerminalState({ includeTerminals: true, silent: true });
      return newTerminalId;
    } catch (error) {
      console.error(error);
      appMessage.error(getErrorMessage(error, '创建终端失败'));
      return null;
    }
  }, [refreshTerminalState, sessionId]);

  const closeTerminal = useCallback(async (terminalId: string) => {
    if (!sessionId) return;
    try {
      const res = await apiFetch(`/api/sessions/${sessionId}/terminals/${terminalId}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('关闭终端失败');
      if (activeTerminalId === terminalId) {
        const defaultTerminal = terminalInfos.find((t) => t.isDefault);
        setActiveTerminalId(defaultTerminal?.terminalId ?? terminalInfos[0]?.terminalId ?? null);
      }
      await refreshTerminalState({ includeTerminals: true, silent: true });
      appMessage.success('终端已关闭');
    } catch (error) {
      console.error(error);
      appMessage.error(getErrorMessage(error, '关闭终端失败'));
    }
  }, [activeTerminalId, refreshTerminalState, sessionId, terminalInfos]);

  const terminateManagedProcess = useCallback(
    async (terminalId: string) => {
      if (!sessionId || !terminalId) return;
      setIsStoppingProcesses(true);
      try {
        const res = await apiFetch(`/api/sessions/${sessionId}/processes/${terminalId}/terminate`, {
          method: 'POST',
        });
        if (!res.ok) {
          throw new Error('终止 AI 进程失败');
        }
        await refreshTerminalState({
          targetSessionId: sessionId,
          includeProcesses: true,
          includeTerminals: true,
        });
        appMessage.success('AI 进程已终止');
      } catch (error) {
        console.error(error);
        appMessage.error(getErrorMessage(error, '终止 AI 进程失败'));
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
        const res = await apiFetch(`/api/sessions/${currentSessionId}/stop`, {
          method: 'POST',
        });
        if (!res.ok) {
          throw new Error('停止 AI 执行失败');
        }
        const data = await res.json();
        setManagedProcesses(Array.isArray(data.remaining) ? data.remaining : []);
        appMessage.success('AI 执行已停止');
      } catch (error) {
        console.error(error);
        appMessage.error(getErrorMessage(error, '停止 AI 执行失败'));
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
        const errorMessage =
          error instanceof DOMException && error.name === 'AbortError'
            ? '恢复会话超时，请重试'
            : getErrorMessage(error, '恢复历史会话失败');
        if (error instanceof DOMException && error.name === 'AbortError') {
          setSessionError(errorMessage);
        } else {
          setSessionError(errorMessage);
        }
        appMessage.error(errorMessage);
      } finally {
        setIsSessionBooting(false);
      }
    },
    [applySessionPayload, fetchSessionSnapshot, sessionId]
  );

  const applyUrlState = useCallback(
    async (nextState: UrlAppState) => {
      isApplyingUrlStateRef.current = true;
      setActivePlugin(nextState.activePlugin);
      setIsRightPanelCollapsed(!nextState.isEditorOpen);
      setIsGitPanelOpen(nextState.isGitPanelOpen);
      setIsContextOpen(nextState.isContextOpen);
      setIsTerminalOpen(nextState.isTerminalOpen);
      setHasTerminalBeenOpened((prev) => prev || nextState.isTerminalOpen);
      setIsWebPreviewOpen(nextState.isWebPreviewOpen);

      try {
        if (nextState.sessionId && nextState.sessionId !== currentSessionIdRef.current) {
          await restoreSession(nextState.sessionId);
        }
        if (nextState.filePath) {
          const targetSessionId = nextState.sessionId ?? currentSessionIdRef.current;
          if (targetSessionId) {
            await loadFileForSession(targetSessionId, nextState.filePath);
          }
        } else if (nextState.isEditorOpen) {
          setSelectedFilePath('');
          setSelectedFileContent('');
        }
        if (nextState.isContextOpen) {
          void loadSessionContext({ silent: true, targetSessionId: nextState.sessionId ?? undefined });
        }
      } finally {
        window.setTimeout(() => {
          isApplyingUrlStateRef.current = false;
          shouldDeferInitialUrlSyncRef.current = false;
        }, 0);
      }
    },
    [loadFileForSession, loadSessionContext, restoreSession],
  );

  const hasAppliedInitialUrlStateRef = useRef(false);

  useEffect(() => {
    if (hasAppliedInitialUrlStateRef.current) {
      return;
    }
    if (!initialUrlState.sessionId && !initialUrlState.filePath && !initialUrlState.isContextOpen) {
      return;
    }

    hasAppliedInitialUrlStateRef.current = true;
    window.setTimeout(() => {
      void applyUrlState(initialUrlState);
    }, 0);
  }, [applyUrlState, initialUrlState]);

  useEffect(() => {
    const handlePopState = () => {
      void applyUrlState(getUrlAppState());
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [applyUrlState]);

  const handleDefaultModelChange = useCallback((modelId: string) => {
    if (defaultModelId === modelId) return;
    localStorage.setItem(DEFAULT_MODEL_STORAGE_KEY, modelId);
    setDefaultModelId(modelId);
    if (!sessionId) {
      setSelectedModelId(modelId);
    }
    appMessage.success('默认模型已更新');
  }, [defaultModelId, sessionId]);

  const handleModelChange = useCallback(
    async (modelId: string) => {
      if (!sessionId) return;
      try {
        const res = await apiFetch(`/api/sessions/${sessionId}/model`, {
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
        appMessage.success('模型已切换');
      } catch (error) {
        console.error(error);
        const errorMessage = getErrorMessage(error, '切换模型失败');
        setSessionError(errorMessage);
        appMessage.error(errorMessage);
      }
    },
    [modelOptions, selectedReasoningEffort, sessionId],
  );

  const handleOpenProject = useCallback(
    async (target: 'editor' | 'explorer', editor?: string, label?: string) => {
      if (!sessionId) return;
      try {
        const res = await apiFetch(`/api/sessions/${sessionId}/open-workspace`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(target === 'editor' ? { target, editor } : { target }),
        });
        if (!res.ok) {
          let message = '打开项目失败';
          try {
            const data = await res.json();
            message = String(data.detail ?? data.error ?? message);
          } catch {
            message = (await res.text()) || message;
          }
          throw new Error(message);
        }
        appMessage.success(target === 'explorer' ? '已打开文件资源管理器' : `已在 ${label ?? editor} 打开项目`);
      } catch (error) {
        console.error(error);
        appMessage.error(getErrorMessage(error, '打开项目失败'));
      }
    },
    [sessionId],
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
        const res = await apiFetch(`/api/sessions/${sessionId}/model`, {
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
        appMessage.success('思考程度已切换');
      } catch (error) {
        console.error(error);
        setSelectedReasoningEffort(previous);
        const errorMessage = getErrorMessage(error, '切换思考程度失败');
        setSessionError(errorMessage);
        appMessage.error(errorMessage);
      }
    },
    [modelOptions, selectedModelId, selectedReasoningEffort, sessionId],
  );

  const handleNewSession = useCallback(() => {
    void createSessionWithWorkspace(currentBaseWorkspace || selectedWorkspace);
  }, [createSessionWithWorkspace, currentBaseWorkspace, selectedWorkspace]);

  const saveModelProviders = useCallback(
    async (providers: UIModelProvider[]) => {
      const res = await apiFetch('/api/model-configs', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ providers }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(String(data.detail ?? '保存模型配置失败'));
      }
      setVisualModelProviders(data.providers ?? []);
      setModelConfigPath(data.configPath ?? null);
      await loadModels();
    },
    [loadModels],
  );

  const discoverProviderModels = useCallback(async (provider: UIModelProvider) => {
    const res = await apiFetch('/api/model-configs/discover-models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(provider),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(String(data.detail ?? '拉取模型列表失败'));
    }
    return {
      models: Array.isArray(data.models) ? (data.models as UIModelProvider['models']) : [],
    };
  }, []);

  const testModelConnection = useCallback(
    async (provider: UIModelProvider, model: string | null) => {
      const res = await apiFetch('/api/model-configs/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, model }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(String(data.detail ?? '模型连接测试失败'));
      }
      return data as ModelConnectionTestResult;
    },
    [],
  );

  const saveMcpServers = useCallback(async (servers: MCPServerConfig[]) => {
    const res = await apiFetch('/api/mcp/servers', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ servers }),
    });
    const data: MCPServersPayload = await res.json();
    if (!res.ok) {
      throw new Error(String((data as { detail?: unknown }).detail ?? '保存 MCP 配置失败'));
    }
    setMcpServers(data.servers ?? []);
    setMcpConfigPath(data.configPath ?? null);
  }, []);

  const testMcpServer = useCallback(async (server: MCPServerConfig) => {
    const serverId = encodeURIComponent(server.id || 'draft');
    const res = await apiFetch(`/api/mcp/servers/${serverId}/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ server }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(String(data.detail ?? 'MCP 连接测试失败'));
    }
    return data as MCPServerTestResult;
  }, []);

  const testEmbeddingSettings = useCallback(async (embedding: AppSettings['embedding']) => {
    const res = await apiFetch('/api/settings/embedding/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(embedding),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(String(data.detail ?? 'Embedding 测试失败'));
    }
    const dimension = typeof data.dimension === 'number' ? data.dimension : null;
    return dimension
      ? `Embedding 测试成功，向量维度 ${dimension}`
      : 'Embedding 测试成功';
  }, []);

  const handleDeleteHistory = useCallback(
    async (targetSessionId: string) => {
      const deletedItem = sessionHistory.find((item) => item.sessionId === targetSessionId);
      if (!deletedItem) return;

      const remainingItems = sessionHistory.filter((item) => item.sessionId !== targetSessionId);
      setSessionHistory(remainingItems);

      apiFetch(`/api/sessions/${targetSessionId}`, { method: 'DELETE' })
        .then(async (res) => {
          if (!res.ok) {
            throw new Error(await readApiError(res, '删除历史会话失败'));
          }
          appMessage.success('历史会话已删除');
        })
        .catch((error) => {
          setSessionHistory((prev) => {
            const insertIdx = prev.findIndex(
              (item) => (item.updatedAt ?? 0) < (deletedItem.updatedAt ?? 0),
            );
            const next = [...prev];
            next.splice(insertIdx === -1 ? next.length : insertIdx, 0, deletedItem);
            return next;
          });
          const errorMessage = getErrorMessage(error, '删除历史会话失败，已恢复');
          setSessionError(errorMessage);
          appMessage.error(errorMessage);
        });

      if (targetSessionId !== sessionId) return;

      const nextItem = remainingItems[0];
      if (nextItem) {
        setSessionError(null);
        fetchSessionSnapshot(nextItem.sessionId)
          .then((data) => applySessionPayload(data))
          .catch((error) => {
            console.error(error);
            const errorMessage = getErrorMessage(error, '恢复历史会话失败');
            setSessionError(errorMessage);
            appMessage.error(errorMessage);
          });
        return;
      }

      setSessionId(null);
      setMessages([]);
      setCodeChanges([]);
      setFileTree([]);
      fileTreeRef.current = [];
      fileTreeRevisionRef.current = 0;
      setTerminalCwd('');
      setTerminalBackend('subprocess');
      setSelectedFileContent('');
      setSelectedFilePath('');
      setCurrentSessionExecutionMode('local');
      setCurrentBaseWorkspace('');
      setCurrentWorktreeBranch(null);
      setSessionContext(null);
      setIsContextOpen(false);
      setShowWorkspacePicker(true);
      clearLastSession();
    },
    [fetchSessionSnapshot, applySessionPayload, sessionHistory, sessionId],
  );

  const streamAssistantResponse = useCallback(async ({
    url,
    body,
    streamSessionId,
    initialAssistantId,
    userVisibleMessage,
    userVisibleAttachments,
    clearComposer,
    onSessionStateChange,
    onPlanStepsChange,
    onAssistantTextChange,
    onToolCallStart,
    onStreamComplete,
    onStreamError,
  }: {
    url: string;
    body: Record<string, unknown>;
    streamSessionId: string;
    initialAssistantId?: string | null;
    userVisibleMessage?: string | null;
    userVisibleAttachments?: ChatAttachment[];
    clearComposer?: boolean;
    onSessionStateChange?: (payload: Partial<SessionContextPayload>) => void;
    onPlanStepsChange?: (steps: PlanStep[]) => void;
    onAssistantTextChange?: (text: string) => void;
    onToolCallStart?: (toolName: string) => void;
    onStreamComplete?: () => void;
    onStreamError?: (message: string) => void;
  }) => {
    if (!streamSessionId || isLoading) return;

    if (clearComposer) {
      setInput('');
      setElementAttachments([]);
    }
    if (userVisibleMessage || (userVisibleAttachments?.length ?? 0) > 0) {
      setMessages((prev) => [
        ...prev,
        {
          id: Math.random().toString(),
          role: 'user',
          content: userVisibleMessage ?? '',
          attachments: userVisibleAttachments,
        },
      ]);
    }

    setIsLoading(true);
    const abortController = new AbortController();
    activeRequestRef.current = abortController;
    activeStreamSessionIdRef.current = streamSessionId;
    const requestStartedAt = Date.now();
    const optimisticAssistantId =
      initialAssistantId ??
      `pending-assistant-${requestStartedAt}-${Math.random().toString(36).slice(2)}`;

    if (currentSessionIdRef.current === streamSessionId) {
      setMessages((prev) => {
        if (initialAssistantId) {
          return prev.map((message) =>
            message.role === 'assistant' && message.id === initialAssistantId
              ? { ...message, startTime: message.startTime ?? requestStartedAt }
              : message,
          );
        }
        if (prev.some((message) => message.id === optimisticAssistantId)) {
          return prev;
        }
        return [
          ...prev,
          {
            id: optimisticAssistantId,
            role: 'assistant' as const,
            content: '',
            thoughts: '',
            toolCalls: [],
            parts: [],
            startTime: requestStartedAt,
          },
        ];
      });
    }

    try {
      const retryAssistantId = optimisticAssistantId;
      let retryThoughtText = '';
      let retryCount = 0;
      let completed = false;
      const isVisibleStreamSession = () => currentSessionIdRef.current === streamSessionId;
      const upsertRetryThought = (text: string) => {
        if (!isVisibleStreamSession()) {
          return;
        }
        retryThoughtText = retryThoughtText ? `${retryThoughtText}\n\n${text}` : text;
        setMessages((prev) => {
          let found = false;
          const next = prev.map((message) => {
            if (message.id !== retryAssistantId) {
              return message;
            }
            found = true;
            return {
              ...message,
              thoughts: retryThoughtText,
              parts: [{ type: 'thinking' as const, text: retryThoughtText }],
            };
          });
          if (found) {
            return next;
          }
          return [
            ...next,
            {
              id: retryAssistantId,
              role: 'assistant' as const,
              content: '',
              thoughts: retryThoughtText,
              toolCalls: [],
              parts: [{ type: 'thinking' as const, text: retryThoughtText }],
              startTime: requestStartedAt,
            },
          ];
        });
      };

      while (!completed) {
        let sawStreamEvent = false;
        try {
          const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: abortController.signal,
          });

          if (!res.ok) {
            const errorText = await readApiError(res, `请求失败：HTTP ${res.status}`);
            throw new StreamHttpError(errorText, res.status);
          }

          if (!res.body) {
            throw new Error('流式响应为空');
          }

          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          let currentAssistantId = optimisticAssistantId;
          const toolNamesById = new Map<string, string>();
          const toolInputBuffersById = new Map<string, string>();
          const assistantTextById = new Map<string, string>();
          let hadStreamError = false;

      const ensureMessageStartTime = (message: ChatMessage): ChatMessage => {
        if (typeof message.startTime === 'number' && Number.isFinite(message.startTime)) {
          return message;
        }
        const elapsedOffset =
          typeof message.thinkingTime === 'number' && Number.isFinite(message.thinkingTime)
            ? message.thinkingTime * 1000
            : 0;
        return {
          ...message,
          startTime: requestStartedAt - elapsedOffset,
        };
      };

      const pendingUpdates = new Map<string, ((message: ChatMessage) => ChatMessage)[]>();
      let rafHandle: number | null = null;
      let toolDeltaCharsSincePaint = 0;
      let toolDeltaEventsSincePaint = 0;

      const flushPendingUpdates = () => {
        if (pendingUpdates.size === 0) {
          rafHandle = null;
          return;
        }
        const updates = new Map(pendingUpdates);
        pendingUpdates.clear();
        rafHandle = null;
        setMessages((prev) => {
          let changed = false;
          const next = prev.map((message) => {
            if (message.role === 'assistant' && updates.has(message.id)) {
              const updaters = updates.get(message.id)!;
              let updated = ensureMessageStartTime(message);
              for (const fn of updaters) {
                updated = fn(updated);
              }
              changed = true;
              return updated;
            }
            return message;
          });
          for (const [id, updaters] of updates) {
            if (!next.some((m) => m.id === id)) {
              let msg: ChatMessage = ensureMessageStartTime({ id, role: 'assistant', content: '', thoughts: '', toolCalls: [], parts: [] });
              for (const fn of updaters) {
                msg = fn(msg);
              }
              next.push(msg);
              changed = true;
            }
          }
          return changed ? next : prev;
        });
      };

      const scheduleFlush = () => {
        if (rafHandle !== null) return;
        rafHandle = requestAnimationFrame(flushPendingUpdates);
      };

      const flushImmediately = () => {
        if (rafHandle !== null) {
          cancelAnimationFrame(rafHandle);
          rafHandle = null;
        }
        flushPendingUpdates();
      };

      const updateAssistantMessage = (
        assistantId: string,
        updater: (message: ChatMessage) => ChatMessage,
        immediate = false
      ) => {
        if (!isVisibleStreamSession()) {
          return;
        }
        const list = pendingUpdates.get(assistantId);
        if (list) {
          list.push(updater);
        } else {
          pendingUpdates.set(assistantId, [updater]);
        }
        if (immediate) {
          flushImmediately();
        } else {
          scheduleFlush();
        }
      };

      const waitForNextPaint = () =>
        new Promise<void>((resolve) => {
          if (document.visibilityState === 'hidden') {
            window.setTimeout(resolve, 0);
            return;
          }
          requestAnimationFrame(() => {
            window.setTimeout(resolve, 0);
          });
        });

      const normalizeStreamUsage = (value: unknown): Partial<SessionTokenUsage> | null => {
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
          return null;
        }
        const source = value as Record<string, unknown>;
        const usage: Partial<SessionTokenUsage> = {};
        const numberKeys = [
          'inputTokens',
          'outputTokens',
          'reasoningTokens',
          'cachedInputTokens',
          'totalTokens',
        ] as const;
        for (const key of numberKeys) {
          const rawValue = source[key];
          if (typeof rawValue === 'number' && Number.isFinite(rawValue)) {
            usage[key] = Math.max(Math.round(rawValue), 0);
          }
        }
        return Object.keys(usage).length > 0 ? usage : null;
      };

      const markFirstTokenLatency = (message: ChatMessage): ChatMessage => {
        if (
          typeof message.firstTokenLatencyMs === 'number' &&
          Number.isFinite(message.firstTokenLatencyMs)
        ) {
          return message;
        }
        const startedAt =
          typeof message.startTime === 'number' && Number.isFinite(message.startTime)
            ? message.startTime
            : requestStartedAt;
        const normalizedStartTime = startedAt < 1_000_000_000_000 ? startedAt * 1000 : startedAt;
        return {
          ...message,
          startTime: message.startTime ?? requestStartedAt,
          firstTokenLatencyMs: Math.max(Math.round(Date.now() - normalizedStartTime), 0),
        };
      };

      const adoptAssistantId = (nextAssistantId: string) => {
        const normalizedNextId = String(nextAssistantId || '').trim();
        if (!normalizedNextId || normalizedNextId === currentAssistantId) {
          return;
        }
        const previousAssistantId = currentAssistantId;
        currentAssistantId = normalizedNextId;
        const previousText = assistantTextById.get(previousAssistantId);
        if (previousText !== undefined && !assistantTextById.has(normalizedNextId)) {
          assistantTextById.set(normalizedNextId, previousText);
        }
        assistantTextById.delete(previousAssistantId);
        if (!isVisibleStreamSession()) {
          return;
        }
        setMessages((prev) => {
          const hasNext = prev.some(
            (message) => message.role === 'assistant' && message.id === normalizedNextId,
          );
          if (hasNext) {
            return prev
              .filter(
                (message) =>
                  !(message.role === 'assistant' && message.id === previousAssistantId),
              )
              .map((message) =>
                message.role === 'assistant' && message.id === normalizedNextId
                  ? { ...message, startTime: message.startTime ?? requestStartedAt }
                  : message,
              );
          }
          let renamed = false;
          const next = prev.map((message) => {
            if (message.role !== 'assistant' || message.id !== previousAssistantId) {
              return message;
            }
            renamed = true;
            return {
              ...message,
              id: normalizedNextId,
              startTime: message.startTime ?? requestStartedAt,
            };
          });
          return renamed ? next : prev;
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

          sawStreamEvent = true;
          const data = JSON.parse(rawData);
          const appendToLastPart = (message: ChatMessage, partType: 'thinking' | 'text', delta: string): ContentBlock[] => {
            const parts = message.parts ?? [];
            const last = parts[parts.length - 1];
            if (last && last.type === partType) {
              return [...parts.slice(0, -1), { ...last, text: last.text + delta }];
            }
            return [...parts, { type: partType, text: delta }];
          };
          const normalizeThoughtKey = (value: string) => value.trim().replace(/\s+/g, ' ');
          const mergeThinkingDelta = (message: ChatMessage, delta: string): ChatMessage => {
            if (!delta) return message;
            const parts = message.parts ?? [];
            const nextThoughts = `${message.thoughts ?? ''}${delta}`;
            const lastMergeableThinkingIndex = [...parts]
              .map((part, index) => ({ part, index }))
              .reverse()
              .find(({ part, index }) => {
                if (part.type !== 'thinking') return false;
                return !parts
                  .slice(index + 1)
                  .some((nextPart) => nextPart.type === 'tool_call' || nextPart.type === 'text');
              })?.index;

            if (lastMergeableThinkingIndex !== undefined) {
              const existingPart = parts[lastMergeableThinkingIndex] as Extract<ContentBlock, { type: 'thinking' }>;
              const nextText = `${existingPart.text}${delta}`;
              const nextParts = [...parts];
              nextParts[lastMergeableThinkingIndex] = { ...existingPart, text: nextText };
              return {
                ...message,
                thoughts: nextThoughts,
                parts: nextParts,
              };
            }

            const textIdx = parts.findIndex((p) => p.type === 'text');
            const nextParts = textIdx === -1
              ? [...parts, { type: 'thinking' as const, text: delta }]
              : [...parts.slice(0, textIdx), { type: 'thinking' as const, text: delta }, ...parts.slice(textIdx)];
            return {
              ...message,
              thoughts: nextThoughts,
              parts: nextParts,
            };
          };
          const mergeThinkingSnapshot = (message: ChatMessage, nextThought: string): ChatMessage => {
            if (!nextThought) return message;
            const parts = message.parts ?? [];
            const nextThoughtKey = normalizeThoughtKey(nextThought);
            const thinkingEntries = parts
              .map((part, index) => ({ part, index }))
              .filter(
                (entry): entry is { part: Extract<ContentBlock, { type: 'thinking' }>; index: number } =>
                  entry.part.type === 'thinking',
              );
            const matchingEntry = [...thinkingEntries]
              .reverse()
              .find(({ part }) => {
                const existingKey = normalizeThoughtKey(part.text);
                return (
                  existingKey === nextThoughtKey ||
                  nextThoughtKey.startsWith(existingKey) ||
                  existingKey.startsWith(nextThoughtKey)
                );
              });

            if (matchingEntry) {
              const nextParts = parts.filter(
                (part, index) =>
                  part.type !== 'thinking' ||
                  index === matchingEntry.index ||
                  normalizeThoughtKey(part.text) !== nextThoughtKey,
              );
              const adjustedIndex = nextParts.findIndex(
                (part) => part.type === 'thinking' && normalizeThoughtKey(part.text) === normalizeThoughtKey(matchingEntry.part.text),
              );
              if (adjustedIndex >= 0 && nextParts[adjustedIndex].type === 'thinking') {
                nextParts[adjustedIndex] = { ...nextParts[adjustedIndex], text: nextThought };
              }
              return {
                ...message,
                thoughts: nextThought,
                parts: nextParts,
              };
            }

            if (message.thoughts?.trim()) {
              return message;
            }

            const textIdx = parts.findIndex((p) => p.type === 'text');
            const nextParts = textIdx === -1
              ? [...parts, { type: 'thinking' as const, text: nextThought }]
              : [...parts.slice(0, textIdx), { type: 'thinking' as const, text: nextThought }, ...parts.slice(textIdx)];
            return {
              ...message,
              thoughts: nextThought,
              parts: nextParts,
            };
          };

          const updateToolPart = (
            assistantId: string,
            toolCallId: string,
            updater: (toolCall: ToolCallRecord) => ToolCallRecord,
            immediate = true
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
            }), immediate);
          };

          const syncGitCommitStatusPreview = async (
            assistantId: string,
            toolCallId: string,
          ) => {
            if (!isVisibleStreamSession()) {
              return;
            }
            try {
              const res = await apiFetch(`/api/sessions/${streamSessionId}/git/status`);
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
            updater: (toolCall: ToolCallRecord) => ToolCallRecord,
            immediate = true,
            stampFirstTokenLatency = false
          ) => {
            updateAssistantMessage(assistantId, (message) => {
              const baseMessage = stampFirstTokenLatency
                ? markFirstTokenLatency(message)
                : message;
              let found = false;
              const toolCalls = (baseMessage.toolCalls ?? []).map((tc) => {
                if (tc.id !== toolCallId) return tc;
                found = true;
                return updater(tc);
              });
              const nextToolCalls = found ? toolCalls : [...toolCalls, updater(createToolCall())];

              let foundPart = false;
              const parts = (baseMessage.parts ?? []).map((part) => {
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
                ...baseMessage,
                toolCalls: nextToolCalls,
                parts: nextParts
              };
            }, immediate);
          };

          const buildSubagentMetadata = (
            event: Pick<
              SubagentStreamEvent,
              'subagentId' | 'parentToolCallId' | 'parentAssistantId' | 'title' | 'task'
            >,
          ) => ({
            agentScope: 'subagent' as const,
            subagentId: event.subagentId ?? null,
            parentToolCallId: event.parentToolCallId ?? null,
            parentAssistantId: event.parentAssistantId ?? null,
            subagentTitle: event.title ?? '子智能体',
            subagentTask: event.task ?? '',
          });

          const upsertSubagentDataPart = (snapshot: SubagentSnapshot) => {
            const subagentId = String(snapshot.id ?? '').trim();
            const messageId = String(snapshot.messageId ?? (subagentId ? `subagent-message-${subagentId}` : '')).trim();
            if (!subagentId || !messageId) return;
            const metadata = buildSubagentMetadata({
              subagentId,
              parentToolCallId: snapshot.parentToolCallId,
              parentAssistantId: snapshot.parentAssistantId,
              title: snapshot.title,
              task: snapshot.task,
            });
            updateAssistantMessage(messageId, (message) => {
              const parts = message.parts ?? [];
              let replaced = false;
              const nextParts = parts.map((part) => {
                if (
                  part.type === 'data' &&
                  part.dataType === 'data-subagent-task' &&
                  typeof part.data === 'object' &&
                  part.data !== null &&
                  !Array.isArray(part.data) &&
                  String((part.data as { id?: unknown }).id ?? '') === subagentId
                ) {
                  replaced = true;
                  return { type: 'data' as const, dataType: 'data-subagent-task', data: snapshot };
                }
                return part;
              });
              if (!replaced) {
                nextParts.push({ type: 'data' as const, dataType: 'data-subagent-task', data: snapshot });
              }
              return {
                ...message,
                ...metadata,
                parts: nextParts,
              };
            }, true);
          };

          const replaceSubagentTextPart = (message: ChatMessage, text: string): ChatMessage => ({
            ...message,
            content: text,
            parts: [
              ...(message.parts ?? []).filter((part) => part.type !== 'text'),
              ...(text ? [{ type: 'text' as const, text }] : []),
            ],
          });

          const applySubagentEvent = (event: SubagentStreamEvent) => {
            const subagentId = String(event.subagentId ?? '').trim();
            const messageId = String(event.messageId ?? (subagentId ? `subagent-message-${subagentId}` : '')).trim();
            if (!subagentId || !messageId) return;

            const metadata = buildSubagentMetadata(event);
            const eventName = String(event.event ?? '');
            const ensureMessage = (immediate = true) => {
              updateAssistantMessage(messageId, (message) => ({
                ...message,
                ...metadata,
              }), immediate);
            };

            if (eventName === 'assistant_started') {
              ensureMessage(true);
              return;
            }

            if (eventName === 'thought_delta') {
              const delta = String(event.delta ?? '');
              updateAssistantMessage(messageId, (message) => ({
                ...mergeThinkingDelta(markFirstTokenLatency(message), delta),
                ...metadata,
              }), false);
              return;
            }

            if (eventName === 'thought') {
              const thought = String(event.thought ?? '');
              updateAssistantMessage(messageId, (message) => ({
                ...mergeThinkingSnapshot(markFirstTokenLatency(message), thought),
                ...metadata,
              }), true);
              return;
            }

            if (eventName === 'final_answer_delta') {
              const delta = String(event.delta ?? '');
              updateAssistantMessage(messageId, (message) => ({
                ...markFirstTokenLatency(message),
                ...metadata,
                content: `${message.content}${delta}`,
                parts: appendToLastPart(message, 'text', delta),
              }), false);
              return;
            }

            if (eventName === 'usage') {
              const usage = normalizeStreamUsage(event.usage);
              updateAssistantMessage(messageId, (message) => ({
                ...message,
                ...metadata,
                tokenUsage: usage ?? message.tokenUsage,
              }), true);
              return;
            }

            if (
              eventName === 'assistant_done' ||
              eventName === 'final' ||
              eventName === 'turn_finished' ||
              eventName === 'limit_reached'
            ) {
              const finalAnswer = String(event.finalAnswer ?? event.finalOutput ?? '');
              updateAssistantMessage(messageId, (message) => ({
                ...replaceSubagentTextPart(
                  markFirstTokenLatency(message),
                  finalAnswer || message.content,
                ),
                ...metadata,
              }), true);
              return;
            }

            if (eventName === 'error') {
              const errorText = String(event.error ?? event.message ?? '').trim();
              if (!errorText) {
                ensureMessage(true);
                return;
              }
              updateAssistantMessage(messageId, (message) => ({
                ...message,
                ...metadata,
                content: `${message.content}${message.content ? '\n' : ''}子智能体执行失败：${errorText}`,
                parts: appendToLastPart(message, 'text', `${message.content ? '\n' : ''}子智能体执行失败：${errorText}`),
              }), true);
              return;
            }

            if (eventName === 'tool_call' && event.toolCall) {
              const toolCallId = String(event.toolCall.id ?? '').trim();
              const toolName = String(event.toolCall.name ?? 'tool');
              if (!toolCallId) {
                ensureMessage(true);
                return;
              }
              const args = (
                event.toolCall.arguments &&
                typeof event.toolCall.arguments === 'object' &&
                !Array.isArray(event.toolCall.arguments)
              ) ? event.toolCall.arguments as Record<string, unknown> : {};
              upsertToolPart(
                messageId,
                toolCallId,
                () => ({
                  id: toolCallId,
                  name: toolName,
                  arguments: args,
                  state: 'running',
                  ...metadata,
                }),
                (toolCall) => ({
                  ...toolCall,
                  ...metadata,
                  id: toolCallId,
                  name: toolName,
                  arguments: args,
                  state: 'running',
                }),
                true,
                true,
              );
              return;
            }

            if (eventName === 'tool_result' && event.toolResult) {
              const toolCallId = String(
                event.toolCall?.id ??
                event.toolResult.tool_call_id ??
                event.toolResult.toolCallId ??
                '',
              ).trim();
              const toolName = String(event.toolCall?.name ?? event.toolResult.name ?? 'tool');
              if (!toolCallId) {
                ensureMessage(true);
                return;
              }
              const args = (
                event.toolCall?.arguments &&
                typeof event.toolCall.arguments === 'object' &&
                !Array.isArray(event.toolCall.arguments)
              ) ? event.toolCall.arguments as Record<string, unknown> : {};
              const nextState: ToolCallRecord['state'] = event.toolResult.success === false ? 'error' : 'completed';
              upsertToolPart(
                messageId,
                toolCallId,
                () => ({
                  id: toolCallId,
                  name: toolName,
                  arguments: args,
                  state: nextState,
                  ...metadata,
                }),
                (toolCall) => ({
                  ...toolCall,
                  ...metadata,
                  id: toolCallId,
                  name: toolName,
                  arguments: Object.keys(args).length > 0 ? args : toolCall.arguments,
                  output: event.toolResult?.output,
                  success: event.toolResult?.success ?? toolCall.success,
                  errorMessage: event.toolResult?.error_message ?? event.toolResult?.errorMessage ?? toolCall.errorMessage,
                  state: nextState,
                }),
              );
              return;
            }

            ensureMessage(false);
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
              refreshFileTreeAfterTerminalActivity(streamSessionId);
            }
            if (
              ['write_file', 'replace_file', 'apply_patch'].includes(toolName) ||
              (toolName === 'delete_file' && outputPayload?.requires_confirmation !== true)
            ) {
              void refreshTerminalState({
                includeFileTree: true,
                includeTerminals: isTerminalOpen,
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
            adoptAssistantId(data.messageId || currentAssistantId);
            assistantTextById.set(currentAssistantId, assistantTextById.get(currentAssistantId) ?? '');
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...message,
              startTime: message.startTime ?? requestStartedAt,
            }), true);
          } else if (data.type === 'text-delta') {
            currentAssistantId = currentAssistantId || Math.random().toString();
            const nextText = `${assistantTextById.get(currentAssistantId) ?? ''}${data.delta ?? ''}`;
            assistantTextById.set(currentAssistantId, nextText);
            onAssistantTextChange?.(nextText);
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...markFirstTokenLatency(message),
              content: `${message.content}${data.delta ?? ''}`,
              parts: appendToLastPart(message, 'text', data.delta ?? '')
            }), false);
          } else if (data.type === 'reasoning-delta') {
            const assistantId = currentAssistantId;
            if (!assistantId) return;
            updateAssistantMessage(assistantId, (message) => {
              const delta = data.delta ?? '';
              return mergeThinkingDelta(markFirstTokenLatency(message), delta);
            }, false);
          } else if (data.type === 'tool-input-available') {
            const assistantId = currentAssistantId;
            if (!assistantId) return;
            if (toolDeltaCharsSincePaint > 0 || toolDeltaEventsSincePaint > 0) {
              toolDeltaCharsSincePaint = 0;
              toolDeltaEventsSincePaint = 0;
              await waitForNextPaint();
            }
            const toolCallId = String(data.toolCallId ?? Math.random());
            const toolName = resolveStreamToolName(
              toolCallId,
              data.toolName,
              toolNamesById.get(toolCallId),
            );
            const toolCallRecord = {
              id: toolCallId,
              name: toolName,
              arguments: data.input ?? {},
              streamedInput: undefined,
              state: 'running' as const
            };
            onToolCallStart?.(toolCallRecord.name);
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
              }),
              true,
              true,
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
            const toolName = resolveStreamToolName(
              toolCallId,
              data.toolName,
              toolNamesById.get(toolCallId),
            );
            onToolCallStart?.(toolName);
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
              }),
              true,
              true,
            );
          } else if (data.type === 'tool-input-delta') {
            const assistantId = currentAssistantId;
            const toolCallId = String(data.toolCallId ?? '');
            if (!assistantId || !toolCallId) return;
            const delta = String(data.inputTextDelta ?? '');
            const toolName = resolveStreamToolName(
              toolCallId,
              data.toolName,
              toolNamesById.get(toolCallId),
            );
            toolNamesById.set(toolCallId, toolName);
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
                name: toolName,
                streamedInput: `${toolCall.streamedInput ?? ''}${delta}`,
                state: 'running'
              }),
              true,
              true,
            );
            toolDeltaCharsSincePaint += delta.length;
            toolDeltaEventsSincePaint += 1;
            if (toolDeltaCharsSincePaint >= 240 || toolDeltaEventsSincePaint >= 4) {
              toolDeltaCharsSincePaint = 0;
              toolDeltaEventsSincePaint = 0;
              await waitForNextPaint();
            }
          } else if (data.type === 'tool-output-available') {
            const assistantId = currentAssistantId;
            const toolCallId = String(data.toolCallId ?? '');
            if (!assistantId || !toolCallId) return;
            updateToolPart(assistantId, toolCallId, (toolCall) => ({
              ...toolCall,
              output: data.output,
              streamedInput: undefined,
              state: 'completed'
            }));
          } else if (data.type === 'data-tool-result') {
            const payload = (data.data ?? {}) as Record<string, unknown>;
            const assistantId = String(payload.assistant_id ?? currentAssistantId);
            const toolCallId = String(payload.id ?? '');
            if (!assistantId || !toolCallId) return;
            adoptAssistantId(assistantId);
            const toolName = resolveStreamToolName(
              toolCallId,
              payload.name,
              toolNamesById.get(toolCallId),
            );
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
              streamedInput: undefined,
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
            if (Array.isArray(steps)) {
              onPlanStepsChange?.(steps as PlanStep[]);
              setSessionContext((prev) =>
                prev
                  ? {
                      ...prev,
                      planSteps: steps as PlanStep[],
                    }
                  : prev
              );
            }
          } else if (data.type === 'data-session-state') {
            const payload = (
              data.data &&
              typeof data.data === 'object' &&
              !Array.isArray(data.data)
            ) ? data.data as Partial<SessionContextPayload> : {};
            onSessionStateChange?.(payload);
            if (typeof payload.workspace === 'string' && payload.workspace) {
              setSelectedWorkspace(payload.workspace);
              setTerminalCwd(payload.workspace);
            }
            if (payload.executionMode) {
              const executionMode = normalizeExecutionMode(payload.executionMode);
              setCurrentSessionExecutionMode(executionMode);
              setNewSessionExecutionMode(executionMode);
            }
            if (typeof payload.baseWorkspace === 'string') {
              setCurrentBaseWorkspace(payload.baseWorkspace);
            }
            if ('worktreeBranch' in payload) {
              setCurrentWorktreeBranch(payload.worktreeBranch ?? null);
            }
            setSessionContext((prev) =>
              prev
                ? {
                      ...prev,
                    workspace: payload.workspace ?? prev.workspace,
                    executionMode: payload.executionMode ?? prev.executionMode,
                    baseWorkspace: payload.baseWorkspace ?? prev.baseWorkspace,
                    worktreePath: payload.worktreePath ?? prev.worktreePath,
                    worktreeBranch: payload.worktreeBranch ?? prev.worktreeBranch,
                    agentType: payload.agentType ?? prev.agentType,
                    phase: payload.phase ?? prev.phase,
                    deployState: payload.deployState ?? prev.deployState,
                    planState: payload.planState ?? prev.planState,
                    taskState: payload.taskState ?? prev.taskState,
                    messageCount: payload.messageCount ?? prev.messageCount,
                    toolCallCount: payload.toolCallCount ?? prev.toolCallCount,
                    thoughtCount: payload.thoughtCount ?? prev.thoughtCount,
                    estimatedTokens: payload.estimatedTokens ?? prev.estimatedTokens,
                    maxTokens: payload.maxTokens ?? prev.maxTokens,
                    usage: payload.usage ?? prev.usage,
                    cumulativeUsage: payload.cumulativeUsage ?? prev.cumulativeUsage,
                    codeChangeCount: payload.codeChangeCount ?? prev.codeChangeCount,
                    recentCodeChanges: payload.recentCodeChanges ?? prev.recentCodeChanges,
                    planSteps: Array.isArray(payload.planSteps) ? payload.planSteps as PlanStep[] : prev.planSteps,
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
            // Terminal text is already streamed through the dedicated terminal socket.
          } else if (data.type === 'data-preview-url') {
            if (typeof data.data?.url === 'string' && isVisibleStreamSession()) {
              setWebPreviewUrl(data.data.url);
              setIsWebPreviewOpen(true);
            }
          } else if (data.type === 'data-subagent-event') {
            const payload = (
              data.data &&
              typeof data.data === 'object' &&
              !Array.isArray(data.data)
            ) ? data.data as SubagentStreamEvent : null;
            if (payload) {
              applySubagentEvent(payload);
            }
          } else if (data.type === 'data-subagent-task') {
            const payload = (
              data.data &&
              typeof data.data === 'object' &&
              !Array.isArray(data.data)
            ) ? data.data as SubagentSnapshot : null;
            if (payload) {
              upsertSubagentDataPart(payload);
            }
          } else if (data.type === 'data-plan-draft') {
            showStreamingPlanDraft(normalizePlanDraft(data.data), '计划草案');
            const assistantId = currentAssistantId;
            if (!assistantId) return;
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              parts: [...(message.parts ?? []), { type: 'data' as const, dataType: data.type, data: data.data }]
            }), true);
          } else if (data.type === 'data-assistant-reset') {
            adoptAssistantId(data.data?.id || currentAssistantId);
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...message,
              content: '',
              parts: (message.parts ?? []).filter((p) => p.type !== 'text')
            }), true);
          } else if (data.type === 'data-tool-call') {
            return;
          } else if (data.type === 'data-usage') {
            const payload = (
              data.data &&
              typeof data.data === 'object' &&
              !Array.isArray(data.data)
            ) ? data.data as Record<string, unknown> : {};
            const assistantId = String(payload.assistant_id ?? currentAssistantId);
            const usage = normalizeStreamUsage(payload.usage);
            if (!assistantId || !usage) return;
            adoptAssistantId(assistantId);
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              tokenUsage: usage,
            }), true);
          } else if (typeof data.type === 'string' && data.type.startsWith('data-')) {
            const assistantId = currentAssistantId;
            if (!assistantId) return;
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              parts: [...(message.parts ?? []), { type: 'data' as const, dataType: data.type, data: data.data }]
            }), true);
          } else if (data.type === 'finish') {
            flushImmediately();
            if (currentSessionIdRef.current === streamSessionId) {
              setIsLoading(false);
            }
          } else if (data.type === 'error') {
            hadStreamError = true;
            const nextText = `${assistantTextById.get(currentAssistantId) ?? ''}${data.errorText ?? ''}`;
            assistantTextById.set(currentAssistantId, nextText);
            onAssistantTextChange?.(nextText);
            if (data.errorText) {
              onStreamError?.(String(data.errorText));
            }
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...message,
              content: `${message.content}${data.errorText ?? ''}`,
              parts: appendToLastPart(message, 'text', data.errorText ?? '')
            }), true);
          } else if (data.type === 'assistant_started') {
            adoptAssistantId(data.payload.id || currentAssistantId);
            assistantTextById.set(currentAssistantId, assistantTextById.get(currentAssistantId) ?? '');
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...message,
              startTime: message.startTime ?? requestStartedAt,
            }), true);
          } else if (data.type === 'assistant_delta') {
            adoptAssistantId(data.payload.id || currentAssistantId);
            const nextText = `${assistantTextById.get(currentAssistantId) ?? ''}${data.payload.delta ?? ''}`;
            assistantTextById.set(currentAssistantId, nextText);
            onAssistantTextChange?.(nextText);
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...markFirstTokenLatency(message),
              content: `${message.content}${data.payload.delta ?? ''}`,
              parts: appendToLastPart(message, 'text', data.payload.delta ?? '')
            }), false);
          } else if (data.type === 'assistant_reset') {
            adoptAssistantId(data.payload.id || currentAssistantId);
            assistantTextById.set(currentAssistantId, '');
            onAssistantTextChange?.('');
            updateAssistantMessage(currentAssistantId, (message) => ({
              ...message,
              content: '',
              parts: (message.parts ?? []).filter((p) => p.type !== 'text')
            }), true);
          } else if (data.type === 'thought_delta') {
            const assistantId = data.payload.assistant_id || currentAssistantId;
            if (!assistantId) return;
            adoptAssistantId(assistantId);
            updateAssistantMessage(assistantId, (message) => {
              const delta = data.payload.delta ?? '';
              return mergeThinkingDelta(markFirstTokenLatency(message), delta);
            }, false);
          } else if (data.type === 'thought') {
            const assistantId = data.payload.assistant_id || currentAssistantId;
            if (!assistantId) return;
            adoptAssistantId(assistantId);
            updateAssistantMessage(assistantId, (message) => {
              const nextThought = String(data.payload.thought ?? '');
              return mergeThinkingSnapshot(markFirstTokenLatency(message), nextThought);
            }, true);
          } else if (data.type === 'tool_call') {
            const assistantId = data.payload.assistant_id || currentAssistantId;
            if (!assistantId) return;
            adoptAssistantId(assistantId);
            const toolCallRecord = { ...data.payload, state: 'running' as const };
            onToolCallStart?.(String(data.payload.name ?? 'tool'));
            if (data.payload.name === 'save_plan') {
              showStreamingPlanDraft(normalizePlanDraft(data.payload.arguments));
            }
            updateAssistantMessage(assistantId, (message) => ({
              ...markFirstTokenLatency(message),
              toolCalls: [...(message.toolCalls ?? []), toolCallRecord],
              parts: [...(message.parts ?? []), { type: 'tool_call' as const, toolCall: toolCallRecord }]
            }), true);
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
            adoptAssistantId(assistantId);
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
            }), true);
          } else if (data.type === 'usage') {
            const assistantId = data.payload.assistant_id || currentAssistantId;
            const usage = normalizeStreamUsage(data.payload.usage);
            if (!assistantId || !usage) return;
            adoptAssistantId(assistantId);
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              tokenUsage: usage,
            }), true);
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
      flushImmediately();
      if (!hadStreamError) {
        onStreamComplete?.();
      }
          completed = true;
        } catch (e) {
          if (isAbortError(e)) {
            return;
          }

          const errorMessage = getErrorMessage(e, 'AI 执行失败');
          const retryable = e instanceof StreamHttpError ? e.retryable : true;
          if (retryable && !sawStreamEvent && retryCount < STREAM_RETRY_LIMIT) {
            const delayMs = getRetryDelayMs(retryCount);
            const retryNumber = retryCount + 1;
            upsertRetryThought(
              `请求出错：${errorMessage}\n正在重试（${retryNumber}/${STREAM_RETRY_LIMIT}），等待 ${formatRetryDelay(delayMs)}。`,
            );
            retryCount += 1;
            try {
              await waitForRetryDelay(delayMs, abortController.signal);
            } catch (delayError) {
              if (isAbortError(delayError)) {
                return;
              }
              throw delayError;
            }
            continue;
          }

          console.error(e);
          if (!sawStreamEvent && retryCount >= STREAM_RETRY_LIMIT) {
            upsertRetryThought(
              `已重试 ${STREAM_RETRY_LIMIT} 次仍未成功，自动停止。\n最后错误：${errorMessage}`,
            );
          }
          appMessage.error(errorMessage);
          onStreamError?.(errorMessage);
          return;
        }
      }
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
          includeTerminals: isTerminalOpen,
          silent: true,
        });
        void loadSessionContext({ silent: !isContextOpen });
      }
      void loadSessionHistory();
    }
  }, [appendCodeChanges, applyTerminalSnapshot, isContextOpen, isLoading, isTerminalOpen, loadFile, loadSessionContext, loadSessionHistory, refreshFileTreeAfterTerminalActivity, refreshTerminalState, showStreamingPlanDraft]);

  const handleAddCodeContextToComposer = useCallback((context: CodeSelectionContext) => {
    const block = formatCodeSelectionContext(context);
    setInput((current) => {
      const base = current.replace(/\s+$/g, '');
      return base ? `${base}\n\n${block}` : block;
    });
    setComposerFocusRevision((current) => current + 1);
    appMessage.success('已加入代码上下文');
  }, []);

  const sendMessage = async (
    msg: string,
    elements?: { selector: string; html: string; sourceUrl?: string }[],
    attachments?: ChatAttachment[],
  ) => {
    const messageAttachments = attachments ?? [];
    if (
      (!msg.trim() && (!elements || elements.length === 0) && messageAttachments.length === 0) ||
      !sessionId ||
      isLoading
    ) return;

    const selectedSkills = extractSelectedSkillIds(msg);
    let finalMsg = msg.trim() || (elements?.length ? '请修改这个元素' : '请分析这些附件');
    if (elements && elements.length > 0) {
      const elementContext = elements.map((el, i) => {
        const urlPart = el.sourceUrl ? `\n来源页面: ${el.sourceUrl}` : '';
        return `[元素${i + 1} 选择器: ${el.selector}]${urlPart}\n${el.html}`;
      }).join('\n\n');
      finalMsg = `${elementContext}\n\n${finalMsg}`;
    }
    if (planData && planAnnotations.length > 0) {
      finalMsg = `${finalMsg}${formatPlanAnnotations(planAnnotations, planData.title)}`;
    }

    await streamAssistantResponse({
      url: apiUrl('/api/chat/stream'),
      body: {
        session_id: sessionId,
        message: finalMsg,
        execution_mode: currentSessionExecutionMode === 'worktree' ? 'worktree' : newSessionExecutionMode,
        agent_mode: resolveAgentModeForRequest(selectedAgentMode) ?? 'auto',
        super_autopilot: selectedAgentMode === 'super' && isSuperAutopilotEnabled,
        skills: selectedSkills,
        attachments: messageAttachments,
      },
      streamSessionId: sessionId,
      userVisibleMessage: finalMsg,
      userVisibleAttachments: messageAttachments.length > 0 ? messageAttachments : undefined,
      clearComposer: true,
    });
  };

  const continueAfterConfirmation = useCallback(async (assistantId: string) => {
    if (!sessionId || !assistantId) return;

    await streamAssistantResponse({
      url: apiUrl('/api/chat/continue'),
      body: { session_id: sessionId, assistant_id: assistantId },
      streamSessionId: sessionId,
      initialAssistantId: assistantId,
      clearComposer: false,
    });
  }, [sessionId, streamAssistantResponse]);

  const handleSendKanbanCardToAi = useCallback(
    async (card: KanbanCard) => {
      if (!sessionId) {
        appMessage.warning('请先创建或恢复一个会话');
        return;
      }
      if (isLoading) {
        appMessage.warning('AI 正在执行中，请稍后再发送卡片');
        return;
      }

      const message = formatKanbanCardTaskPrompt(card);
      setSelectedAgentMode('coding');
      const startedAt = new Date().toISOString();
      let latestPhase = 'planning';
      let latestSteps: PlanStep[] = buildDefaultKanbanPlanSteps();
      let latestAssistantText = '';
      let lastPersistedState = '';

      const persistState = async (state: KanbanAiState) => {
        const serialized = JSON.stringify(state);
        if (serialized === lastPersistedState) {
          return;
        }
        lastPersistedState = serialized;
        await persistKanbanCardAiState(card.id, state);
      };

      const initialState = buildKanbanAiState({
        sessionId,
        startedAt,
        phase: latestPhase,
        planSteps: latestSteps,
        status: 'running',
      });
      await persistState(initialState);

      void streamAssistantResponse({
        url: apiUrl('/api/chat/stream'),
        body: {
          session_id: sessionId,
          message,
          agent_mode: 'coding',
        },
        streamSessionId: sessionId,
        userVisibleMessage: message,
        clearComposer: true,
        onSessionStateChange: (payload) => {
          latestPhase = payload.phase ?? latestPhase;
          void persistState(buildKanbanAiState({
            sessionId,
            startedAt,
            phase: latestPhase,
            planSteps: latestSteps,
            status: payload.phase === 'failed' ? 'error' : 'running',
            result: latestAssistantText || null,
          }));
        },
        onPlanStepsChange: (steps) => {
          latestSteps = steps;
          void persistState(buildKanbanAiState({
            sessionId,
            startedAt,
            phase: latestPhase,
            planSteps: latestSteps,
            status: 'running',
            result: latestAssistantText || null,
          }));
        },
        onAssistantTextChange: (text) => {
          latestAssistantText = text;
        },
        onToolCallStart: (toolName) => {
          latestSteps = advanceKanbanPlanSteps(latestSteps, toolName);
          void persistState(buildKanbanAiState({
            sessionId,
            startedAt,
            phase: latestPhase,
            planSteps: latestSteps,
            status: 'running',
            result: latestAssistantText || null,
          }));
        },
        onStreamComplete: () => {
          void persistState(buildKanbanAiState({
            sessionId,
            startedAt,
            phase: 'completed',
            planSteps: latestSteps,
            status: 'completed',
            result: latestAssistantText || null,
            finishedAt: new Date().toISOString(),
          }));
        },
        onStreamError: (errorMessage) => {
          void persistState(buildKanbanAiState({
            sessionId,
            startedAt,
            phase: 'failed',
            planSteps: latestSteps,
            status: 'error',
            error: errorMessage,
            result: latestAssistantText || null,
            finishedAt: new Date().toISOString(),
          }));
        },
      });
      return initialState;
    },
    [isLoading, persistKanbanCardAiState, sessionId, streamAssistantResponse],
  );

  const resolveDeleteConfirmation = useCallback(
    async (toolCallId: string, approved: boolean) => {
      if (!sessionId) return;

      try {
        const res = await apiFetch(`/api/sessions/${sessionId}/tools/${toolCallId}/confirm-delete`, {
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
            includeTerminals: isTerminalOpen,
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
        appMessage.error(getErrorMessage(error, '确认操作失败'));
      }
    },
    [appendCodeChanges, continueAfterConfirmation, findAssistantIdByToolCallId, isTerminalOpen, refreshTerminalState, sessionId]
  );

  const resolveGitConfirmation = useCallback(
    async (toolCallId: string, type: 'commit' | 'tag', approved: boolean) => {
      if (!sessionId) return;

      try {
        const endpoint = type === 'commit' ? 'confirm-commit' : 'confirm-tag';
        const res = await apiFetch(`/api/sessions/${sessionId}/tools/${toolCallId}/${endpoint}`, {
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
            includeTerminals: isTerminalOpen,
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
        appMessage.error(getErrorMessage(error, '连接失败'));
      }
    },
    [continueAfterConfirmation, findAssistantIdByToolCallId, isTerminalOpen, refreshTerminalState, sessionId]
  );

  const resolveConnectInput = useCallback(
    async (toolCallId: string, values: Record<string, string>) => {
      if (!sessionId) return;

      try {
        const res = await apiFetch(`/api/sessions/${sessionId}/tools/${toolCallId}/connect`, {
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
        const error = new Error('未找到计划问题定义');
        appMessage.error(error.message);
        throw error;
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

      const res = await apiFetch(`/api/sessions/${sessionId}/tools/${toolCallId}/input`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers: payloadAnswers }),
      });
      const data = await res.json();
      if (!res.ok) {
        const error = new Error(String(data.detail ?? '提交失败'));
        appMessage.error(error.message);
        throw error;
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
      appMessage.success('已复制回答');
    } catch (error) {
      console.error(error);
      appMessage.error(getErrorMessage(error, '复制失败'));
    }
  }, []);

  const handleCompressConversation = useCallback(
    async (message: ChatMessage) => {
      if (!sessionId) {
        return;
      }

      setCompletionActionState({ messageId: message.id, action: 'compress' });
      try {
        const res = await apiFetch(`/api/sessions/${sessionId}/context/compress`, {
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
          appMessage.info('当前上下文暂不需要压缩');
          return;
        }

        await refreshVisibleSessionSnapshot(sessionId);
        if ((data as SessionContextCompressionPayload).updatedContext) {
          setSessionContext((data as SessionContextCompressionPayload).updatedContext ?? null);
        } else {
          await loadSessionContext({ silent: true, targetSessionId: sessionId });
        }
        await loadSessionHistory();
        appMessage.success('会话上下文已压缩');
      } catch (error) {
        console.error(error);
        appMessage.error(getErrorMessage(error, '压缩会话失败'));
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
        const res = await apiFetch(`/api/sessions/${sessionId}/fork`, {
          method: 'POST',
        });
        if (!res.ok) {
          throw new Error(await readApiError(res, '派生分支失败'));
        }
        const data = await res.json() as SessionPayload;
        applySessionPayload(data);
        await loadSessionHistory();
        await loadSessionContext({ silent: true, targetSessionId: data.sessionId });
        appMessage.success('已派生新会话');
      } catch (error) {
        console.error(error);
        appMessage.error(getErrorMessage(error, '派生分支失败'));
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
        const res = await apiFetch(`/api/sessions/${sessionId}/restore`, {
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
        appMessage.success('对话已还原');
      } catch (error) {
        console.error(error);
        appMessage.error(getErrorMessage(error, '还原对话失败'));
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
    fileTreeRef.current = [];
    fileTreeRevisionRef.current = 0;
    setTerminalCwd('');
    setTerminalBackend('subprocess');
    setManagedProcesses([]);
    setTerminalInfos([]);
    setActiveTerminalId(null);
    setSelectedFileContent('');
    setSelectedFilePath('');
    setBackendMode('demo');
    setCurrentSessionExecutionMode('local');
    setCurrentBaseWorkspace('');
    setCurrentWorktreeBranch(null);
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

  return (
    <>
      {(showWorkspacePicker || !sessionId) ? (
        <WorkspacePicker
          shouldRestoreSession={shouldRestoreSession}
          customWorkspace={customWorkspace}
          sessionError={sessionError}
          isSessionBooting={isSessionBooting}
          initializeGitRepository={initializeGitRepository}
          selectedWorkspace={selectedWorkspace}
          directoryTree={directoryTree}
          directoryExpanded={directoryExpanded}
          recentProjects={recentProjects}
          onDirectoryExpandedChange={handleDirectoryExpandedChange}
          onCustomWorkspaceChange={setCustomWorkspace}
          onInitializeGitRepositoryChange={setInitializeGitRepository}
          onSelectWorkspace={(path) => {
            setSelectedWorkspace(path);
            setCustomWorkspace(path);
          }}
          onCreateSession={createSession}
          onOpenRecentProject={handleOpenRecentProject}
          onRemoveRecentProject={handleRemoveRecentProject}
        />
      ) : (
    <div className="flex flex-col h-screen bg-background text-foreground font-sans w-full overflow-hidden text-[var(--app-body-font-size)] leading-[var(--app-body-line-height)]">
      <header
        className="relative flex items-center h-10 px-3 border-b bg-muted/30 flex-shrink-0 gap-2"
        {...(window.__TAURI__ ? { 'data-tauri-drag-region': '' } : {})}
      >
        <div className="flex items-center gap-2 select-none">
          <img src="/supercode-logo.svg" alt="SuperCode" className="h-5 w-5 rounded-[4px]" />
          <span className="text-sm font-bold tracking-tight">Super Code</span>
        </div>
        <div className="flex-1 min-w-0" />
        <div className="absolute left-1/2 -translate-x-1/2 flex max-w-[420px] items-center gap-2 text-[11px] text-muted-foreground">
          {currentSessionExecutionMode === 'worktree' ? (
            <span className="shrink-0 rounded border border-primary/20 bg-primary/10 px-1.5 py-0.5 text-primary">
              Worktree{currentWorktreeBranch ? ` · ${currentWorktreeBranch.replace('supercode/session-', '')}` : ''}
            </span>
          ) : null}
          <span className="truncate" title={selectedWorkspace}>
            {currentSessionExecutionMode === 'worktree'
              ? `${getPathLeaf(currentBaseWorkspace)} -> ${selectedWorkspace}`
              : selectedWorkspace}
          </span>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1.5 rounded-full px-2.5 text-xs"
              title="打开当前项目"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              打开
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            {PROJECT_OPEN_TARGETS.map((target) => (
              <DropdownMenuItem
                key={target.command}
                onClick={() => void handleOpenProject('editor', target.command, target.name)}
              >
                <span className="flex h-4 w-4 items-center justify-center">
                  {target.icon}
                </span>
                {target.name}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => void handleOpenProject('explorer')}>
              <FolderOpen className="h-4 w-4" />
              文件资源管理器
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-2 rounded-full px-3 text-xs"
          onClick={() => {
            void loadModelConfigs()
              .catch((error) => {
                console.error(error);
                appMessage.error(getErrorMessage(error, '加载设置失败'));
              })
              .finally(() => setIsModelConfigOpen(true));
          }}
          title="模型与供应商设置"
        >
          <Settings2 className="w-3.5 h-3.5" />
          设置
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 rounded-full"
          onClick={handleThemeToggle}
          title={isDarkMode ? '切换到浅色模式' : '切换到深色模式'}
        >
          {isDarkMode ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </Button>
        <Button variant="ghost" size="icon" className="h-7 w-7 rounded-full" onClick={() => setIsAboutOpen(true)} title="关于">
          <Info className="w-4 h-4" />
        </Button>
        <Button variant="ghost" size="icon" onClick={toggleRightPanel} className="h-7 w-7 ml-2" title={isRightPanelCollapsed ? '展开右侧面板' : '收起右侧面板'}>
          {isRightPanelCollapsed ? <PanelRightOpen className="w-4 h-4" /> : <PanelRightClose className="w-4 h-4" />}
        </Button>
        {window.__TAURI__ && (
          <div className="flex items-center ml-1">
            <Button variant="ghost" size="icon" className="h-7 w-7 rounded-md" title="最小化" onClick={() => window.__TAURI__?.core?.invoke('plugin:window|minimize').catch(() => {})}>
              <Minus className="w-3.5 h-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7 rounded-md" title="最大化" onClick={() => window.__TAURI__?.core?.invoke('plugin:window|toggle_maximize').catch(() => {})}>
              <Square className="w-3 h-3" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7 rounded-md hover:bg-destructive/80 hover:text-destructive-foreground" title="关闭" onClick={() => window.__TAURI__?.core?.invoke('plugin:window|close').catch(() => {})}>
              <X className="w-4 h-4" />
            </Button>
          </div>
        )}
      </header>
      <div className="flex flex-1 min-h-0">
      <Sidebar
        currentSessionId={sessionId}
        historyItems={sessionHistory}
        isHistoryLoading={isHistoryLoading}
        hasMoreHistory={sessionHistoryHasMore}
        isCollapsed={isSidebarCollapsed}
        selectedWorkspace={selectedWorkspace}
        selectedBaseWorkspace={currentBaseWorkspace || selectedWorkspace}
        backendMode={backendMode}
        startupError={startupError}
        width={sidebarWidth}
        isResizing={isSidebarResizing}
        isGitPanelOpen={isGitPanelOpen}
        onGitPanelToggle={() => setIsGitPanelOpen((prev) => !prev)}
        onNewSession={handleNewSession}
        onSelectHistory={(targetSessionId) => void restoreSession(targetSessionId)}
        onDeleteHistory={(targetSessionId) => void handleDeleteHistory(targetSessionId)}
        onLoadMoreHistory={() => void loadMoreSessionHistory()}
        onToggle={toggleSidebar}
        onSelectOtherProject={handleSelectOtherProject}
        activePlugin={activePlugin}
        plugins={availablePlugins}
        onActivePluginChange={(pluginId) => void handleActivePluginChange(pluginId)}
      />
      {!isSidebarCollapsed && (
        <ResizableHandle
          side="left"
          onResize={(delta) => setSidebarWidth((prev) => Math.min(Math.max(prev + delta, 220), 480))}
          onResizeStateChange={setIsSidebarResizing}
        />
      )}
      {activePlugin === 'kanban' ? (
        <div className="flex-1 flex flex-col min-w-0 bg-background overflow-hidden">
          <KanbanBoard
            workspace={selectedWorkspace}
            fileTree={fileTree}
            onSendCardToAi={handleSendKanbanCardToAi}
          />
        </div>
      ) : activePlugin === 'project-docs' ? (
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <ProjectDocsPage sessionId={sessionId} workspace={selectedWorkspace} fileTree={fileTree} />
        </div>
      ) : (
      <>
      <div style={isRightPanelCollapsed ? undefined : { width: chatPanelWidth }} className={isRightPanelCollapsed ? 'flex-1 min-w-0' : 'flex-shrink-0'}>
        <ChatPanel
        sessionId={sessionId}
        contextData={sessionContext}
        codeChanges={codeChanges}
        isContextLoading={isContextLoading}
        isContextOpen={isContextOpen}
        messages={messages}
        input={input}
        composerFocusRevision={composerFocusRevision}
        isLoading={isLoading}
        model={selectedModelId}
        defaultModelId={defaultModelId}
        reasoningEffort={selectedReasoningEffort}
        executionMode={currentSessionExecutionMode === 'worktree' ? 'worktree' : newSessionExecutionMode}
        modelOptions={modelOptions}
        fileTree={fileTree}
        onDefaultModelChange={handleDefaultModelChange}
        onModelChange={handleModelChange}
        onReasoningEffortChange={handleReasoningEffortChange}
        onExecutionModeChange={(mode) => {
          if (currentSessionExecutionMode !== 'worktree') {
            setNewSessionExecutionMode(mode);
          }
        }}
        onContextOpenChange={handleContextOpenChange}
        onInputChange={setInput}
        onEditMessage={(content) => {
          setInput(content);
          void sendMessage(content, elementAttachments.length > 0 ? elementAttachments : undefined);
        }}
        onSendMessage={(attachments) =>
          void sendMessage(
            input,
            elementAttachments.length > 0 ? elementAttachments : undefined,
            attachments,
          )
        }
        availableSkills={availableSkills}
        onStopMessage={stopMessage}
        onResolveDeleteConfirmation={resolveDeleteConfirmation}
        onResolveGitConfirmation={resolveGitConfirmation}
        onResolveConnectInput={resolveConnectInput}
        onResolvePlanQuestionsInput={resolvePlanQuestionsInput}
        onViewPlan={openPlanDraftPanel}
        onClosePlanSteps={handleClosePlanSteps}
        agentMode={selectedAgentMode}
        superAutopilotEnabled={selectedAgentMode === 'super' && isSuperAutopilotEnabled}
        onSuperAutopilotChange={setIsSuperAutopilotEnabled}
        onAgentModeChange={(mode) => {
          if (mode === 'conflux') {
            window.location.href = '/conflux';
            return;
          }
          setSelectedAgentMode(mode);
        }}
        elementAttachments={elementAttachments}
        onRemoveElementAttachment={(id) => setElementAttachments((prev) => prev.filter((e) => e.id !== id))}
        onCompletionAction={handleCompletionAction}
        activeCompletionAction={completionActionState}
        thinkingRendering={appSettings.thinkingRendering}
        finalAnswerRendering={appSettings.finalAnswerRendering}
        />
      </div>
      {!isRightPanelCollapsed && (
      <ResizableHandle
        side="left"
        onResize={(delta) => setChatPanelWidth((prev) => Math.min(Math.max(prev + delta, 560), 1120))}
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
          onLoadDirectory={loadFileTreeDirectory}
          onSaveFile={saveFile}
          onRefreshFileTree={() => refreshFileTreeSnapshot(sessionId, true)}
          sessionId={sessionId}
          isWebPreviewOpen={isWebPreviewOpen}
          onToggleWebPreview={() => setIsWebPreviewOpen((prev) => !prev)}
          webPreviewUrl={webPreviewUrl}
          onWebPreviewUrlChange={setWebPreviewUrl}
          isDarkMode={isDarkMode}
          onSelectPreviewElement={(html, selector, sourceUrl) => {
            setElementAttachments((prev) => [
              ...prev,
              { id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, selector, html, sourceUrl: sourceUrl ?? webPreviewUrl },
            ]);
          }}
          planData={planData}
          onPlanAnnotationsChange={setPlanAnnotations}
          onAddCodeContext={handleAddCodeContextToComposer}
          onPlanSave={async (markdown, annotations) => {
            if (!planData) return;
            const nextPlan = { ...planData, markdown };
            setPlanData(nextPlan);
            setPlanAnnotations(annotations);

            if (!sessionId) return;
            try {
              const annotationPayload = formatPlanAnnotations(annotations);
              const response = await apiFetch(`/api/sessions/${sessionId}/plan-draft`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  title: nextPlan.title,
                  markdown: nextPlan.markdown + annotationPayload,
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
              appMessage.success('计划草案已保存');
            } catch (error) {
              console.error('保存计划草案失败:', error);
              appMessage.error(getErrorMessage(error, '保存计划草案失败'));
            }
          }}
          onSubmitPlan={async (markdown, annotations) => {
            const annotationPayload = formatPlanAnnotations(annotations);
            const submittedMarkdown = markdown + annotationPayload;

            setPlanData(null);
            setPlanAnnotations([]);
            setSelectedAgentMode('coding');

            if (!sessionId) return;

            try {
              const res = await apiFetch(`/api/sessions/${sessionId}/plan/submit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  title: planData?.title,
                  markdown: submittedMarkdown,
                }),
              });
              const payload = await res.json();
              if (!res.ok) {
                throw new Error(String(payload.detail ?? '提交方案失败'));
              }

              const codingInput = String(payload.codingInput ?? '').trim();
              if (!codingInput) {
                throw new Error('提交方案失败：后端没有返回编码输入');
              }
              setMessages([]);
              setSessionContext((prev) =>
                prev
                  ? {
                      ...prev,
                      agentType: typeof payload.agentType === 'string' ? payload.agentType : 'coding',
                      phase: typeof payload.phase === 'string' ? payload.phase : prev.phase,
                      planState:
                        payload.planState && typeof payload.planState === 'object'
                          ? payload.planState
                          : prev.planState,
                      planSteps: [],
                      messageCount: 0,
                      toolCallCount: 0,
                      thoughtCount: 0,
                      recentMessages: [],
                      recentThoughts: [],
                      recentTools: [],
                    }
                  : prev,
              );
              await loadSessionHistory();

              appMessage.success('方案已提交，开始执行');
              await streamAssistantResponse({
                url: apiUrl('/api/chat/stream'),
                body: {
                  session_id: sessionId,
                  message: codingInput,
                  agent_mode: 'coding',
                },
                streamSessionId: sessionId,
                userVisibleMessage: codingInput,
                clearComposer: true,
              });
            } catch (error) {
              console.error('提交方案失败:', error);
              appMessage.error(getErrorMessage(error, '提交方案失败'));
            }
          }}
          onClosePlan={() => {
            setPlanData(null);
            setPlanAnnotations([]);
          }}
        />
        <TerminalPanel
          sessionId={sessionId}
          isOpen={isTerminalOpen}
          terminalInfos={terminalInfos}
          activeTerminalId={activeTerminalId}
          onActiveTerminalChange={setActiveTerminalId}
          onRuntimeStatusChange={(status) => {
            if (status.cwd) setTerminalCwd(status.cwd);
            if (status.backend) setTerminalBackend(status.backend);
          }}
          onToggle={handleTerminalToggle}
          onRefreshTerminals={() => void refreshTerminalState({ includeTerminals: true })}
          onCreateTerminal={createTerminal}
          onCloseTerminal={closeTerminal}
          onTerminateProcess={(terminalId) => void terminateManagedProcess(terminalId)}
        />
      </div>
      </>
      )}
      </>
      )}
      </div>
      <SettingsDialog
        open={isModelConfigOpen}
        onOpenChange={setIsModelConfigOpen}
        providers={visualModelProviders}
        configPath={modelConfigPath}
        mcpServers={mcpServers}
        mcpConfigPath={mcpConfigPath}
        settings={appSettings}
        currentWorkspace={selectedWorkspace}
        onSaveProviders={saveModelProviders}
        onDiscoverModels={discoverProviderModels}
        onTestModelConnection={testModelConnection}
        onSaveMcpServers={saveMcpServers}
        onTestMcpServer={testMcpServer}
        onTestEmbedding={testEmbeddingSettings}
        onSaveSettings={saveAppSettings}
        onSessionsChanged={() => loadSessionHistory()}
      />
      <Dialog open={isAboutOpen} onOpenChange={setIsAboutOpen}>
        <DialogContent className="sm:max-w-md overflow-hidden">
          <div
            className="absolute inset-0 pointer-events-none overflow-hidden"
            aria-hidden
            onContextMenu={(e) => e.preventDefault()}
          >
            {Array.from({ length: 6 }, (_, row) =>
              Array.from({ length: 4 }, (_, col) => (
                <span
                  key={`${row}-${col}`}
                  className="absolute text-foreground font-bold"
                  style={{
                    opacity: 0.03,
                    fontSize: '0.7rem',
                    letterSpacing: '0.2em',
                    whiteSpace: 'nowrap',
                    transform: 'rotate(-25deg)',
                    left: `${-10 + col * 28}%`,
                    top: `${-5 + row * 22}%`,
                    userSelect: 'none',
                    WebkitUserSelect: 'none',
                  }}
                >
                  zongxi
                </span>
              ))
            )}
          </div>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <motion.img
                src="/supercode-logo.svg"
                alt="SuperCode"
                className="h-5 w-5 rounded-[4px]"
                initial={{ scale: 0.3, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: 'spring', stiffness: 200, damping: 15 }}
              />
              <motion.span
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.4, duration: 0.4, ease: 'easeOut' }}
              >
                Super Code
              </motion.span>
            </DialogTitle>
            <DialogDescription asChild>
              <motion.p
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5, duration: 0.4, ease: 'easeOut' }}
              >
                一款 AI 驱动的智能编程助手，支持多种大模型，集代码编写、计划设计、部署发布于一体，让开发更高效。
              </motion.p>
            </DialogDescription>
          </DialogHeader>
          <motion.div
            className="text-sm text-muted-foreground space-y-3"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.6, duration: 0.4, ease: 'easeOut' }}
          >
            <p>作者：<span className="font-semibold text-foreground">zongxi</span></p>
            <p>开源地址：
              <a
                href="https://github.com/zongxi1115/SuperCode"
                onClick={(e) => { e.preventDefault(); openExternalUrl('https://github.com/zongxi1115/SuperCode'); }}
                className="text-primary hover:underline"
              >
                https://github.com/zongxi1115/SuperCode
              </a>
            </p>
          </motion.div>
          <motion.div
            className="relative h-1 mt-2 rounded-full overflow-hidden"
            style={{ background: 'rgba(0, 156, 255, 0.12)' }}
            initial={{ opacity: 0, scaleX: 0 }}
            animate={{ opacity: 1, scaleX: 1 }}
            transition={{ delay: 0.7, duration: 0.5, ease: [0.25, 0.1, 0.25, 1] }}
          >
            <motion.div
              className="absolute inset-y-0 w-2/5 rounded-full"
              style={{ background: 'linear-gradient(90deg, transparent, rgba(0, 156, 255, 0.65), rgba(120, 215, 255, 0.85), transparent)' }}
              animate={{ x: ['-100%', '350%'] }}
              transition={{ duration: 1.8, repeat: Infinity, ease: [0.4, 0, 0.2, 1], repeatDelay: 0.3 }}
            />
          </motion.div>
        </DialogContent>
      </Dialog>
    </div>
      )}
      <AnimatePresence>
        {isSessionBooting && (
          <SplashScreen key="splash" workspace={selectedWorkspace || customWorkspace} />
        )}
      </AnimatePresence>
    </>
  );
}
