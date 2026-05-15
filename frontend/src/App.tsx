import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ConversationEmptyState } from '@/components/ai-elements/conversation';
import { Message, MessageContent, MessageResponse } from '@/components/ai-elements/message';
import { Plan, PlanHeader, PlanTitle } from '@/components/ai-elements/plan';
import { Tool, ToolHeader, ToolContent, ToolInput, ToolOutput } from '@/components/ai-elements/tool';
import { FileTree, FileTreeFile, FileTreeFolder } from '@/components/ai-elements/file-tree';
import { CodeBlock } from '@/components/ai-elements/code-block';
import { Textarea } from '@/components/ui/textarea';
import { ChevronRight, Plus, Terminal as TerminalIcon, FileCode, PanelLeftClose, PanelLeftOpen, FolderOpen } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
};

type ToolCallRecord = {
  id: string;
  name: string;
  arguments?: Record<string, unknown>;
  output?: unknown;
  errorMessage?: string;
  error_message?: string | null;
  success?: boolean;
  state: 'running' | 'completed' | 'error';
};

type PlanStep = {
  id: string;
  title: string;
  description: string;
  status: string;
};

type FileTreeNode = {
  path: string;
  name: string;
  type: 'folder' | 'file';
  children?: FileTreeNode[];
};

type SessionPayload = {
  sessionId: string;
  mode: 'agent' | 'demo';
  startupError?: string | null;
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

type WorkspaceOption = {
  value: string;
  label: string;
};

type DirectoryNode = {
  path: string;
  name: string;
  children?: DirectoryNode[];
  loaded?: boolean;
};

interface LastSession {
  workspace: string;
  timestamp: number;
}

const LAST_SESSION_KEY = 'supercode_last_session';

function getLastSession(): LastSession | null {
  try {
    const raw = localStorage.getItem(LAST_SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as LastSession;
    return parsed;
  } catch {
    return null;
  }
}

function saveLastSession(workspace: string) {
  try {
    localStorage.setItem(LAST_SESSION_KEY, JSON.stringify({ workspace, timestamp: Date.now() }));
  } catch {
    // silent fail
  }
}

function clearLastSession() {
  try {
    localStorage.removeItem(LAST_SESSION_KEY);
  } catch {
    // silent fail
  }
}

function renderFileTreeNodes(nodes: FileTreeNode[]): JSX.Element[] {
  return nodes.map((node) =>
    node.type === 'folder' ? (
      <FileTreeFolder key={node.path} path={node.path} name={node.name}>
        {renderFileTreeNodes(node.children ?? [])}
      </FileTreeFolder>
    ) : (
      <FileTreeFile key={node.path} path={node.path} name={node.name} />
    )
  );
}

function renderDirectoryNodes(nodes: DirectoryNode[]): JSX.Element[] {
  return nodes.map((node) => (
    <FileTreeFolder key={node.path} path={node.path} name={node.name}>
      {renderDirectoryNodes(node.children ?? [])}
    </FileTreeFolder>
  ));
}

function workspaceOptionsToDirectoryNodes(options: WorkspaceOption[]): DirectoryNode[] {
  return options.map((option) => ({
    path: option.value,
    name: option.label,
    children: [],
    loaded: false
  }));
}

function updateDirectoryNodeTree(
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

function findDirectoryNode(nodes: DirectoryNode[], targetPath: string): DirectoryNode | null {
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

function getFileLanguage(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  const langMap: Record<string, string> = {
    tsx: 'tsx', jsx: 'jsx', ts: 'typescript', js: 'javascript',
    py: 'python', json: 'json', css: 'css', scss: 'scss',
    html: 'html', md: 'markdown', yaml: 'yaml', yml: 'yaml',
    toml: 'toml', rs: 'rust', go: 'go', sql: 'sql', sh: 'bash',
  };
  return langMap[ext] ?? 'text';
}

const FILE_TREE_POLL_INTERVAL = 5000;

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [thoughts, setThoughts] = useState<string[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCallRecord[]>([]);
  const [planSteps, setPlanSteps] = useState<PlanStep[]>([]);
  const [fileTree, setFileTree] = useState<FileTreeNode[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [terminalOutput, setTerminalOutput] = useState('');
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
    .then(res => res.json())
    .then((data: { workspaces: WorkspaceOption[] }) => {
      const options = data.workspaces ?? [];
      setDirectoryTree(workspaceOptionsToDirectoryNodes(options));
      if (data.workspaces?.length && !initialWorkspace) {
        setSelectedWorkspace(data.workspaces[0].value);
      }
    })
    .catch(console.error);
  }, [initialWorkspace]);

  const createSessionWithWorkspace = useCallback(async (workspace: string) => {
    setIsSessionBooting(true);
    setSessionError(null);

    try {
      const res = await fetch('http://localhost:8000/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace })
      });
      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(errorText || '创建会话失败');
      }
      const data: SessionPayload = await res.json();
      setSessionId(data.sessionId);
      setBackendMode(data.mode);
      setStartupError(data.startupError ?? null);
      setSelectedWorkspace(data.workspace);
      if (data.messages) setMessages(data.messages);
      if (data.toolCalls) setToolCalls(data.toolCalls);
      if (data.thoughts) setThoughts(data.thoughts);
      if (data.planSteps) setPlanSteps(data.planSteps);
      if (data.fileTree) setFileTree(data.fileTree);
      if (data.terminalOutput) setTerminalOutput(data.terminalOutput);
      if (data.selectedFilePath) setSelectedFilePath(data.selectedFilePath);
      if (data.selectedFileContent) setSelectedFileContent(data.selectedFileContent);
      saveLastSession(data.workspace);
      setShowWorkspacePicker(false);
    } catch (error) {
      console.error(error);
      setSessionError(error instanceof Error ? error.message : '创建会话失败');
    } finally {
      setIsSessionBooting(false);
    }
  }, []);

  const hasRestoredRef = useRef(false);

  useEffect(() => {
    if (hasRestoredRef.current) return;
    if (!shouldRestoreSession || !initialWorkspace) return;

    hasRestoredRef.current = true;
    const id = setTimeout(() => {
      createSessionWithWorkspace(initialWorkspace);
    }, 0);
    return () => clearTimeout(id);
  }, [shouldRestoreSession, initialWorkspace, createSessionWithWorkspace]);

  useEffect(() => {
    if (!sessionId) return;

    const poll = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/file-tree`);
        if (res.ok) {
          const data = await res.json();
          if (data.fileTree) {
            setFileTree(data.fileTree);
          }
        }
      } catch {
        // silent fail for polling
      }
    };

    const intervalId = setInterval(poll, FILE_TREE_POLL_INTERVAL);
    return () => clearInterval(intervalId);
  }, [sessionId]);

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

  const sendMessage = async (msg: string) => {
    if (!msg.trim() || !sessionId || isLoading) return;
    
    setInput('');
    setIsLoading(true);
    
    setMessages(prev => [...prev, { id: Math.random().toString(), role: 'user', content: msg }]);

    try {
      const res = await fetch('http://localhost:8000/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: msg })
      });

      if (!res.body) return;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let incomingContent = '';
      let currentAssistantId = '';
      const processEvent = async (eventStr: string) => {
        if (!eventStr.startsWith('data: ')) return;

        try {
          const data = JSON.parse(eventStr.replace('data: ', ''));

          if (data.type === 'assistant_delta') {
            currentAssistantId = data.payload.id || currentAssistantId || Math.random().toString();
            incomingContent += data.payload.delta;
            setMessages(prev => {
              const msgs = [...prev];
              const last = msgs[msgs.length - 1];
              if (last && last.role === 'assistant' && last.id === currentAssistantId) {
                last.content = incomingContent;
                return msgs;
              }
              return [...msgs, { id: currentAssistantId, role: 'assistant', content: incomingContent }];
            });
          } else if (data.type === 'assistant_reset') {
            currentAssistantId = data.payload.id || currentAssistantId || Math.random().toString();
            incomingContent = '';
            setMessages(prev => prev.map((msg) =>
              msg.id === currentAssistantId && msg.role === 'assistant'
                ? { ...msg, content: '' }
                : msg
            ));
          } else if (data.type === 'thought') {
            setThoughts(prev => [...prev, data.payload.thought]);
          } else if (data.type === 'tool_call') {
            setToolCalls(prev => [...prev, { ...data.payload, state: 'running' }]);
            if (data.payload.name === 'read_file' && typeof data.payload.arguments?.filename === 'string') {
              void loadFile(data.payload.arguments.filename);
            }
          } else if (data.type === 'tool_result') {
            if (data.payload.name === 'execute' || data.payload.name === 'excecute') {
              setTerminalOutput(data.payload.output);
            }
            setToolCalls(prev => prev.map(tc =>
              tc.id === data.payload.id
                ? {
                    ...tc,
                    ...data.payload,
                    errorMessage: data.payload.error_message ?? tc.errorMessage,
                    state: data.payload.success ? 'completed' : 'error'
                  }
                : tc
            ));
          } else if (data.type === 'plan_steps') {
            setPlanSteps(data.payload.steps);
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
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const toggleSidebar = useCallback(() => {
    setIsSidebarCollapsed(prev => !prev);
  }, []);

  const handleSelectOtherProject = useCallback(() => {
    clearLastSession();
    setSessionId(null);
    setMessages([]);
    setThoughts([]);
    setToolCalls([]);
    setPlanSteps([]);
    setFileTree([]);
    setTerminalOutput('');
    setSelectedFileContent('');
    setSelectedFilePath('');
    setBackendMode('demo');
    setStartupError(null);
    setSessionError(null);
    setShowWorkspacePicker(true);
  }, []);

  const sidebarWidth = isSidebarCollapsed ? 48 : 256;

  if (showWorkspacePicker || !sessionId) {
    if (shouldRestoreSession) {
      return (
        <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-6">
          <div className="w-full max-w-xl rounded-2xl border bg-card p-6 shadow-sm space-y-5">
            <div className="space-y-2">
              <div className="text-sm font-medium text-muted-foreground">正在恢复上次的工作区</div>
              <h1 className="text-2xl font-semibold">加载中...</h1>
              <p className="text-sm text-muted-foreground">
                工作区：{customWorkspace}
              </p>
            </div>
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-6">
        <div className="w-full max-w-xl rounded-2xl border bg-card p-6 shadow-sm space-y-5">
          <div className="space-y-2">
            <div className="text-sm font-medium text-muted-foreground">初始化工作区</div>
            <h1 className="text-2xl font-semibold">先打开一个工作区</h1>
            <p className="text-sm text-muted-foreground">
              选定后，文件树、代码预览和后端 agent 都会围绕这个目录工作。
            </p>
          </div>

          <div className="space-y-3">
            <label className="text-sm font-medium">树形选择目录</label>
            <ScrollArea className="h-72 rounded-lg border">
              <div className="p-3">
                <FileTree
                  expanded={directoryExpanded}
                  onExpandedChange={handleDirectoryExpandedChange}
                  selectedPath={selectedWorkspace}
                  onSelect={(path) => {
                    setSelectedWorkspace(path);
                    setCustomWorkspace('');
                  }}
                >
                  {renderDirectoryNodes(directoryTree)}
                </FileTree>
              </div>
            </ScrollArea>
            <p className="text-xs text-muted-foreground">
              点击目录名选中工作区，点左侧箭头继续展开下一层。
            </p>
          </div>

          <div className="space-y-3">
            <label className="text-sm font-medium">或直接输入系统绝对路径</label>
            <Input
              value={customWorkspace}
              onChange={(e) => setCustomWorkspace(e.target.value)}
              placeholder="例如 D:\\vibe_projs\\SuperCode 或 C:\\Users\\32980\\Desktop"
            />
            <p className="text-xs text-muted-foreground">
              留空时使用上面的选项；输入系统绝对路径时会覆盖下拉选择。
            </p>
          </div>

          {sessionError && (
            <div className="rounded border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {sessionError}
            </div>
          )}

          <Button className="w-full" onClick={createSession} disabled={isSessionBooting}>
            {isSessionBooting ? '正在打开工作区...' : '打开工作区'}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-background text-foreground text-sm font-sans w-full overflow-hidden">
      {/* 1. Left Sidebar - Collapsible with motion */}
      <motion.div
        animate={{ width: sidebarWidth }}
        transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
        className="border-r bg-muted/20 flex flex-col flex-shrink-0 overflow-hidden"
      >
        {/* Toggle button - always visible */}
        <div className="flex items-center justify-between p-2 border-b">
          <AnimatePresence mode="wait">
            {!isSidebarCollapsed && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="flex-1 space-y-2"
              >
                <Button variant="default" className="w-full justify-start gap-2" onClick={() => window.location.reload()}>
                  <Plus className="w-4 h-4" /> 新建任务
                </Button>
                <Button variant="outline" className="w-full justify-start gap-2" onClick={handleSelectOtherProject}>
                  <FolderOpen className="w-4 h-4" /> 选择其他项目
                </Button>
              </motion.div>
            )}
          </AnimatePresence>
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleSidebar}
            className="shrink-0 h-8 w-8"
          >
            {isSidebarCollapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
          </Button>
        </div>

        <AnimatePresence mode="wait">
          {!isSidebarCollapsed && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex-1 flex flex-col min-h-0"
            >
              <div className="px-4 pt-3">
                <div className="text-xs text-muted-foreground">
                  当前模式：{backendMode === 'agent' ? '真实 Agent' : 'Demo 回退'}
                </div>
                <div className="mt-1 text-xs text-muted-foreground truncate" title={selectedWorkspace}>
                  工作区：{selectedWorkspace}
                </div>
                {startupError && (
                  <div className="mt-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-900">
                    启动提示：{startupError}
                  </div>
                )}
              </div>
              <ScrollArea className="flex-1">
                <div className="p-4">
                  <h3 className="text-xs font-semibold text-muted-foreground mb-4">项目结构</h3>
                  {fileTree.length > 0 && (
                    <div>
                      <FileTree selectedPath={selectedFilePath} onSelect={loadFile}>
                        {renderFileTreeNodes(fileTree)}
                      </FileTree>
                    </div>
                  )}
                  {!fileTree.length && (
                    <div className="text-muted-foreground text-center py-4">暂无文件结构</div>
                  )}
                </div>
              </ScrollArea>
            </motion.div>
          )}
        </AnimatePresence>

        {isSidebarCollapsed && (
          <div className="flex-1 flex flex-col items-center pt-3 gap-2">
            <div className="w-6 h-6 rounded bg-muted/80 flex items-center justify-center" title={selectedWorkspace}>
              <FileCode className="w-3.5 h-3.5 text-muted-foreground" />
            </div>
          </div>
        )}
      </motion.div>

      {/* 2. Chat Panel */}
      <div className="flex-1 flex flex-col min-w-0 border-r relative">
        <div className="flex-1 overflow-auto p-4 space-y-4">
           {messages.length === 0 ? (
             <ConversationEmptyState title="智能代码助手" description="描述您的需求，我将为您生成代码并执行" />
           ) : (
              messages.map((msg, idx) => (
                <Message key={msg.id || idx} from={msg.role}>
                  <MessageContent>
                    <MessageResponse>{msg.content}</MessageResponse>
                  </MessageContent>
                </Message>
             ))
           )}
        </div>
        
        <div className="p-4 bg-background">
          <div className="flex bg-muted/30 border rounded-lg p-2 gap-2 shadow-sm focus-within:ring-1 focus-within:ring-ring">
             <Textarea 
               value={input}
               onChange={(e) => setInput(e.target.value)}
               onKeyDown={handleKeyDown}
               placeholder="告诉我想实现什么，或粘贴代码、截图、提问..."
               className="min-h-[44px] resize-none border-0 shadow-none focus-visible:ring-0 bg-transparent flex-1 py-1.5"
               rows={1}
             />
             <Button size="icon" onClick={() => sendMessage(input)} disabled={isLoading}>
                <ChevronRight className="w-4 h-4" />
             </Button>
          </div>
        </div>
      </div>

      {/* 3. Editor & Terminal Column */}
      <div className="w-1/3 flex flex-col min-w-0 border-r">
         <Tabs defaultValue="editor" className="flex-1 flex flex-col h-full w-full">
           <div className="border-b px-2 flex items-center shrink-0">
             <TabsList className="h-10 bg-transparent">
               <TabsTrigger value="editor" className="data-[state=active]:bg-muted/50 rounded-none border-b-2 border-transparent data-[state=active]:border-primary shadow-none">代码预览</TabsTrigger>
               <TabsTrigger value="terminal" className="data-[state=active]:bg-muted/50 rounded-none border-b-2 border-transparent data-[state=active]:border-primary shadow-none">终端 & 日志</TabsTrigger>
             </TabsList>
           </div>
           
           <TabsContent value="editor" className="flex-1 p-0 m-0 overflow-hidden relative">
             {selectedFilePath && selectedFileContent ? (
               <div className="absolute inset-0 p-4 overflow-auto">
                 <div className="flex items-center gap-2 mb-2 text-muted-foreground font-mono text-xs">
                   <FileCode className="w-4 h-4" /> {selectedFilePath}
                 </div>
                 <CodeBlock language={getFileLanguage(selectedFilePath) as 'tsx'} className="w-full text-sm">
                   {selectedFileContent}
                 </CodeBlock>
               </div>
             ) : (
               <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
                 <div className="text-center space-y-2">
                   <FileCode className="w-10 h-10 mx-auto opacity-30" />
                   <p className="text-xs">选择左侧文件以预览代码</p>
                 </div>
               </div>
             )}
           </TabsContent>
           
           <TabsContent value="terminal" className="flex-1 p-0 m-0 overflow-auto bg-black text-white p-4 font-mono text-xs">
              <div className="flex items-center gap-2 mb-4 text-gray-400">
                 <TerminalIcon className="w-4 h-4" /> 终端输出
              </div>
              <pre className="whitespace-pre-wrap">{terminalOutput || '> 等待命令执行...'}</pre>
           </TabsContent>
         </Tabs>
      </div>

      {/* 4. Right Sidebar (Plan & Tools) */}
      <div className="w-80 bg-muted/10 flex flex-col flex-shrink-0">
         <ScrollArea className="flex-1 p-4">
            <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
               🎯 实现计划
            </h3>
            <Plan className="mb-8">
               <PlanHeader><PlanTitle>执行步骤</PlanTitle></PlanHeader>
               {planSteps.map(step => (
                 <div key={step.id} className="p-4 border-t first:border-0 flex flex-col gap-2">
                   <div className="flex items-center gap-2">
                     <div className="w-6 h-6 rounded-full border flex items-center justify-center text-xs font-mono shrink-0 font-bold bg-background">
                       {step.id}
                     </div>
                     <span className="font-semibold text-sm">{step.title}</span>
                     <span className="ml-auto text-xs text-muted-foreground">{step.status}</span>
                   </div>
                   <div className="text-xs text-muted-foreground pl-8">{step.description}</div>
                 </div>
               ))}
               {!planSteps.length && <div className="text-muted-foreground text-xs p-4">等待生成计划...</div>}
            </Plan>

            <h3 className="font-semibold text-sm mb-4 mt-8 flex items-center gap-2">
               🧠 思维链与检索链
            </h3>
            <div className="space-y-4">
              {thoughts.map((t, idx) => (
                <div key={idx} className="bg-muted px-3 py-2 rounded-md text-xs text-muted-foreground border">
                   {t}
                </div>
              ))}
            </div>

            <h3 className="font-semibold text-sm mb-4 mt-8 flex items-center gap-2">
               🛠️ 工具调用链
            </h3>
            <div className="space-y-3">
               {toolCalls.map(tc => {
                 const errorText = tc.state === 'error' ? String(tc.errorMessage || tc.error_message || tc.output) : undefined;
                 const output = tc.state === 'completed' ? tc.output : undefined;
                 const mappedState = tc.state === 'completed' ? 'output-available' : 
                                    tc.state === 'error' ? 'output-error' : 
                                    tc.state === 'running' ? 'input-available' : 'input-streaming';
                 return (
                   <Tool key={tc.id} className="text-xs bg-background rounded border">
                     <ToolHeader type="dynamic-tool" toolName={tc.name} state={mappedState} />
                     <ToolContent>
                       <ToolInput input={tc.arguments || {}} />
                       {(output || errorText) && (
                         <ToolOutput output={output} errorText={errorText} />
                       )}
                     </ToolContent>
                   </Tool>
                 );
               })}
               {!toolCalls.length && <div className="text-muted-foreground text-xs">暂无调用记录...</div>}
            </div>
         </ScrollArea>
      </div>
    </div>
  );
}
