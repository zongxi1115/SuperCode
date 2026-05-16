import {
  Context,
  ContextCacheUsage,
  ContextContent,
  ContextContentBody,
  ContextContentFooter,
  ContextContentHeader,
  ContextInputUsage,
  ContextOutputUsage,
  ContextReasoningUsage,
  ContextTrigger,
} from '@/components/ai-elements/context';
import {
  Queue,
  QueueItem,
  QueueItemDescription,
  QueueItemTitle,
} from '@/components/ai-elements/queue';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { SessionContextPayload } from '@/lib/app-types';
import { Bot, LoaderCircle, MessageSquare, Sparkles, Wrench } from 'lucide-react';

type ContextViewerProps = {
  contextData: SessionContextPayload | null;
  isLoading: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

function trimText(value: string, maxLength = 180) {
  const compact = value.replace(/\s+/g, ' ').trim();
  if (compact.length <= maxLength) {
    return compact;
  }
  return `${compact.slice(0, maxLength)}...`;
}

function isMeaningfulThought(value: string) {
  const trimmed = value.trim();
  return Boolean(trimmed && trimmed !== '模型未提供思路。');
}

export function ContextViewer({
  contextData,
  isLoading,
  open,
  onOpenChange,
}: ContextViewerProps) {
  const recentThoughts = (contextData?.recentThoughts ?? []).filter(isMeaningfulThought);
  const usedTokens = contextData?.estimatedTokens ?? 0;
  const maxTokens = Math.max(contextData?.maxTokens ?? 1, 1);
  const usage = {
    inputTokens: Math.max(Math.round(usedTokens * 0.65), 0),
    outputTokens: Math.max(Math.round(usedTokens * 0.25), 0),
    reasoningTokens: Math.max(Math.round(usedTokens * 0.1), 0),
  };

  return (
    <>
      <Context
        maxTokens={maxTokens}
        modelId={contextData?.model}
        openDelay={120}
        usedTokens={usedTokens}
        usage={usage}
      >
        <ContextTrigger onClick={() => onOpenChange(true)} />
        <ContextContent align="end" className="w-72">
          <ContextContentHeader />
          <ContextContentBody className="space-y-2">
            <ContextInputUsage />
            <ContextOutputUsage />
            <ContextReasoningUsage />
            <ContextCacheUsage />
            <div className="mt-2 flex items-center justify-between text-xs">
              <span className="text-muted-foreground">消息</span>
              <span>{contextData?.messageCount ?? 0}</span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">工具调用</span>
              <span>{contextData?.toolCallCount ?? 0}</span>
            </div>
          </ContextContentBody>
          <ContextContentFooter>
            <span className="text-muted-foreground">模型</span>
            <span className="truncate">{contextData?.model ?? '加载中'}</span>
          </ContextContentFooter>
        </ContextContent>
      </Context>

      <Dialog onOpenChange={onOpenChange} open={open}>
        <DialogContent className="max-w-3xl p-0">
          <DialogHeader className="border-b px-6 py-4">
            <DialogTitle>会话上下文</DialogTitle>
            <DialogDescription>
              查看当前会话已累积的消息、工具调用、思考片段和当前工作区信息。
            </DialogDescription>
          </DialogHeader>

          <ScrollArea className="max-h-[70vh]">
            <div className="space-y-5 px-6 py-5">
              {isLoading && !contextData ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <LoaderCircle className="size-4 animate-spin" />
                  正在读取上下文...
                </div>
              ) : null}

              {contextData ? (
                <>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary">
                      <MessageSquare className="size-3" />
                      {contextData.messageCount} 条消息
                    </Badge>
                    <Badge variant="secondary">
                      <Wrench className="size-3" />
                      {contextData.toolCallCount} 次工具
                    </Badge>
                    <Badge variant="secondary">
                      <Sparkles className="size-3" />
                      {contextData.thoughtCount} 段思考
                    </Badge>
                    <Badge variant="outline">
                      约 {contextData.estimatedTokens} / {contextData.maxTokens} tokens
                    </Badge>
                  </div>

                  <section className="space-y-2">
                    <h3 className="text-sm font-medium">基础信息</h3>
                    <div className="rounded-lg border bg-muted/20 p-3 text-xs leading-6">
                      <div>模型：{contextData.model}</div>
                      <div>模式：{contextData.mode}</div>
                      <div>工作区：{contextData.workspace}</div>
                      <div>当前文件：{contextData.selectedFilePath || '暂无'}</div>
                      <div>打开标签：{contextData.openFiles.join('、') || '暂无'}</div>
                    </div>
                  </section>

                  <section className="space-y-2">
                    <h3 className="text-sm font-medium">最近消息</h3>
                    <div className="space-y-2">
                      {contextData.recentMessages.length ? (
                        contextData.recentMessages.map((message, index) => (
                          <div key={`${message.role}-${index}`} className="rounded-lg border p-3 text-sm">
                            <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
                              {message.role === 'assistant' ? <Bot className="size-3.5" /> : <MessageSquare className="size-3.5" />}
                              <span>{message.role === 'assistant' ? '助手' : '用户'}</span>
                            </div>
                            <div className="leading-6 text-foreground/90">{trimText(message.content, 280) || '空消息'}</div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">当前还没有消息上下文。</div>
                      )}
                    </div>
                  </section>

                  <section className="space-y-2">
                    <h3 className="text-sm font-medium">最近工具调用</h3>
                    <div className="space-y-2">
                      {contextData.recentTools.length ? (
                        contextData.recentTools.map((tool) => (
                          <div key={tool.id} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
                            <div className="flex items-center gap-2">
                              <Wrench className="size-3.5 text-muted-foreground" />
                              <span>{tool.name}</span>
                            </div>
                            <Badge variant={tool.state === 'error' ? 'destructive' : 'outline'}>{tool.state}</Badge>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">当前还没有工具调用记录。</div>
                      )}
                    </div>
                  </section>

                  <section className="space-y-2">
                    <h3 className="text-sm font-medium">最近思考</h3>
                    <div className="space-y-2">
                      {recentThoughts.length ? (
                        recentThoughts.map((thought, index) => (
                          <div key={index} className="rounded-lg border p-3 text-sm leading-6 text-foreground/85">
                            {trimText(thought, 320)}
                          </div>
                        ))
                      ) : (
                        <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">当前还没有可展示的思考片段。</div>
                      )}
                    </div>
                  </section>

                  <section className="space-y-2">
                    <h3 className="text-sm font-medium">当前计划</h3>
                    <Queue>
                      {contextData.planSteps.map((step) => {
                        const status = step.status === 'completed' ? 'completed' : step.status === 'error' ? 'error' : step.status === 'running' ? 'running' : 'pending';
                        return (
                          <QueueItem key={step.id} status={status}>
                            <QueueItemTitle>{step.title}</QueueItemTitle>
                            <QueueItemDescription>{step.description}</QueueItemDescription>
                          </QueueItem>
                        );
                      })}
                    </Queue>
                  </section>
                </>
              ) : null}
            </div>
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </>
  );
}
