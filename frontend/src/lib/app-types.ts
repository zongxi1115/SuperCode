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
  state: 'running' | 'completed' | 'error' | 'approval-requested' | 'output-available' | 'output-denied';
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
};

export type FileTreeNode = {
  path: string;
  name: string;
  type: 'folder' | 'file';
  children?: FileTreeNode[];
};

export type WorkspaceOption = {
  value: string;
  label: string;
};

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
  status: 'pending' | 'running' | 'completed' | 'error';
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

export type SessionContextPayload = {
  sessionId: string;
  workspace: string;
  mode: 'agent' | 'demo' | string;
  model: string;
  selectedFilePath?: string | null;
  openFiles: string[];
  messageCount: number;
  toolCallCount: number;
  thoughtCount: number;
  estimatedTokens: number;
  maxTokens: number;
  recentMessages: SessionContextMessage[];
  recentThoughts: string[];
  recentTools: SessionContextTool[];
  planSteps: PlanStep[];
};

export type SessionPayload = {
  sessionId: string;
  model?: string;
  modelId?: string | null;
  mode: 'agent' | 'demo';
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
  selectedFilePath?: string | null;
  selectedFileContent?: string;
  planSteps?: PlanStep[];
};

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
  fileTree?: FileTreeNode[] | null;
  processes?: ManagedProcessPayload[] | null;
};

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

export type ModelOption = {
  id: string;
  name: string;
  model?: string;
  provider: string;
  envFile: string;
  label: string;
  sourceType?: 'env' | 'ui' | string;
  sourceLabel?: string;
  readOnly?: boolean;
};

export type UIModelProvider = {
  id?: string | null;
  name: string;
  baseUrl: string;
  apiKey: string;
  models: string[];
  provider?: string | null;
};

export type ModelConfigPayload = {
  providers: UIModelProvider[];
  envConfigs: ModelOption[];
  configPath: string;
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
