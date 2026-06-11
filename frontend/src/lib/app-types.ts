export type ToolCallRecord = {
  id: string;
  name: string;
  arguments?: Record<string, unknown>;
  output?: unknown;
  errorMessage?: string;
  error_message?: string | null;
  success?: boolean | null;
  streamedInput?: string;
  approval?: {
    id: string;
    approved?: boolean;
    reason?: string;
  };
  inputRequest?: {
    id: string;
    kind: string;
    title: string;
    message: string;
    fields: { name: string; label: string; type: string; required: boolean; default?: string; placeholder?: string }[];
    questions?: {
      id: string;
      type: 'single_choice' | 'multi_choice' | 'short_text' | string;
      prompt: string;
      required: boolean;
      placeholder?: string;
      options?: {
        id: string;
        label: string;
        description?: string;
      }[];
    }[];
  };
  state: 'running' | 'completed' | 'error' | 'approval-requested' | 'input-requested' | 'output-available' | 'output-denied';
};

export type CodeChangeRecord = {
  id: string;
  action: 'added' | 'modified' | 'deleted' | string;
  path: string;
  absolutePath?: string | null;
  source?: string;
  toolCallId?: string | null;
  assistantId?: string | null;
  turnIndex?: number | null;
  stepIndex?: number | null;
  timestamp: number;
  linesAdded: number;
  linesDeleted: number;
  summary: string;
  diffPreview: string;
};

export type SubagentStepSnapshot = {
  id: string;
  name: string;
  status: 'running' | 'completed' | 'error' | 'paused' | string;
  thought?: string;
  error?: string;
};

export type SubagentSnapshot = {
  id?: string;
  kind?: string;
  title?: string;
  agentType?: string;
  status: 'running' | 'completed' | 'error' | 'paused' | string;
  task: string;
  focusPaths?: string[];
  currentThought?: string;
  steps: SubagentStepSnapshot[];
  stepCount: number;
  filesRead: string[];
  changedFiles: string[];
  commandsRun: string[];
  findings: string[];
  recommendedFiles: string[];
  toolNames?: string[];
  finalOutput?: string;
  error?: string;
};

export type ContentBlock =
  | { type: 'thinking'; text: string }
  | { type: 'tool_call'; toolCall: ToolCallRecord }
  | { type: 'text'; text: string }
  | { type: 'data'; dataType: string; data: unknown };

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  thoughts?: string;
  toolCalls?: ToolCallRecord[];
  parts?: ContentBlock[];
  thinkingTime?: number; // 思考时间（秒）
};

export type CompletionActionKey =
  | 'copy'
  | 'view-changes'
  | 'compress'
  | 'fork'
  | 'restore'
  | 'publish';

export type FileTreeNode = {
  path: string;
  name: string;
  type: 'folder' | 'file';
  loaded?: boolean;
  children?: FileTreeNode[];
};

export type WorkspaceOption = {
  value: string;
  label: string;
};

export type SessionExecutionMode = 'local' | 'worktree';

export type DirectoryNode = {
  path: string;
  name: string;
  children?: DirectoryNode[];
  loaded?: boolean;
};

export type PlanStep = {
  id: string;
  title: string;
  description: string;
  status: 'pending' | 'running' | 'blocked' | 'completed' | 'error';
};

export type TaskRecord = {
  id: string;
  title: string;
  description: string;
  status: 'pending' | 'running' | 'blocked' | 'completed';
  dependsOn: string[];
  acceptanceCriteria: string[];
  needsSplit: boolean;
  createdBy: 'plan_agent' | 'coding_agent' | 'system' | string;
  parentTaskId?: string | null;
};

export type TaskState = {
  strictMode: boolean;
  autoCreateEnabled: boolean;
  source: 'plan' | 'coding-seeded' | string;
  activeTaskId?: string | null;
  tasks: TaskRecord[];
};

export type SessionContextMessage = {
  role: 'user' | 'assistant' | string;
  content: string;
};

export type SessionContextTool = {
  id: string;
  name: string;
  state: 'running' | 'completed' | 'error' | string;
  success?: boolean | null;
};

export type SkillSummary = {
  id: string;
  name: string;
  description: string;
  scope: 'builtin' | 'workspace' | string;
  sourcePath?: string | null;
};

export type PluginSummary = {
  id: string;
  name: string;
  description: string;
  icon: string;
  navSlot: string;
  enabled: boolean;
  loadable?: boolean;
  loaded?: boolean;
};

export type SessionTokenUsage = {
  inputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  cachedInputTokens: number;
  totalTokens: number;
};

export type SessionContextPayload = {
  sessionId: string;
  workspace: string;
  mode: 'agent' | 'demo' | string;
  executionMode?: SessionExecutionMode;
  baseWorkspace?: string | null;
  worktreePath?: string | null;
  worktreeBranch?: string | null;
  model: string;
  reasoningEffort?: string | null;
  agentType?: string;
  phase?: string;
  deployState?: Record<string, unknown>;
  planState?: Record<string, unknown>;
  taskState?: TaskState;
  selectedFilePath?: string | null;
  openFiles: string[];
  messageCount: number;
  toolCallCount: number;
  thoughtCount: number;
  estimatedTokens: number;
  maxTokens: number;
  usage: SessionTokenUsage;
  cumulativeUsage: SessionTokenUsage;
  recentMessages: SessionContextMessage[];
  recentThoughts: string[];
  recentTools: SessionContextTool[];
  codeChangeCount: number;
  recentCodeChanges: CodeChangeRecord[];
  availableSkills: SkillSummary[];
  planSteps: PlanStep[];
};

export type SessionContextCompressionPayload = {
  sessionId: string;
  mode: 'preview' | 'apply';
  applied: boolean;
  summary: string;
  usageRatio: number;
  usageThreshold: number;
  sourceMessageCount: number;
  sourceToolCount: number;
  sourceThoughtCount: number;
  preservedMessageCount: number;
  preservedToolCount: number;
  preservedThoughtCount: number;
  originalEstimatedTokens: number;
  maxTokens: number;
  compressedEstimatedTokens: number;
  savedEstimatedTokens: number;
  usedFallback?: boolean;
  skippedReason?: string | null;
  updatedContext?: SessionContextPayload | null;
};

export type SessionPayload = {
  sessionId: string;
  model?: string;
  modelId?: string | null;
  reasoningEffort?: string | null;
  mode: 'agent' | 'demo';
  executionMode?: SessionExecutionMode;
  baseWorkspace?: string | null;
  worktreePath?: string | null;
  worktreeBranch?: string | null;
  agentType?: string;
  phase?: string;
  routeState?: Record<string, unknown>;
  deployState?: Record<string, unknown>;
  planState?: Record<string, unknown>;
  isGenerating?: boolean;
  startupError?: string | null;
  envFile?: string | null;
  previewUrl?: string;
  workspace: string;
  workspaceOptions: WorkspaceOption[];
  messages?: ChatMessage[];
  toolCalls?: ToolCallRecord[];
  thoughts?: string[];
  terminalOutput?: string;
  fileTree?: FileTreeNode[];
  fileTreeRevision?: number;
  selectedFilePath?: string | null;
  selectedFileContent?: string;
  availableSkills?: SkillSummary[];
  codeChanges?: CodeChangeRecord[];
  planSteps?: PlanStep[];
  taskState?: TaskState;
};

export type AgentMode = 'auto' | 'chat' | 'plan' | 'coding' | 'deploy';

export interface LastSession {
  workspace: string;
  timestamp: number;
}

export interface RecentProject {
  workspace: string;
  timestamp: number;
}

export type SessionHistoryItem = {
  sessionId: string;
  workspace: string;
  executionMode?: SessionExecutionMode;
  baseWorkspace?: string | null;
  worktreePath?: string | null;
  worktreeBranch?: string | null;
  mode: 'agent' | 'demo' | string;
  model: string;
  title: string;
  preview: string;
  messageCount: number;
  toolCallCount: number;
  createdAt: number;
  updatedAt: number;
};

export type TerminalSnapshotPayload = {
  sessionId: string;
  output: string;
  revision: number;
  isAlive: boolean;
  shell: string;
  backend?: string;
  cwd?: string | null;
  supportsInterrupt?: boolean;
  supportsRawInput?: boolean;
  supportsResize?: boolean;
  fileTree?: FileTreeNode[] | null;
  processes?: ManagedProcessPayload[] | null;
};

export type TerminalSocketClientMessage =
  | { type: 'input'; data: string }
  | { type: 'resize'; cols: number; rows: number }
  | { type: 'clear' }
  | { type: 'interrupt' };

export type TerminalSocketServerMessage =
  | { type: 'output'; data: string }
  | {
      type: 'status';
      cwd?: string | null;
      backend?: string;
      supportsInterrupt?: boolean;
      supportsResize?: boolean;
    }
  | { type: 'clear' }
  | { type: 'error'; message: string };

export type ManagedProcessInfo = {
  pid: number;
  parent_pid: number;
  name: string;
  command_line: string;
  is_root: boolean;
};

export type ManagedProcessPayload = {
  terminalId: string;
  command: string;
  rootPid: number;
  status: 'running' | 'orphaned' | 'terminated' | 'completed' | 'unknown' | string;
  returnCode?: number | null;
  startedAt: number;
  terminatedAt?: number | null;
  processCount: number;
  processes: ManagedProcessInfo[];
};

export type TerminalInfo = {
  terminalId: string;
  name: string;
  shell: string;
  backend: string;
  cwd: string | null;
  isAlive: boolean;
  isDefault: boolean;
  kind: 'interactive' | 'managed-process';
  command?: string | null;
  rootPid?: number | null;
  status?: string | null;
  startedAt?: number | null;
};

export type ModelOption = {
  id: string;
  name: string;
  model?: string;
  provider: string;
  envFile: string;
  label: string;
  sourceType?: 'env' | 'ui' | string;
  sourceLabel?: string;
  contextWindow?: number | null;
  readOnly?: boolean;
};

export type UIModelRecord = {
  id: string;
  contextWindow?: number | null;
};

export type UIModelProvider = {
  id?: string | null;
  name: string;
  baseUrl: string;
  apiKey: string;
  models: UIModelRecord[];
  provider?: string | null;
  apiMode?: 'chat_completions' | 'responses' | null;
};

export type ModelConfigPayload = {
  providers: UIModelProvider[];
  envConfigs: ModelOption[];
  configPath: string;
};

export type MCPTransport = 'stdio' | 'streamable_http';

export type MCPServerStatus = {
  state: 'unknown' | 'ok' | 'error' | string;
  message: string;
  toolCount?: number | null;
};

export type MCPServerConfig = {
  id?: string | null;
  name: string;
  enabled: boolean;
  transport: MCPTransport;
  command: string;
  args: string[];
  env: Record<string, string>;
  url: string;
  bearerToken: string;
  headers: Record<string, string>;
  status?: MCPServerStatus;
};

export type MCPServersPayload = {
  servers: MCPServerConfig[];
  configPath: string;
};

export type MCPToolSummary = {
  name: string;
  description: string;
  parametersSchema?: Record<string, unknown>;
};

export type MCPServerTestResult = {
  toolCount: number;
  tools: MCPToolSummary[];
};

export type MemoryItem = {
  id: string;
  content: string;
  scope: 'global' | 'workspace';
  enabled: boolean;
  createdAt: number;
  updatedAt: number;
  sourceSessionId?: string | null;
  sourcePreview?: string | null;
};

export type AppSettings = {
  autoApprove: boolean;
  thinkingRendering: "text" | "markdown";
  finalAnswerRendering: "markdown" | "html";
  bodyFontFamily: string;
  bodyFontSize: number;
  bodyLineHeight: number;
  embedding: {
    enabled: boolean;
    baseUrl: string;
    apiKey: string;
    model: string;
  };
  imageGeneration: {
    enabled: boolean;
    baseUrl: string;
    apiKey: string;
    model: string;
    size: string;
    quality: string;
  };
  memory: {
    enabled: boolean;
    autoLearn: boolean;
    global: MemoryItem[];
    workspaces: Record<string, MemoryItem[]>;
  };
};

export type GitCommitInfo = {
  hash: string;
  author: string;
  date: string;
  message: string;
};

export type GitTagInfo = {
  name: string;
  date: string;
  message: string;
};

export type GitLogPayload = {
  commits: GitCommitInfo[];
  isRepo: boolean;
  changedFiles?: string[];
  branch?: string;
  error?: string;
};

export type GitStatusPayload = {
  isRepo: boolean;
  changedFiles: string[];
  branch: string;
  error?: string;
};

export type GitTagsPayload = {
  tags: GitTagInfo[];
  isRepo: boolean;
  error?: string;
};
