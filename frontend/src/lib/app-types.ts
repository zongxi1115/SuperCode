export type ToolCallRecord = {
  id: string;
  name: string;
  arguments?: Record<string, unknown>;
  output?: unknown;
  errorMessage?: string;
  error_message?: string | null;
  success?: boolean;
  state: 'running' | 'completed' | 'error';
};

export type ContentBlock =
  | { type: 'thinking'; text: string }
  | { type: 'tool_call'; toolCall: ToolCallRecord }
  | { type: 'text'; text: string };

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
  mode: 'agent' | 'demo';
  startupError?: string | null;
  envFile?: string | null;
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
};

export type ModelOption = {
  id: string;
  name: string;
  provider: string;
  envFile: string;
  label: string;
};
