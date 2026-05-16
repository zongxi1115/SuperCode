import type { ChatMessage, ContentBlock, DirectoryNode, FileTreeNode, ToolCallRecord, WorkspaceOption } from '@/lib/app-types';

export const LAST_SESSION_KEY = 'supercode_last_session';
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
  return 'input-streaming';
}

export function hasMessageThoughts(message: ChatMessage) {
  return Boolean(message.thoughts?.trim());
}
