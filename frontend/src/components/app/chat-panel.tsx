import { ContextViewer } from '@/components/app/context-viewer';
import { Conversation, ConversationContent, ConversationEmptyState } from '@/components/ai-elements/conversation';
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep,
} from '@/components/ai-elements/chain-of-thought';
import { CodeBlock, CodeBlockDiff } from '@/components/ai-elements/code-block';
import { Terminal } from '@/components/ai-elements/terminal';
import { Message, MessageContent, MessageResponse } from '@/components/ai-elements/message';
import { Persona, type PersonaState } from '@/components/ai-elements/persona';
import {
  Queue,
  QueueItem,
  QueueItemDescription,
  QueueItemTitle,
} from '@/components/ai-elements/queue';
import { Shimmer } from '@/components/ai-elements/shimmer';
import {
  Task,
  TaskContent,
  TaskItem,
  TaskItemFile,
  TaskTrigger,
} from '@/components/ai-elements/task';
import {
  Attachments,
  Attachment,
  AttachmentPreview,
  AttachmentInfo,
  AttachmentRemove,
  type AttachmentData,
} from '@/components/ai-elements/attachments';
import {
  ModelSelector,
  ModelSelectorTrigger,
  ModelSelectorContent,
  ModelSelectorInput,
  ModelSelectorList,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorItem,
  ModelSelectorName,
  ModelSelectorLogo,
} from '@/components/ai-elements/model-selector';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { getFileLanguage } from '@/lib/app-utils';
import type { ChatMessage, ContentBlock, ModelOption, PlanStep, SessionContextPayload, ToolCallRecord } from '@/lib/app-types';
import {
  ChevronDown,
  ChevronRight,
  FileCodeIcon,
  FileSearchIcon,
  FolderOpenIcon,
  ListChecks,
  PencilIcon,
  PlusIcon,
  PaperclipIcon,
  Square,
  TerminalIcon,
  Trash2Icon,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import type React from 'react';
import { memo, useMemo, useRef, useState, useCallback } from 'react';

type ChatPanelProps = {
  contextData: SessionContextPayload | null;
  messages: ChatMessage[];
  isContextLoading: boolean;
  isContextOpen: boolean;
  input: string;
  isLoading: boolean;
  model: string | null;
  modelOptions: ModelOption[];
  onContextOpenChange: (open: boolean) => void;
  onInputChange: (value: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSendMessage: () => void;
  onStopMessage: () => void;
  onModelChange: (envFile: string) => void;
};

const TOOL_ICONS: Record<string, React.ReactNode> = {
  list_file: <FolderOpenIcon className="size-4" />,
  read_file: <FileSearchIcon className="size-4" />,
  write_file: <PlusIcon className="size-4" />,
  replace_file: <PencilIcon className="size-4" />,
  delete_file: <Trash2Icon className="size-4" />,
  execute: <TerminalIcon className="size-4" />,
  excecute: <TerminalIcon className="size-4" />,
  terminal_input: <TerminalIcon className="size-4" />,
  terminal_wait: <TerminalIcon className="size-4" />,
};

function getToolIcon(name: string) {
  return TOOL_ICONS[name] ?? <FileCodeIcon className="size-4" />;
}

function normalizeThoughtText(value?: string | null) {
  const trimmed = value?.trim() ?? '';
  if (!trimmed || trimmed === '模型未提供思路。') {
    return '';
  }
  return trimmed;
}

function ToolBody({ toolCall }: { toolCall: ToolCallRecord }) {
  const args = toolCall.arguments || {};
  const output = toolCall.state === 'completed' ? toolCall.output : undefined;
  const errorText = toolCall.state === 'error'
    ? String(toolCall.errorMessage || toolCall.error_message || toolCall.output)
    : undefined;

  const filename = (args.filename || args.path || args.file_path) as string | undefined;
  const content = args.content as string | undefined;
  const oldContent = args.old_content || args.old_code as string | undefined;
  const newContent = args.new_content || args.new_code as string | undefined;
  const command = args.command || args.cmd || args.content as string | undefined;
  const terminalPayload = output && typeof output === 'object' && !Array.isArray(output)
    ? output as Record<string, unknown>
    : undefined;
  const terminalStatus = typeof terminalPayload?.status === 'string'
    ? terminalPayload.status
    : undefined;
  const terminalFullOutput = typeof terminalPayload?.full_output === 'string'
    ? terminalPayload.full_output
    : typeof output === 'string'
      ? output
      : undefined;

  if (toolCall.name === 'write_file' && content) {
    return (
      <div className="space-y-2">
        {filename && (
          <TaskItemFile>
            <FileCodeIcon className="size-3" />
            {filename}
          </TaskItemFile>
        )}
        <CodeBlock
          code={content}
          language={filename ? getFileLanguage(filename) as never : 'text'}
        />
      </div>
    );
  }

  if (toolCall.name === 'replace_file' && oldContent && newContent) {
    const diffLines = [
      ...oldContent.split('\n').map((l: string) => `- ${l}`),
      '---',
      ...newContent.split('\n').map((l: string) => `+ ${l}`),
    ].join('\n');

    return (
      <div className="space-y-2">
        {filename && (
          <TaskItemFile>
            <FileCodeIcon className="size-3" />
            {filename}
          </TaskItemFile>
        )}
        <CodeBlockDiff diff={diffLines} />
      </div>
    );
  }

  if (toolCall.name === 'read_file' && typeof output === 'string') {
    return (
      <div className="space-y-2">
        {filename && (
          <TaskItemFile>
            <FileCodeIcon className="size-3" />
            {filename}
          </TaskItemFile>
        )}
        <CodeBlock
          code={output}
          language={filename ? getFileLanguage(filename) as never : 'text'}
        />
      </div>
    );
  }

  if (
    toolCall.name === 'open_browser' &&
    output &&
    typeof output === 'object' &&
    !Array.isArray(output)
  ) {
    const browserPayload = output as Record<string, unknown>;
    const targetValue = typeof browserPayload.target === 'string' ? browserPayload.target : undefined;
    const resolvedUrl = typeof browserPayload.resolved_url === 'string' ? browserPayload.resolved_url : undefined;
    const sourceType = typeof browserPayload.source_type === 'string' ? browserPayload.source_type : undefined;
    const absolutePath = typeof browserPayload.absolute_path === 'string' ? browserPayload.absolute_path : undefined;

    return (
      <div className="space-y-2 rounded-md bg-muted/50 p-3 text-xs">
        <p className="font-medium text-foreground">已在右侧浏览器预览中打开</p>
        {targetValue ? <p className="text-muted-foreground">目标：{targetValue}</p> : null}
        {sourceType ? (
          <p className="text-muted-foreground">
            类型：{sourceType === 'network_url' ? '网络地址' : sourceType === 'local_file' ? '本地文件' : sourceType}
          </p>
        ) : null}
        {absolutePath ? <p className="text-muted-foreground">绝对路径：{absolutePath}</p> : null}
        {resolvedUrl ? (
          <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-background/80 p-2 font-mono">
            {resolvedUrl}
          </pre>
        ) : null}
      </div>
    );
  }

  if (toolCall.name === 'list_file' && typeof output === 'string') {
    return (
      <div className="space-y-2">
        {filename && (
          <TaskItemFile>
            <FolderOpenIcon className="size-3" />
            {filename}
          </TaskItemFile>
        )}
        <pre className="overflow-x-auto rounded-md bg-muted/50 p-2 text-xs font-mono whitespace-pre-wrap">
          {output}
        </pre>
      </div>
    );
  }

  if (
    (
      toolCall.name === 'execute' ||
      toolCall.name === 'excecute' ||
      toolCall.name === 'terminal_input' ||
      toolCall.name === 'terminal_wait'
    ) &&
    (command || content || terminalStatus || terminalFullOutput)
  ) {
    const cmdText = toolCall.name === 'terminal_input'
      ? content
      : toolCall.name === 'terminal_wait'
        ? `wait ${String(args.timeout ?? '')}s`
        : command ?? content;
    const termOutput = [
      cmdText && `$ ${cmdText}`,
      terminalFullOutput,
      errorText,
    ].filter(Boolean).join('\n');
    const isRunning = toolCall.state === 'running';

    return (
      <Terminal
        output={termOutput}
        isStreaming={isRunning}
      />
    );
  }

  return (
    <div className="space-y-2">
      {Object.keys(args).length > 0 && (
        <div className="rounded-md bg-muted/50 p-2 text-xs">
          <p className="font-medium text-muted-foreground mb-1">参数</p>
          <pre className="overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(args, null, 2)}
          </pre>
        </div>
      )}
      {output && (
        <div className="rounded-md bg-muted/50 p-2 text-xs">
          <p className="font-medium text-muted-foreground mb-1">结果</p>
          <pre className="overflow-x-auto whitespace-pre-wrap">
            {typeof output === 'string' ? output : JSON.stringify(output, null, 2)}
          </pre>
        </div>
      )}
      {errorText && (
        <div className="rounded-md bg-destructive/10 p-2 text-xs text-destructive">
          <p className="font-medium mb-1">错误</p>
          <pre className="overflow-x-auto whitespace-pre-wrap">{errorText}</pre>
        </div>
      )}
    </div>
  );
}

function PlanToggle({ planSteps, isStreaming }: { planSteps: PlanStep[]; isStreaming: boolean }) {
  const [isOpen, setIsOpen] = useState(false);

  if (planSteps.length === 0) return null;

  const completedCount = planSteps.filter((s) => s.status === 'completed').length;

  return (
    <div className="px-3">
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className="flex items-center gap-2 w-full rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
      >
        <ListChecks className="size-3.5 shrink-0" />
        <span className="flex-1 text-left">计划</span>
        <span className="text-[10px] tabular-nums">{completedCount}/{planSteps.length}</span>
        <motion.div
          animate={{ rotate: isOpen ? 180 : 0 }}
          transition={{ type: 'spring', stiffness: 300, damping: 25 }}
        >
          <ChevronDown className="size-3" />
        </motion.div>
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 260, damping: 26 }}
            className="overflow-hidden"
          >
            <div className="px-1 pb-2 pt-1">
              <Queue isStreaming={isStreaming}>
                {planSteps.map((step) => (
                  <QueueItem key={step.id} status={step.status}>
                    <QueueItemTitle>{step.title}</QueueItemTitle>
                    <QueueItemDescription>{step.description}</QueueItemDescription>
                  </QueueItem>
                ))}
              </Queue>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

const personaLabels: Record<PersonaState, string> = {
  asleep: 'Asleep',
  idle: 'Idle',
  listening: 'Listening',
  thinking: 'Thinking',
  speaking: 'Speaking',
};

const PERSONA_LAYOUT_ID = 'chat-persona-shell';

const PersonaShell = memo(function PersonaShell({ state }: { state: PersonaState }) {
  return (
    <motion.div
      layoutId={PERSONA_LAYOUT_ID}
      transition={{ type: 'spring', stiffness: 320, damping: 30 }}
      aria-label={`AI status: ${personaLabels[state]}`}
      className="pointer-events-none inline-flex items-center justify-start"
    >
      <Persona variant="glint" state={state} className="size-12" />
    </motion.div>
  );
});

const PersonaRail = memo(function PersonaRail({ state }: { state: PersonaState }) {
  return (
    <motion.div layout className="flex justify-start py-2">
      <PersonaShell state={state} />
    </motion.div>
  );
});

const EmptyStateWithPersona = memo(function EmptyStateWithPersona({
  state,
}: {
  state: PersonaState;
}) {
  return (
    <ConversationEmptyState className="min-h-[38vh]">
      <motion.div layout className="flex items-center gap-4 text-left">
        <PersonaShell state={state} />
        <div className="space-y-1">
          <h3 className="font-medium text-sm">智能代码助手</h3>
          <p className="text-muted-foreground text-sm">描述您的需求，我将为您生成代码并执行</p>
        </div>
      </motion.div>
    </ConversationEmptyState>
  );
});

const MessageList = memo(function MessageList({
  isLoading,
  messages,
}: {
  isLoading: boolean;
  messages: ChatMessage[];
}) {
  const renderToolCall = (tc: ToolCallRecord, isLastTool: boolean) => {
    const statusLabel =
      tc.state === 'completed' ? '已完成' :
      tc.state === 'error' ? '出错' : '执行中';

    return (
      <Task key={tc.id} defaultOpen={isLastTool}>
        <TaskTrigger
          title={`${tc.name} · ${statusLabel}`}
          icon={getToolIcon(tc.name)}
        />
        <TaskContent>
          <TaskItem>
            <ToolBody toolCall={tc} />
          </TaskItem>
        </TaskContent>
      </Task>
    );
  };

  const renderLegacyAssistant = (msg: ChatMessage, isLast: boolean) => {
    if (isLast) {
      const thoughtText = normalizeThoughtText(msg.thoughts);
      const hasThoughts = Boolean(thoughtText);
      const hasToolCalls = (msg.toolCalls?.length ?? 0) > 0;

      return (
        <>
          {hasThoughts ? (
            <ChainOfThought defaultOpen={isLoading}>
              <ChainOfThoughtHeader>
                <span>思考过程</span>
              </ChainOfThoughtHeader>
                <ChainOfThoughtContent>
                  <ChainOfThoughtStep
                    label={thoughtText}
                    status={isLoading ? 'active' : 'complete'}
                  />
                {hasToolCalls ? (
                  <div className="space-y-2">
                    {msg.toolCalls?.map((tc, tci) => renderToolCall(tc, tci === (msg.toolCalls?.length ?? 0) - 1))}
                  </div>
                ) : null}
              </ChainOfThoughtContent>
            </ChainOfThought>
          ) : hasToolCalls ? (
            <div className="space-y-2">
              {msg.toolCalls?.map((tc, tci) => renderToolCall(tc, tci === (msg.toolCalls?.length ?? 0) - 1))}
            </div>
          ) : null}
        </>
      );
    }

    return (msg.toolCalls?.length ?? 0) > 0 ? (
      <div className="space-y-2">
        {msg.toolCalls?.map((tc, tci) => renderToolCall(tc, tci === (msg.toolCalls?.length ?? 0) - 1))}
      </div>
    ) : null;
  };

  const renderPartsAssistant = (msg: ChatMessage, isLast: boolean) => {
    const parts = msg.parts ?? [];
    const groups: ({ type: 'cot'; blocks: ContentBlock[]; hasThinking: boolean } | { type: 'text'; block: ContentBlock } | { type: 'tools'; blocks: ContentBlock[] })[] = [];
    let cotBuffer: ContentBlock[] = [];

    const flushCot = () => {
      if (cotBuffer.length === 0) return;
      const hasThinking = cotBuffer.some((b) => b.type === 'thinking' && b.text.trim());
      if (hasThinking) {
        groups.push({ type: 'cot', blocks: cotBuffer, hasThinking: true });
      } else {
        groups.push({ type: 'tools', blocks: cotBuffer });
      }
      cotBuffer = [];
    };

    for (const part of parts) {
      if (part.type === 'thinking' || part.type === 'tool_call') {
        cotBuffer.push(part);
      } else if (part.type === 'text') {
        flushCot();
        groups.push({ type: 'text', block: part });
      }
    }
    flushCot();

    return groups.map((group, gi) => {
      if (group.type === 'text') {
        return group.block.text ? (
          <MessageResponse key={`text-${gi}`}>{group.block.text}</MessageResponse>
        ) : null;
      }

      if (group.type === 'tools') {
        const lastToolIdx = [...group.blocks].map((b, i) => b.type === 'tool_call' ? i : -1).filter(i => i >= 0).pop();
        return (
          <div key={`tools-${gi}`} className="space-y-2">
            {group.blocks.map((block, bi) => {
              if (block.type === 'tool_call') {
                return renderToolCall(block.toolCall, bi === lastToolIdx);
              }
              return null;
            })}
          </div>
        );
      }

      const hasContent = group.blocks.length > 0;
      const isActive = isLast && isLoading;
      return (
        <ChainOfThought key={`cot-${gi}`} defaultOpen={isActive || hasContent}>
          <ChainOfThoughtHeader>
            {isActive && !hasContent ? (
              <Shimmer duration={1}>正在思考...</Shimmer>
            ) : (
              <span>思考过程</span>
            )}
          </ChainOfThoughtHeader>
          <ChainOfThoughtContent>
            {(() => {
              const lastToolIdx = [...group.blocks].map((b, i) => b.type === 'tool_call' ? i : -1).filter(i => i >= 0).pop();
              return group.blocks.map((block, bi) => {
                if (block.type === 'thinking') {
                  return block.text.trim() ? (
                    <ChainOfThoughtStep
                      key={`thinking-${gi}-${bi}`}
                      label={block.text}
                      status={isActive ? 'active' : 'complete'}
                    />
                  ) : null;
                }
                if (block.type === 'tool_call') {
                  return <div key={`tool-${gi}-${bi}`}>{renderToolCall(block.toolCall, bi === lastToolIdx)}</div>;
                }
                return null;
              });
            })()}
          </ChainOfThoughtContent>
        </ChainOfThought>
      );
    });
  };

  return (
    <>
      {messages.map((msg, idx) => {
        const isLast = idx === messages.length - 1;
        return (
          <Message key={msg.id || idx} from={msg.role}>
            <MessageContent>
              {msg.role === 'assistant' && (
                msg.parts
                  ? renderPartsAssistant(msg, isLast)
                  : renderLegacyAssistant(msg, isLast)
              )}
              {!msg.parts && msg.content ? <MessageResponse>{msg.content}</MessageResponse> : null}
            </MessageContent>
          </Message>
        );
      })}
    </>
  );
});

const ChatStreamBody = memo(function ChatStreamBody({
  isLoading,
  messages,
  personaState,
}: {
  isLoading: boolean;
  messages: ChatMessage[];
  personaState: PersonaState;
}) {
  if (messages.length === 0) {
    return <EmptyStateWithPersona state={personaState} />;
  }

  return (
    <>
      <MessageList isLoading={isLoading} messages={messages} />
      <PersonaRail state={personaState} />
    </>
  );
});

export function ChatPanel({
  contextData,
  messages,
  isContextLoading,
  isContextOpen,
  input,
  isLoading,
  model,
  modelOptions,
  onContextOpenChange,
  onInputChange,
  onKeyDown,
  onSendMessage,
  onStopMessage,
  onModelChange,
}: ChatPanelProps) {
  const planSteps = contextData?.planSteps ?? [];
  const [isFocused, setIsFocused] = useState(false);
  const [attachmentFiles, setAttachmentFiles] = useState<AttachmentData[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isModelSelectorOpen, setIsModelSelectorOpen] = useState(false);

  const handleAddFiles = useCallback((fileList: FileList | File[]) => {
    const incoming = Array.from(fileList);
    const newFiles: AttachmentData[] = incoming.map((file) => ({
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      type: 'file' as const,
      filename: file.name,
      mediaType: file.type,
      url: URL.createObjectURL(file),
    }));
    setAttachmentFiles((prev) => [...prev, ...newFiles]);
  }, []);

  const handleRemoveAttachment = useCallback((id: string) => {
    setAttachmentFiles((prev) => {
      const found = prev.find((f) => f.id === id);
      if (found && 'url' in found && found.url) URL.revokeObjectURL(found.url);
      return prev.filter((f) => f.id !== id);
    });
  }, []);

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      handleAddFiles(e.target.files);
      e.target.value = '';
    }
  }, [handleAddFiles]);

  const selectedModel = modelOptions.find((m) => m.envFile === model) ?? modelOptions[0];

  const lastAssistantMessage = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') {
        return messages[i];
      }
    }
    return null;
  }, [messages]);

  const hasDraftInput = isFocused && input.trim().length > 0;
  const hasStreamingResponse = isLoading && Boolean(lastAssistantMessage?.content?.trim());
  const hasCompletedConversation = messages.length > 0 && !isLoading;

  const personaState = useMemo<PersonaState>(() => {
    if (hasStreamingResponse) {
      return 'speaking';
    }
    if (isLoading) {
      return 'thinking';
    }
    if (hasDraftInput) {
      return 'listening';
    }
    if (hasCompletedConversation) {
      return 'idle';
    }
    if (!isFocused) {
      return 'asleep';
    }
    return 'idle';
  }, [hasCompletedConversation, hasDraftInput, hasStreamingResponse, isFocused, isLoading]);

  return (
    <div className="h-full flex flex-col min-w-0 border-r">
      <Conversation className="flex-1">
        <ConversationContent className="gap-4 pb-4">
          <ChatStreamBody
            isLoading={isLoading}
            messages={messages}
            personaState={personaState}
          />
        </ConversationContent>
      </Conversation>

      <div className="shrink-0 border-t bg-background">
        <PlanToggle planSteps={planSteps} isStreaming={isLoading} />

        <div className="p-3 pt-2">
          <div className="flex flex-col rounded-lg border bg-muted/30 p-2 shadow-sm focus-within:ring-1 focus-within:ring-ring">
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              multiple
              onChange={handleFileInputChange}
            />

            {attachmentFiles.length > 0 && (
              <div className="pb-2">
                <Attachments variant="inline">
                  {attachmentFiles.map((file) => (
                    <Attachment
                      key={file.id}
                      data={file}
                      onRemove={() => handleRemoveAttachment(file.id)}
                    >
                      <AttachmentPreview />
                      <AttachmentInfo />
                      <AttachmentRemove />
                    </Attachment>
                  ))}
                </Attachments>
              </div>
            )}

            <Textarea
              value={input}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyDown={onKeyDown}
              onFocus={() => setIsFocused(true)}
              onBlur={() => setIsFocused(false)}
              placeholder="告诉我想实现什么，或粘贴代码、截图、提问..."
              className="min-h-[80px] resize-none border-0 bg-transparent px-1 py-1.5 shadow-none focus-visible:ring-0"
              rows={3}
            />
            <div className="mt-1.5 flex items-center justify-between gap-2 border-t border-border/50 pt-2">
              <div className="flex items-center gap-1">
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => fileInputRef.current?.click()}
                  aria-label="添加附件"
                  title="添加附件"
                >
                  <PaperclipIcon className="w-4 h-4" />
                </Button>

                <ModelSelector open={isModelSelectorOpen} onOpenChange={setIsModelSelectorOpen}>
                  <ModelSelectorTrigger asChild>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 gap-1.5 px-2 text-xs font-medium text-muted-foreground hover:text-foreground"
                    >
                      <ModelSelectorLogo provider={selectedModel?.provider ?? 'openrouter'} />
                      <ModelSelectorName>{selectedModel?.name ?? '选择模型'}</ModelSelectorName>
                    </Button>
                  </ModelSelectorTrigger>
                  <ModelSelectorContent title="选择模型">
                    <ModelSelectorInput placeholder="搜索模型..." />
                    <ModelSelectorList>
                      <ModelSelectorEmpty>未找到模型</ModelSelectorEmpty>
                      <ModelSelectorGroup heading="可用模型">
                        {modelOptions.map((m) => (
                          <ModelSelectorItem
                            key={m.envFile}
                            onSelect={() => {
                              onModelChange(m.envFile);
                              setIsModelSelectorOpen(false);
                            }}
                            className="gap-2"
                          >
                            <ModelSelectorLogo provider={m.provider} />
                            <ModelSelectorName>{m.name}</ModelSelectorName>
                          </ModelSelectorItem>
                        ))}
                      </ModelSelectorGroup>
                    </ModelSelectorList>
                  </ModelSelectorContent>
                </ModelSelector>

                <ContextViewer
                  contextData={contextData}
                  isLoading={isContextLoading}
                  onOpenChange={onContextOpenChange}
                  open={isContextOpen}
                />
              </div>
              {isLoading ? (
                <Button
                  size="icon"
                  variant="destructive"
                  onClick={onStopMessage}
                  aria-label="终止生成"
                  title="终止生成"
                >
                  <Square className="w-3.5 h-3.5 fill-current" />
                </Button>
              ) : (
                <Button
                  size="icon"
                  onClick={onSendMessage}
                  disabled={!input.trim()}
                  aria-label="发送消息"
                  title="发送消息"
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
