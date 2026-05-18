import type { ChatMessage, ContentBlock, DirectoryNode, FileTreeNode, RecentProject, ToolCallRecord, WorkspaceOption } from '@/lib/app-types';

export const LAST_SESSION_KEY = 'supercode_last_session';
export const RECENT_PROJECTS_KEY = 'supercode_recent_projects';
export const MAX_RECENT_PROJECTS = 10;
export const FILE_TREE_POLL_INTERVAL = 5000;

export function getLastSession() {
  try {
    const raw = localStorage.getItem(LAST_SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function saveLastSession(workspace: string) {
  try {
    localStorage.setItem(LAST_SESSION_KEY, JSON.stringify({ workspace, timestamp: Date.now() }));
  } catch {
    // silent fail
  }
}

export function clearLastSession() {
  try {
    localStorage.removeItem(LAST_SESSION_KEY);
  } catch {
    // silent fail
  }
}

export function getRecentProjects(): RecentProject[] {
  try {
    const raw = localStorage.getItem(RECENT_PROJECTS_KEY);
    if (!raw) return [];
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

export function addRecentProject(workspace: string) {
  try {
    const projects = getRecentProjects().filter((p) => p.workspace !== workspace);
    projects.unshift({ workspace, timestamp: Date.now() });
    const trimmed = projects.slice(0, MAX_RECENT_PROJECTS);
    localStorage.setItem(RECENT_PROJECTS_KEY, JSON.stringify(trimmed));
  } catch {
    // silent fail
  }
}

export function removeRecentProject(workspace: string) {
  try {
    const projects = getRecentProjects().filter((p) => p.workspace !== workspace);
    localStorage.setItem(RECENT_PROJECTS_KEY, JSON.stringify(projects));
  } catch {
    // silent fail
  }
}

export function workspaceOptionsToDirectoryNodes(options: WorkspaceOption[]): DirectoryNode[] {
  return options.map((option) => ({
    path: option.value,
    name: option.label,
    children: [],
    loaded: false
  }));
}

export function updateDirectoryNodeTree(
  nodes: DirectoryNode[],
  targetPath: string,
  updater: (node: DirectoryNode) => DirectoryNode
): DirectoryNode[] {
  return nodes.map((node) => {
    if (node.path === targetPath) {
      return updater(node);
    }
    if (!node.children?.length) {
      return node;
    }
    return {
      ...node,
      children: updateDirectoryNodeTree(node.children, targetPath, updater)
    };
  });
}

export function findDirectoryNode(nodes: DirectoryNode[], targetPath: string): DirectoryNode | null {
  for (const node of nodes) {
    if (node.path === targetPath) {
      return node;
    }
    if (node.children?.length) {
      const childMatch = findDirectoryNode(node.children, targetPath);
      if (childMatch) {
        return childMatch;
      }
    }
  }
  return null;
}

export function getFileLanguage(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  const langMap: Record<string, string> = {
    tsx: 'tsx', jsx: 'jsx', ts: 'typescript', js: 'javascript',
    py: 'python', json: 'json', css: 'css', scss: 'scss',
    html: 'html', md: 'markdown', yaml: 'yaml', yml: 'yaml',
    toml: 'toml', rs: 'rust', go: 'go', sql: 'sql', sh: 'bash',
    vue: 'vue', svelte: 'svelte', astro: 'astro', xml: 'xml',
  };
  return langMap[ext] ?? 'text';
}

export function hydrateMessages(
  baseMessages: ChatMessage[],
  thoughts?: string[],
  toolCalls?: ToolCallRecord[]
): ChatMessage[] {
  if (!baseMessages.length) {
    return baseMessages;
  }

  const assistantMessages = baseMessages.filter((message) => message.role === 'assistant');
  const hasStructuredParts = assistantMessages.some((message) => Array.isArray(message.parts) && message.parts.length > 0);

  if (hasStructuredParts) {
    return baseMessages.map((message) => {
      if (message.role !== 'assistant' || !Array.isArray(message.parts)) {
        return message;
      }

      const content = message.parts
        .filter((part): part is Extract<ContentBlock, { type: 'text' }> => part.type === 'text')
        .map((part) => part.text)
        .join('');
      const mergedThoughts = message.parts
        .filter((part): part is Extract<ContentBlock, { type: 'thinking' }> => part.type === 'thinking')
        .map((part) => part.text.trim())
        .filter(Boolean)
        .join('\n\n');
      const mergedToolCalls = message.parts
        .filter((part): part is Extract<ContentBlock, { type: 'tool_call' }> => part.type === 'tool_call')
        .map((part) => part.toolCall);

      return {
        ...message,
        content,
        thoughts: mergedThoughts,
        toolCalls: mergedToolCalls,
      };
    });
  }

  if (assistantMessages.length !== 1) {
    return baseMessages;
  }

  const lastAssistantIndex = [...baseMessages]
    .map((message, index) => ({ message, index }))
    .reverse()
    .find(({ message }) => message.role === 'assistant')?.index;

  if (lastAssistantIndex === undefined) {
    return baseMessages;
  }

  return baseMessages.map((message, index) => {
    if (index !== lastAssistantIndex) {
      return message;
    }

    const mergedThoughts = message.thoughts ?? thoughts?.join('\n\n') ?? '';
    const mergedToolCalls = message.toolCalls ?? toolCalls ?? [];

    const parts: ContentBlock[] = [];
    if (mergedThoughts) {
      parts.push({ type: 'thinking', text: mergedThoughts });
    }
    for (const tc of mergedToolCalls) {
      parts.push({ type: 'tool_call', toolCall: tc });
    }
    if (message.content) {
      parts.push({ type: 'text', text: message.content });
    }

    return {
      ...message,
      thoughts: mergedThoughts,
      toolCalls: mergedToolCalls,
      parts
    };
  });
}

export function mapToolState(state: ToolCallRecord['state']) {
  if (state === 'completed') return 'output-available';
  if (state === 'error') return 'output-error';
  if (state === 'running') return 'input-available';
  if (state === 'input-requested') return 'input-requested';
  return 'input-streaming';
}

export function hasMessageThoughts(message: ChatMessage) {
  return Boolean(message.thoughts?.trim());
}
