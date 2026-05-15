import { ContextViewer } from '@/components/app/context-viewer';
import { ConversationEmptyState } from '@/components/ai-elements/conversation';
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep,
} from '@/components/ai-elements/chain-of-thought';
import { CodeBlock, CodeBlockDiff } from '@/components/ai-elements/code-block';
import { Message, MessageContent, MessageResponse } from '@/components/ai-elements/message';
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
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { getFileLanguage } from '@/lib/app-utils';
import type { ChatMessage, PlanStep, SessionContextPayload, ToolCallRecord } from '@/lib/app-types';
import {
  ChevronDown,
  ChevronRight,
  FileCodeIcon,
  FileSearchIcon,
  FolderOpenIcon,
  ListChecks,
  PencilIcon,
  PlusIcon,
  Square,
  TerminalIcon,
  Trash2Icon,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import type React from 'react';
import { useState } from 'react';

type ChatPanelProps = {
  contextData: SessionContextPayload | null;
  messages: ChatMessage[];
  isContextLoading: boolean;
  isContextOpen: boolean;
  input: string;
  isLoading: boolean;
  onContextOpenChange: (open: boolean) => void;
  onInputChange: (value: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSendMessage: () => void;
  onStopMessage: () => void;
};

const TOOL_ICONS: Record<string, React.ReactNode> = {
  list_file: <FolderOpenIcon className="size-4" />,
  read_file: <FileSearchIcon className="size-4" />,
  write_file: <PlusIcon className="size-4" />,
  replace_file: <PencilIcon className="size-4" />,
  delete_file: <Trash2Icon className="size-4" />,
  execute: <TerminalIcon className="size-4" />,
};

function getToolIcon(name: string) {
  return TOOL_ICONS[name] ?? <FileCodeIcon className="size-4" />;
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
  const command = args.command || args.cmd as string | undefined;

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

  if (toolCall.name === 'execute' && command) {
    return (
      <div className="space-y-2">
        <div className="rounded-md bg-muted/50 p-2 text-xs font-mono">
          <span className="text-muted-foreground">$</span> {command}
        </div>
        {typeof output === 'string' && output && (
          <pre className="overflow-x-auto rounded-md bg-black/80 p-2 text-xs font-mono text-white whitespace-pre-wrap">
            {output}
          </pre>
        )}
      </div>
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

export function ChatPanel({
  contextData,
  messages,
  isContextLoading,
  isContextOpen,
  input,
  isLoading,
  onContextOpenChange,
  onInputChange,
  onKeyDown,
  onSendMessage,
  onStopMessage,
}: ChatPanelProps) {
  const planSteps = contextData?.planSteps ?? [];

  return (
    <div className="h-full flex flex-col min-w-0 border-r">
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <ConversationEmptyState title="智能代码助手" description="描述您的需求，我将为您生成代码并执行" />
        ) : (
          messages.map((msg, idx) => (
            <Message key={msg.id || idx} from={msg.role}>
              <MessageContent>
                {msg.role === 'assistant' && idx === messages.length - 1 && (
                  <>
                    {msg.thoughts?.trim() || (msg.toolCalls?.length ?? 0) > 0 || (isLoading && !msg.content) ? (
                      <ChainOfThought defaultOpen={isLoading}>
                        <ChainOfThoughtHeader>
                          {isLoading ? (
                            <Shimmer duration={1}>正在思考...</Shimmer>
                          ) : (
                            <span>思考过程</span>
                          )}
                        </ChainOfThoughtHeader>
                        <ChainOfThoughtContent>
                          {msg.thoughts?.trim() ? (
                            <ChainOfThoughtStep
                              label={msg.thoughts}
                              status={isLoading ? 'active' : 'complete'}
                            />
                          ) : null}

                          {(msg.toolCalls?.length ?? 0) > 0 ? (
                            <div className="space-y-2">
                              {msg.toolCalls?.map((tc) => {
                                const statusLabel =
                                  tc.state === 'completed' ? '已完成' :
                                  tc.state === 'error' ? '出错' : '执行中';

                                return (
                                  <Task key={tc.id}>
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
                              })}
                            </div>
                          ) : null}

                          {isLoading && !msg.thoughts?.trim() && (msg.toolCalls?.length ?? 0) === 0 && !msg.content ? (
                            <div className="px-3 py-1 text-sm text-muted-foreground">
                              <Shimmer duration={1.5}>正在分析...</Shimmer>
                            </div>
                          ) : null}
                        </ChainOfThoughtContent>
                      </ChainOfThought>
                    ) : null}
                  </>
                )}
                {msg.role === 'assistant' && idx !== messages.length - 1 && (msg.toolCalls?.length ?? 0) > 0 && (
                  <div className="space-y-2">
                    {msg.toolCalls?.map((tc) => {
                      const statusLabel =
                        tc.state === 'completed' ? '已完成' :
                        tc.state === 'error' ? '出错' : '执行中';

                      return (
                        <Task key={tc.id}>
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
                    })}
                  </div>
                )}
                {msg.content ? <MessageResponse>{msg.content}</MessageResponse> : null}
              </MessageContent>
            </Message>
          ))
        )}
      </div>

      <div className="shrink-0 border-t bg-background">
        <PlanToggle planSteps={planSteps} isStreaming={isLoading} />

        <div className="p-3 pt-2">
          <div className="flex flex-col rounded-lg border bg-muted/30 p-2 shadow-sm focus-within:ring-1 focus-within:ring-ring">
            <Textarea
              value={input}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="告诉我想实现什么，或粘贴代码、截图、提问..."
              className="min-h-[80px] resize-none border-0 bg-transparent px-1 py-1.5 shadow-none focus-visible:ring-0"
              rows={3}
            />
            <div className="mt-1.5 flex items-center justify-end gap-2 border-t border-border/50 pt-2">
              <ContextViewer
                contextData={contextData}
                isLoading={isContextLoading}
                onOpenChange={onContextOpenChange}
                open={isContextOpen}
              />
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
