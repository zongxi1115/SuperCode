import { ContextViewer } from "@/components/app/context-viewer";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
} from "@/components/ai-elements/conversation";
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import { CodeBlock, CodeBlockDiff } from "@/components/ai-elements/code-block";
import {
  Confirmation,
  ConfirmationAccepted,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRejected,
  ConfirmationRequest,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import {
  Commit,
  CommitActions,
  CommitAuthor,
  CommitAuthorAvatar,
  CommitContent,
  CommitCopyButton,
  CommitFile,
  CommitFileAdditions,
  CommitFileChanges,
  CommitFileDeletions,
  CommitFileIcon,
  CommitFileInfo,
  CommitFilePath,
  CommitFiles,
  CommitHash,
  CommitFileStatus,
  CommitHeader,
  CommitInfo,
  CommitMessage,
  CommitMetadata,
  CommitSeparator,
  CommitTimestamp,
} from "@/components/ai-elements/commit";
import { Terminal } from "@/components/ai-elements/terminal";
import {
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import { Persona, type PersonaState } from "@/components/ai-elements/persona";
import {
  Queue,
  QueueItem,
  QueueItemDescription,
  QueueItemTitle,
} from "@/components/ai-elements/queue";
import { Shimmer } from "@/components/ai-elements/shimmer";
import {
  Task,
  TaskContent,
  TaskItem,
  TaskItemFile,
  TaskTrigger,
} from "@/components/ai-elements/task";
import {
  Attachments,
  Attachment,
  AttachmentPreview,
  AttachmentInfo,
  AttachmentRemove,
  type AttachmentData,
} from "@/components/ai-elements/attachments";
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
} from "@/components/ai-elements/model-selector";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { getFileLanguage } from "@/lib/app-utils";
import { getFileIcon } from "@/lib/file-icons";
import type {
  ChatMessage,
  ContentBlock,
  ModelOption,
  PlanStep,
  SessionContextPayload,
  ToolCallRecord,
} from "@/lib/app-types";
import {
  ChevronDown,
  ChevronRight,
  BarChart3Icon,
  DatabaseIcon,
  FileCodeIcon,
  FileSearchIcon,
  FolderOpenIcon,
  GitBranch,
  GitCommitHorizontal,
  Tag,
  ListChecks,
  PencilIcon,
  PlusIcon,
  PaperclipIcon,
  Square,
  TerminalIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type React from "react";
import { memo, useMemo, useRef, useState, useCallback, useEffect } from "react";

type ElementAttachment = {
  id: string;
  selector: string;
  html: string;
  sourceUrl?: string;
};

type ChatPanelProps = {
  sessionId: string | null;
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
  onResolveDeleteConfirmation: (toolCallId: string, approved: boolean) => void;
  onResolveGitConfirmation: (
    toolCallId: string,
    type: "commit" | "tag",
    approved: boolean,
  ) => void;
  onModelChange: (modelId: string) => void;
  elementAttachments?: ElementAttachment[];
  onRemoveElementAttachment?: (id: string) => void;
};

const TOOL_ICONS: Record<string, React.ReactNode> = {
  list_file: <FolderOpenIcon className="size-4" />,
  read_file: <FileSearchIcon className="size-4" />,
  write_file: <PlusIcon className="size-4" />,
  apply_patch: <PencilIcon className="size-4" />,
  replace_file: <PencilIcon className="size-4" />,
  delete_file: <Trash2Icon className="size-4" />,
  execute: <TerminalIcon className="size-4" />,
  excecute: <TerminalIcon className="size-4" />,
  terminal_input: <TerminalIcon className="size-4" />,
  terminal_wait: <TerminalIcon className="size-4" />,
  git_commit: <GitCommitHorizontal className="size-4" />,
  git_log: <GitBranch className="size-4" />,
  git_tag: <Tag className="size-4" />,
};

const TOOL_TITLES: Record<string, (args: Record<string, unknown>) => string> = {
  list_file: () => "正在列出文件",
  read_file: (args) => {
    const f = ((args.filename || args.path || args.file_path) as string)?.split(/[\\/]/).pop();
    return f ? `正在阅读 ${f}` : "正在阅读文件";
  },
  write_file: (args) => {
    const f = ((args.filename || args.path || args.file_path) as string)?.split(/[\\/]/).pop();
    return f ? `正在创建 ${f}` : "正在创建文件";
  },
  apply_patch: (args) => {
    const f = ((args.filename || args.path || args.file_path) as string)?.split(/[\\/]/).pop();
    return f ? `正在编辑 ${f}` : "正在编辑文件";
  },
  replace_file: (args) => {
    const f = ((args.filename || args.path || args.file_path) as string)?.split(/[\\/]/).pop();
    return f ? `正在替换 ${f}` : "正在替换文件";
  },
  delete_file: (args) => {
    const f = ((args.filename || args.path || args.file_path) as string)?.split(/[\\/]/).pop();
    return f ? `正在删除 ${f}` : "正在删除文件";
  },
  execute: () => "正在执行命令",
  excecute: () => "正在执行命令",
  terminal_input: () => "正在执行命令",
  terminal_wait: () => "等待终端",
  git_commit: () => "正在提交",
  git_log: () => "正在查看日志",
  git_tag: () => "正在创建标签",
};

function getToolTitle(name: string, args: Record<string, unknown>): string {
  const fn = TOOL_TITLES[name];
  return fn ? fn(args) : "执行中";
}

function getToolIcon(name: string) {
  return TOOL_ICONS[name] ?? <FileCodeIcon className="size-4" />;
}

function normalizeThoughtText(value?: string | null) {
  const trimmed = value?.trim() ?? "";
  if (!trimmed || trimmed === "模型未提供思路。") {
    return "";
  }
  return trimmed;
}

function parseGitStatus(raw: string): {
  status: "added" | "modified" | "deleted" | "renamed";
  path: string;
} {
  const normalized = raw.trim();
  const code = normalized.slice(0, 2).replace(/\s/g, "");
  const path = normalized.slice(2).trim() || normalized;
  if (code.includes("R")) return { status: "renamed", path };
  if (code.includes("D")) return { status: "deleted", path };
  if (code.includes("A") || code === "??") return { status: "added", path };
  return { status: "modified", path };
}

function GitCommitPreview({
  sessionId,
  toolCall,
  onResolveGitConfirmation,
}: {
  sessionId: string | null;
  toolCall: ToolCallRecord;
  onResolveGitConfirmation: (
    toolCallId: string,
    type: "commit" | "tag",
    approved: boolean,
  ) => void;
}) {
  const output = toolCall.output;
  const commitPayload =
    output && typeof output === "object" && !Array.isArray(output)
      ? (output as Record<string, unknown>)
      : undefined;
  const commitMessage =
    typeof commitPayload?.commit_message === "string"
      ? commitPayload.commit_message
      : typeof toolCall.arguments?.message === "string"
        ? toolCall.arguments.message
        : typeof commitPayload?.message === "string"
          ? commitPayload.message
          : undefined;
  const hasChanges = commitPayload?.has_changes !== false;
  const initialChangedFiles = Array.isArray(commitPayload?.changed_files)
    ? (commitPayload.changed_files as string[])
    : Array.isArray(commitPayload?.changedFiles)
      ? (commitPayload.changedFiles as string[])
      : [];
  const initialChangedFilesKey = initialChangedFiles.join("\n");
  const [fallbackChangedFiles, setFallbackChangedFiles] =
    useState<string[]>(initialChangedFiles);

  useEffect(() => {
    setFallbackChangedFiles(initialChangedFiles);
  }, [initialChangedFilesKey]);

  useEffect(() => {
    if (
      !sessionId ||
      toolCall.state !== "approval-requested" ||
      initialChangedFiles.length > 0
    ) {
      return;
    }

    let disposed = false;
    void fetch(`http://localhost:8000/api/sessions/${sessionId}/git/status`)
      .then(async (res) => {
        if (!res.ok) {
          return;
        }
        const data = await res.json();
        if (disposed) {
          return;
        }
        setFallbackChangedFiles(
          Array.isArray(data.changedFiles)
            ? (data.changedFiles as string[])
            : [],
        );
      })
      .catch((error) => {
        console.error(error);
      });

    return () => {
      disposed = true;
    };
  }, [initialChangedFilesKey, sessionId, toolCall.state]);

  const changedFiles =
    initialChangedFiles.length > 0 ? initialChangedFiles : fallbackChangedFiles;
  const confirmationMessage =
    typeof commitPayload?.message === "string"
      ? commitPayload.message
      : undefined;
  const approval = toolCall.approval ?? { id: toolCall.id };
  const confirmationState =
    toolCall.state === "completed" ? "output-available" : toolCall.state;
  const previewHash = toolCall.id.slice(0, 7);
  const previewDate = new Date();

  if (!hasChanges) {
    return (
      <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
        没有待提交的变更。
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <Confirmation approval={approval} state={confirmationState as never}>
        <ConfirmationTitle>
          {confirmationMessage ?? `确认提交？`}
        </ConfirmationTitle>
        <Commit className="mt-2" defaultOpen>
          <CommitHeader>
            <CommitAuthor>
              <CommitAuthorAvatar initials="SC" />
            </CommitAuthor>
            <CommitInfo>
              <CommitMessage>{commitMessage ?? "git commit"}</CommitMessage>
              <CommitMetadata>
                <CommitHash>{previewHash}</CommitHash>
                <CommitSeparator />
                <CommitTimestamp date={previewDate}>待提交</CommitTimestamp>
                <CommitSeparator />
                <span>{changedFiles.length} 个文件</span>
              </CommitMetadata>
            </CommitInfo>
            <CommitActions>
              <CommitCopyButton
                hash={commitMessage ?? ""}
                disabled={!commitMessage}
              />
            </CommitActions>
          </CommitHeader>
          {changedFiles.length > 0 ? (
            <CommitContent>
              <CommitFiles>
                {changedFiles.map((rawFile: string, i: number) => {
                  const parsed = parseGitStatus(rawFile);
                  const fileIcon = getFileIcon(parsed.path.split(/[\\/]/).pop() ?? '');
                  return (
                    <CommitFile key={`${rawFile}-${i}`}>
                      <CommitFileInfo>
                        <CommitFileStatus status={parsed.status} />
                        {fileIcon ? (
                          <span style={{ color: fileIcon.color }}>{fileIcon.icon}</span>
                        ) : (
                          <CommitFileIcon />
                        )}
                        <CommitFilePath>{parsed.path}</CommitFilePath>
                      </CommitFileInfo>
                      <CommitFileChanges>
                        <CommitFileAdditions count={0} />
                        <CommitFileDeletions count={0} />
                      </CommitFileChanges>
                    </CommitFile>
                  );
                })}
              </CommitFiles>
            </CommitContent>
          ) : null}
        </Commit>
        <ConfirmationRequest>
          <ConfirmationActions>
            <ConfirmationAction
              variant="outline"
              onClick={() =>
                onResolveGitConfirmation(toolCall.id, "commit", false)
              }
            >
              取消
            </ConfirmationAction>
            <ConfirmationAction
              variant="default"
              onClick={() =>
                onResolveGitConfirmation(toolCall.id, "commit", true)
              }
            >
              确认提交
            </ConfirmationAction>
          </ConfirmationActions>
        </ConfirmationRequest>
        <ConfirmationAccepted>
          <p className="text-xs text-muted-foreground">提交成功。</p>
        </ConfirmationAccepted>
        <ConfirmationRejected>
          <p className="text-xs text-muted-foreground">提交已取消。</p>
        </ConfirmationRejected>
      </Confirmation>
    </div>
  );
}

function ToolBody({
  toolCall,
  sessionId,
  onResolveDeleteConfirmation,
  onResolveGitConfirmation,
}: {
  toolCall: ToolCallRecord;
  sessionId: string | null;
  onResolveDeleteConfirmation: (toolCallId: string, approved: boolean) => void;
  onResolveGitConfirmation: (
    toolCallId: string,
    type: "commit" | "tag",
    approved: boolean,
  ) => void;
}) {
  const args = toolCall.arguments || {};
  const output =
    toolCall.state === "completed" ||
    toolCall.state === "output-available" ||
    toolCall.state === "output-denied"
      ? toolCall.output
      : undefined;
  const errorText =
    toolCall.state === "error"
      ? String(
          toolCall.errorMessage || toolCall.error_message || toolCall.output,
        )
      : undefined;
  const isStreaming = toolCall.state === "running";

  const filename = (args.filename || args.path || args.file_path) as
    | string
    | undefined;
  const content =
    (args.content as string | undefined) ??
    (toolCall.name === "write_file" ? toolCall.streamedInput : undefined);
  const oldContent = args.old_content || (args.old_code as string | undefined);
  const newContent = (args.new_content ||
    args.new_code ||
    (toolCall.name === "replace_file" ? toolCall.streamedInput : undefined)) as
    | string
    | undefined;
  const patchText = (args.patch ||
    (toolCall.name === "apply_patch" ? toolCall.streamedInput : undefined)) as
    | string
    | undefined;
  const command =
    args.command || args.cmd || (args.content as string | undefined);
  const terminalPayload =
    output && typeof output === "object" && !Array.isArray(output)
      ? (output as Record<string, unknown>)
      : undefined;
  const terminalStatus =
    typeof terminalPayload?.status === "string"
      ? terminalPayload.status
      : undefined;
  const terminalId =
    typeof terminalPayload?.terminal_id === "string"
      ? terminalPayload.terminal_id
      : typeof args.terminal_id === "string"
        ? args.terminal_id
        : undefined;
  const terminalFullOutput =
    typeof terminalPayload?.full_output === "string"
      ? terminalPayload.full_output
      : typeof output === "string"
        ? output
        : undefined;

  if (toolCall.name === "write_file" && content) {
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
          enableHighlighting={!isStreaming}
          language={filename ? (getFileLanguage(filename) as never) : "text"}
          viewportClassName="overflow-x-auto"
        />
      </div>
    );
  }

  if (toolCall.name === "replace_file" && oldContent && newContent) {
    const diffLines = [
      ...oldContent.split("\n").map((l: string) => `- ${l}`),
      "---",
      ...newContent.split("\n").map((l: string) => `+ ${l}`),
    ].join("\n");

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

  if (toolCall.name === "read_file" && typeof output === "string") {
    const fileIcon = filename
      ? getFileIcon(filename.split(/[\\/]/).pop() ?? "")
      : null;
    return (
      <span className="inline-flex items-center gap-1 text-muted-foreground text-sm">
        正在阅读文件
        <TaskItemFile>
          {fileIcon ? (
            <span style={{ color: fileIcon.color }}>{fileIcon.icon}</span>
          ) : (
            <FileCodeIcon className="size-3" />
          )}
          <span>{filename ? filename.split(/[\\/]/).pop() : filename}</span>
        </TaskItemFile>
      </span>
    );
  }

  if (toolCall.name === "read_file") {
    const fileIcon = filename
      ? getFileIcon(filename.split(/[\\/]/).pop() ?? "")
      : null;
    return (
      <span className="inline-flex items-center gap-1 text-muted-foreground text-sm">
        正在阅读文件
        <TaskItemFile>
          {fileIcon ? (
            <span style={{ color: fileIcon.color }}>{fileIcon.icon}</span>
          ) : (
            <FileCodeIcon className="size-3" />
          )}
          <span>
            {filename ? filename.split(/[\\/]/).pop() : (filename ?? "...")}
          </span>
        </TaskItemFile>
      </span>
    );
  }

  if (toolCall.name === "replace_file" && newContent) {
    return (
      <div className="space-y-2">
        {filename && (
          <TaskItemFile>
            <FileCodeIcon className="size-3" />
            {filename}
          </TaskItemFile>
        )}
        <CodeBlock
          code={newContent}
          enableHighlighting={!isStreaming}
          language={filename ? (getFileLanguage(filename) as never) : "text"}
          viewportClassName="overflow-x-auto"
        />
      </div>
    );
  }

  if (toolCall.name === "apply_patch" && patchText) {
    return (
      <div className="space-y-2">
        <CodeBlock
          code={patchText}
          enableHighlighting={!isStreaming}
          language={"diff" as never}
          viewportClassName="overflow-x-auto"
        />
      </div>
    );
  }

  if (toolCall.name === "delete_file") {
    const deletePayload =
      output && typeof output === "object" && !Array.isArray(output)
        ? (output as Record<string, unknown>)
        : undefined;
    const deleteFilename =
      filename ??
      (typeof deletePayload?.filename === "string"
        ? deletePayload.filename
        : undefined);
    const confirmationMessage =
      typeof deletePayload?.message === "string"
        ? deletePayload.message
        : undefined;
    const approval = toolCall.approval ?? { id: toolCall.id };
    const confirmationState =
      toolCall.state === "completed" ? "output-available" : toolCall.state;

    return (
      <div className="space-y-3">
        {deleteFilename ? (
          <TaskItemFile>
            <FileCodeIcon className="size-3" />
            {deleteFilename}
          </TaskItemFile>
        ) : null}
        <Confirmation approval={approval} state={confirmationState as never}>
          <ConfirmationTitle>
            {confirmationMessage ??
              `确认删除文件${deleteFilename ? ` ${deleteFilename}` : ""}？`}
          </ConfirmationTitle>
          <ConfirmationRequest>
            <ConfirmationActions>
              <ConfirmationAction
                variant="outline"
                onClick={() => onResolveDeleteConfirmation(toolCall.id, false)}
              >
                取消
              </ConfirmationAction>
              <ConfirmationAction
                variant="destructive"
                onClick={() => onResolveDeleteConfirmation(toolCall.id, true)}
              >
                删除
              </ConfirmationAction>
            </ConfirmationActions>
          </ConfirmationRequest>
          <ConfirmationAccepted>
            <p className="text-xs text-muted-foreground">文件已删除。</p>
          </ConfirmationAccepted>
          <ConfirmationRejected>
            <p className="text-xs text-muted-foreground">删除已取消。</p>
          </ConfirmationRejected>
        </Confirmation>
      </div>
    );
  }

  if (toolCall.name === "git_commit") {
    return (
      <GitCommitPreview
        sessionId={sessionId}
        toolCall={toolCall}
        onResolveGitConfirmation={onResolveGitConfirmation}
      />
    );
  }

  if (toolCall.name === "git_tag") {
    const tagPayload =
      output && typeof output === "object" && !Array.isArray(output)
        ? (output as Record<string, unknown>)
        : undefined;
    const tagName =
      typeof tagPayload?.tag === "string" ? tagPayload.tag : undefined;
    const tagMessage =
      typeof tagPayload?.tag_message === "string"
        ? tagPayload.tag_message
        : undefined;
    const confirmationMessage =
      typeof tagPayload?.message === "string" ? tagPayload.message : undefined;
    const approval = toolCall.approval ?? { id: toolCall.id };
    const confirmationState =
      toolCall.state === "completed" ? "output-available" : toolCall.state;

    if (
      output &&
      typeof output === "object" &&
      "tags" in (output as Record<string, unknown>)
    ) {
      const tagList = (output as Record<string, unknown>).tags as string[];
      return (
        <div className="space-y-1">
          <div className="text-xs font-medium text-muted-foreground">
            标签列表 ({tagList.length})
          </div>
          {tagList.map((t: string) => (
            <div key={t} className="flex items-center gap-1.5 text-xs">
              <Tag className="size-3 text-muted-foreground" />
              <span className="font-mono">{t}</span>
            </div>
          ))}
        </div>
      );
    }

    return (
      <div className="space-y-3">
        <Confirmation approval={approval} state={confirmationState as never}>
          <ConfirmationTitle>
            {confirmationMessage ?? `确认创建标签？`}
          </ConfirmationTitle>
          {tagName && (
            <div className="rounded-md bg-muted/30 p-2 mt-2 text-xs font-mono flex items-center gap-1.5">
              <Tag className="size-3" />
              {tagName}
              {tagMessage && (
                <span className="text-muted-foreground ml-2">{tagMessage}</span>
              )}
            </div>
          )}
          <ConfirmationRequest>
            <ConfirmationActions>
              <ConfirmationAction
                variant="outline"
                onClick={() =>
                  onResolveGitConfirmation(toolCall.id, "tag", false)
                }
              >
                取消
              </ConfirmationAction>
              <ConfirmationAction
                variant="default"
                onClick={() =>
                  onResolveGitConfirmation(toolCall.id, "tag", true)
                }
              >
                确认创建
              </ConfirmationAction>
            </ConfirmationActions>
          </ConfirmationRequest>
          <ConfirmationAccepted>
            <p className="text-xs text-muted-foreground">标签已创建。</p>
          </ConfirmationAccepted>
          <ConfirmationRejected>
            <p className="text-xs text-muted-foreground">创建标签已取消。</p>
          </ConfirmationRejected>
        </Confirmation>
      </div>
    );
  }

  if (toolCall.name === "git_log" && typeof output === "string") {
    return (
      <div className="space-y-2">
        <pre className="overflow-x-auto rounded-md bg-muted/50 p-2 text-xs font-mono whitespace-pre-wrap">
          {output}
        </pre>
      </div>
    );
  }

  if (
    toolCall.name === "open_browser" &&
    output &&
    typeof output === "object" &&
    !Array.isArray(output)
  ) {
    const browserPayload = output as Record<string, unknown>;
    const targetValue =
      typeof browserPayload.target === "string"
        ? browserPayload.target
        : undefined;
    const resolvedUrl =
      typeof browserPayload.resolved_url === "string"
        ? browserPayload.resolved_url
        : undefined;
    const sourceType =
      typeof browserPayload.source_type === "string"
        ? browserPayload.source_type
        : undefined;
    const absolutePath =
      typeof browserPayload.absolute_path === "string"
        ? browserPayload.absolute_path
        : undefined;

    return (
      <div className="space-y-2 rounded-md bg-muted/50 p-3 text-xs">
        <p className="font-medium text-foreground">已在右侧浏览器预览中打开</p>
        {targetValue ? (
          <p className="text-muted-foreground">目标：{targetValue}</p>
        ) : null}
        {sourceType ? (
          <p className="text-muted-foreground">
            类型：
            {sourceType === "network_url"
              ? "网络地址"
              : sourceType === "local_file"
                ? "本地文件"
                : sourceType}
          </p>
        ) : null}
        {absolutePath ? (
          <p className="text-muted-foreground">绝对路径：{absolutePath}</p>
        ) : null}
        {resolvedUrl ? (
          <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-background/80 p-2 font-mono">
            {resolvedUrl}
          </pre>
        ) : null}
      </div>
    );
  }

  if (toolCall.name === "list_file" && typeof output === "string") {
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
    (toolCall.name === "execute" ||
      toolCall.name === "excecute" ||
      toolCall.name === "terminal_input" ||
      toolCall.name === "terminal_wait") &&
    (command || content || terminalStatus || terminalFullOutput)
  ) {
    const cmdText =
      toolCall.name === "terminal_input"
        ? content
        : toolCall.name === "terminal_wait"
          ? `wait ${String(args.timeout ?? "")}s`
          : (command ?? content);
    const termOutput = [
      terminalId && `# ${terminalId}`,
      cmdText && `$ ${cmdText}`,
      terminalFullOutput,
      errorText,
    ]
      .filter(Boolean)
      .join("\n");
    const isRunning = toolCall.state === "running";

    return <Terminal output={termOutput} isStreaming={isRunning} />;
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
            {typeof output === "string"
              ? output
              : JSON.stringify(output, null, 2)}
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

function PlanToggle({
  planSteps,
  isStreaming,
}: {
  planSteps: PlanStep[];
  isStreaming: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);

  if (planSteps.length === 0) return null;

  const completedCount = planSteps.filter(
    (s) => s.status === "completed",
  ).length;

  return (
    <div className="px-3">
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className="flex items-center gap-2 w-full rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
      >
        <ListChecks className="size-3.5 shrink-0" />
        <span className="flex-1 text-left">计划</span>
        <span className="text-[10px] tabular-nums">
          {completedCount}/{planSteps.length}
        </span>
        <motion.div
          animate={{ rotate: isOpen ? 180 : 0 }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
        >
          <ChevronDown className="size-3" />
        </motion.div>
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 260, damping: 26 }}
            className="overflow-hidden"
          >
            <div className="px-1 pb-2 pt-1">
              <Queue isStreaming={isStreaming}>
                {planSteps.map((step) => (
                  <QueueItem key={step.id} status={step.status}>
                    <QueueItemTitle>{step.title}</QueueItemTitle>
                    <QueueItemDescription>
                      {step.description}
                    </QueueItemDescription>
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

function DataPartView({
  part,
}: {
  part: Extract<ContentBlock, { type: "data" }>;
}) {
  const data = part.data;

  if (
    part.dataType === "data-chart" &&
    data &&
    typeof data === "object" &&
    !Array.isArray(data)
  ) {
    const chart = data as { title?: unknown; points?: unknown };
    const points = Array.isArray(chart.points)
      ? chart.points
          .map((point) =>
            point && typeof point === "object"
              ? (point as { x?: unknown; y?: unknown })
              : null,
          )
          .filter(
            (point): point is { x?: unknown; y?: unknown } =>
              Boolean(point) && typeof point?.y === "number",
          )
      : [];
    const maxValue = Math.max(...points.map((point) => Number(point.y)), 1);

    return (
      <div className="rounded-md border bg-background p-3">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          <BarChart3Icon className="size-4 text-primary" />
          {typeof chart.title === "string" ? chart.title : "图表"}
        </div>
        <div className="flex h-36 items-end gap-2">
          {points.map((point, index) => (
            <div
              key={`${String(point.x)}-${index}`}
              className="flex min-w-10 flex-1 flex-col items-center gap-1"
            >
              <div
                className="w-full rounded-t bg-primary/80"
                style={{
                  height: `${Math.max((Number(point.y) / maxValue) * 100, 4)}%`,
                }}
              />
              <span className="max-w-full truncate text-xs text-muted-foreground">
                {String(point.x ?? "")}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-md border bg-muted/30 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <DatabaseIcon className="size-3.5" />
        {part.dataType}
      </div>
      <CodeBlock code={JSON.stringify(data, null, 2)} language="json" />
    </div>
  );
}

const personaLabels: Record<PersonaState, string> = {
  asleep: "Asleep",
  idle: "Idle",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

const PERSONA_LAYOUT_ID = "chat-persona-shell";

const PersonaShell = memo(function PersonaShell({
  state,
}: {
  state: PersonaState;
}) {
  return (
    <motion.div
      layoutId={PERSONA_LAYOUT_ID}
      transition={{ type: "spring", stiffness: 320, damping: 30 }}
      aria-label={`AI status: ${personaLabels[state]}`}
      className="pointer-events-none inline-flex items-center justify-start"
    >
      <Persona variant="glint" state={state} className="size-12" />
    </motion.div>
  );
});

const PersonaRail = memo(function PersonaRail({
  state,
}: {
  state: PersonaState;
}) {
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
          <p className="text-muted-foreground text-sm">
            描述您的需求，我将为您生成代码并执行
          </p>
        </div>
      </motion.div>
    </ConversationEmptyState>
  );
});

const MessageList = memo(function MessageList({
  sessionId,
  isLoading,
  messages,
  onResolveDeleteConfirmation,
  onResolveGitConfirmation,
}: {
  sessionId: string | null;
  isLoading: boolean;
  messages: ChatMessage[];
  onResolveDeleteConfirmation: (toolCallId: string, approved: boolean) => void;
  onResolveGitConfirmation: (
    toolCallId: string,
    type: "commit" | "tag",
    approved: boolean,
  ) => void;
}) {
  const statusLabelMap: Record<ToolCallRecord["state"], string> = {
    running: "执行中",
    completed: "已完成",
    error: "出错",
    "approval-requested": "待确认",
    "output-available": "已完成",
    "output-denied": "已拒绝",
  };

  const renderToolCall = (tc: ToolCallRecord, isLastRunning: boolean) => {
    const statusLabel = statusLabelMap[tc.state] ?? "执行中";
    const shouldOpen = isLastRunning || tc.name.startsWith("git_");
    const toolTitle = `${getToolTitle(tc.name, tc.arguments ?? {})} · ${statusLabel}`;

    return (
      <Task key={tc.id} defaultOpen={shouldOpen}>
        <TaskTrigger
          title={tc.state === "running" && isLastRunning ? <Shimmer duration={1}>{toolTitle}</Shimmer> : toolTitle}
          icon={getToolIcon(tc.name)}
        />
        <TaskContent>
          <TaskItem>
            <ToolBody
              sessionId={sessionId}
              toolCall={tc}
              onResolveDeleteConfirmation={onResolveDeleteConfirmation}
              onResolveGitConfirmation={onResolveGitConfirmation}
            />
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
                  status={isLoading ? "active" : "complete"}
                />
                {hasToolCalls ? (
                  <div className="space-y-2">
                    {(() => {
                      const lastRunningIdx = [...(msg.toolCalls ?? [])].findLastIndex((tc) => tc.state === "running");
                      return msg.toolCalls?.map((tc, tci) =>
                        renderToolCall(tc, tci === lastRunningIdx),
                      );
                    })()}
                  </div>
                ) : null}
              </ChainOfThoughtContent>
            </ChainOfThought>
          ) : hasToolCalls ? (
            <div className="space-y-2">
              {(() => {
                const lastRunningIdx = [...(msg.toolCalls ?? [])].findLastIndex((tc) => tc.state === "running");
                return msg.toolCalls?.map((tc, tci) =>
                  renderToolCall(tc, tci === lastRunningIdx),
                );
              })()}
            </div>
          ) : null}
        </>
      );
    }

    return (msg.toolCalls?.length ?? 0) > 0 ? (
      <div className="space-y-2">
        {(() => {
          const lastRunningIdx = [...(msg.toolCalls ?? [])].findLastIndex((tc) => tc.state === "running");
          return msg.toolCalls?.map((tc, tci) =>
            renderToolCall(tc, tci === lastRunningIdx),
          );
        })()}
      </div>
    ) : null;
  };

  const renderPartsAssistant = (msg: ChatMessage, isLast: boolean) => {
    const parts = msg.parts ?? [];
    const groups: (
      | { type: "cot"; blocks: ContentBlock[]; hasThinking: boolean }
      | { type: "text"; block: Extract<ContentBlock, { type: "text" }> }
      | { type: "tools"; blocks: ContentBlock[] }
      | { type: "data"; block: Extract<ContentBlock, { type: "data" }> }
    )[] = [];
    let cotBuffer: ContentBlock[] = [];

    const flushCot = () => {
      if (cotBuffer.length === 0) return;
      const hasThinking = cotBuffer.some(
        (b) => b.type === "thinking" && b.text.trim(),
      );
      if (hasThinking) {
        groups.push({ type: "cot", blocks: cotBuffer, hasThinking: true });
      } else {
        groups.push({ type: "tools", blocks: cotBuffer });
      }
      cotBuffer = [];
    };

    for (const part of parts) {
      if (part.type === "thinking" || part.type === "tool_call") {
        cotBuffer.push(part);
      } else if (part.type === "text") {
        flushCot();
        groups.push({ type: "text", block: part });
      } else if (part.type === "data") {
        flushCot();
        groups.push({ type: "data", block: part });
      }
    }
    flushCot();

    return groups.map((group, gi) => {
      if (group.type === "text") {
        return group.block.text ? (
          <MessageResponse key={`text-${gi}`}>
            {group.block.text}
          </MessageResponse>
        ) : null;
      }

      if (group.type === "data") {
        return <DataPartView key={`data-${gi}`} part={group.block} />;
      }

      if (group.type === "tools") {
        const lastRunningIdx = group.blocks.findLastIndex(
          (b) => b.type === "tool_call" && b.toolCall.state === "running",
        );
        return (
          <div key={`tools-${gi}`} className="space-y-2">
            {group.blocks.map((block, bi) => {
              if (block.type === "tool_call") {
                return renderToolCall(block.toolCall, bi === lastRunningIdx);
              }
              return null;
            })}
          </div>
        );
      }

      const hasContent = group.blocks.length > 0;
      const isActive = isLast && isLoading;
      const lastRunningTool = isActive
        ? [...group.blocks]
            .reverse()
            .find(
              (b) =>
                b.type === "tool_call" &&
                b.toolCall.state === "running",
            )
        : undefined;
      const activeLabel = lastRunningTool
        ? getToolTitle(
            lastRunningTool.toolCall.name,
            lastRunningTool.toolCall.arguments ?? {},
          )
        : isActive
          ? "正在思考..."
          : "思考过程";
      return (
        <ChainOfThought key={`cot-${gi}`} defaultOpen={isActive || hasContent}>
          <ChainOfThoughtHeader>
            {isActive ? (
              <Shimmer duration={1}>{activeLabel}</Shimmer>
            ) : (
              <span>思考过程</span>
            )}
          </ChainOfThoughtHeader>
          <ChainOfThoughtContent>
            {(() => {
              const lastRunningIdx = group.blocks.findLastIndex(
                (b) => b.type === "tool_call" && b.toolCall.state === "running",
              );
              return group.blocks.map((block, bi) => {
                if (block.type === "thinking") {
                  return block.text.trim() ? (
                    <ChainOfThoughtStep
                      key={`thinking-${gi}-${bi}`}
                      label={block.text}
                      status={isActive ? "active" : "complete"}
                    />
                  ) : null;
                }
                if (block.type === "tool_call") {
                  return (
                    <div key={`tool-${gi}-${bi}`}>
                      {renderToolCall(block.toolCall, bi === lastRunningIdx)}
                    </div>
                  );
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
              {msg.role === "assistant" &&
                (msg.parts
                  ? renderPartsAssistant(msg, isLast)
                  : renderLegacyAssistant(msg, isLast))}
              {!msg.parts && msg.content ? (
                <MessageResponse>{msg.content}</MessageResponse>
              ) : null}
            </MessageContent>
          </Message>
        );
      })}
    </>
  );
});

const ChatStreamBody = memo(function ChatStreamBody({
  sessionId,
  isLoading,
  messages,
  onResolveDeleteConfirmation,
  onResolveGitConfirmation,
  personaState,
}: {
  sessionId: string | null;
  isLoading: boolean;
  messages: ChatMessage[];
  onResolveDeleteConfirmation: (toolCallId: string, approved: boolean) => void;
  onResolveGitConfirmation: (
    toolCallId: string,
    type: "commit" | "tag",
    approved: boolean,
  ) => void;
  personaState: PersonaState;
}) {
  if (messages.length === 0) {
    return <EmptyStateWithPersona state={personaState} />;
  }

  return (
    <>
      <MessageList
        sessionId={sessionId}
        isLoading={isLoading}
        messages={messages}
        onResolveDeleteConfirmation={onResolveDeleteConfirmation}
        onResolveGitConfirmation={onResolveGitConfirmation}
      />
      <PersonaRail state={personaState} />
    </>
  );
});

export function ChatPanel({
  sessionId,
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
  onResolveDeleteConfirmation,
  onResolveGitConfirmation,
  onModelChange,
  elementAttachments = [],
  onRemoveElementAttachment,
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
      type: "file" as const,
      filename: file.name,
      mediaType: file.type,
      url: URL.createObjectURL(file),
    }));
    setAttachmentFiles((prev) => [...prev, ...newFiles]);
  }, []);

  const handleRemoveAttachment = useCallback((id: string) => {
    setAttachmentFiles((prev) => {
      const found = prev.find((f) => f.id === id);
      if (found && "url" in found && found.url) URL.revokeObjectURL(found.url);
      return prev.filter((f) => f.id !== id);
    });
  }, []);

  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) {
        handleAddFiles(e.target.files);
        e.target.value = "";
      }
    },
    [handleAddFiles],
  );

  const selectedModel =
    modelOptions.find((m) => m.id === model) ?? modelOptions[0];

  const lastAssistantMessage = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") {
        return messages[i];
      }
    }
    return null;
  }, [messages]);

  const hasDraftInput = isFocused && input.trim().length > 0;
  const hasStreamingResponse =
    isLoading && Boolean(lastAssistantMessage?.content?.trim());
  const hasCompletedConversation = messages.length > 0 && !isLoading;

  const personaState = useMemo<PersonaState>(() => {
    if (hasStreamingResponse) {
      return "speaking";
    }
    if (isLoading) {
      return "thinking";
    }
    if (hasDraftInput) {
      return "listening";
    }
    if (hasCompletedConversation) {
      return "idle";
    }
    if (!isFocused) {
      return "asleep";
    }
    return "idle";
  }, [
    hasCompletedConversation,
    hasDraftInput,
    hasStreamingResponse,
    isFocused,
    isLoading,
  ]);

  return (
    <div className="h-full flex flex-col min-w-0 border-r">
      <Conversation className="flex-1">
        <ConversationContent className="gap-4 pb-4 max-w-[720px] mx-auto w-full">
          <ChatStreamBody
            sessionId={sessionId}
            isLoading={isLoading}
            messages={messages}
            onResolveDeleteConfirmation={onResolveDeleteConfirmation}
            onResolveGitConfirmation={onResolveGitConfirmation}
            personaState={personaState}
          />
        </ConversationContent>
      </Conversation>

      <div className="shrink-0 border-t bg-background">
        <div className="max-w-[720px] mx-auto w-full">
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

              {elementAttachments.length > 0 && (
                <div className="pb-2 flex flex-wrap gap-1.5">
                  {elementAttachments.map((el) => (
                    <div
                      key={el.id}
                      className="group relative flex h-16 items-center gap-1.5 rounded-md border border-border px-1.5 py-1 transition-all hover:bg-accent/50"
                    >
                      <div className="size-12 shrink-0 overflow-hidden rounded bg-white">
                        <iframe
                          srcDoc={el.html}
                          title={el.selector}
                          sandbox="allow-scripts"
                          className="pointer-events-none size-full origin-top-left scale-[0.25]"
                          style={{ width: "400%", height: "400%" }}
                        />
                      </div>
                      <div className="flex flex-col gap-0.5 min-w-0 max-w-[140px]">
                        <span className="truncate text-[10px] font-mono text-muted-foreground leading-tight">
                          {el.selector}
                        </span>
                        {el.sourceUrl && (
                          <span className="truncate text-[9px] text-muted-foreground/60 leading-tight">
                            {el.sourceUrl.replace(/^https?:\/\//, "")}
                          </span>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => onRemoveElementAttachment?.(el.id)}
                        className="absolute -top-1.5 -right-1.5 flex size-4 shrink-0 items-center justify-center rounded-full bg-background border shadow-sm opacity-0 transition-opacity group-hover:opacity-100 hover:bg-destructive/10"
                      >
                        <XIcon className="size-2.5 text-muted-foreground hover:text-destructive" />
                      </button>
                    </div>
                  ))}
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

                  <ModelSelector
                    open={isModelSelectorOpen}
                    onOpenChange={setIsModelSelectorOpen}
                  >
                    <ModelSelectorTrigger asChild>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 gap-1.5 px-2 text-xs font-medium text-muted-foreground hover:text-foreground"
                      >
                        <ModelSelectorLogo
                          provider={selectedModel?.provider ?? "openrouter"}
                        />
                        <ModelSelectorName>
                          {selectedModel?.label ?? selectedModel?.name ?? "选择模型"}
                        </ModelSelectorName>
                      </Button>
                    </ModelSelectorTrigger>
                    <ModelSelectorContent title="选择模型">
                      <ModelSelectorInput placeholder="搜索模型..." />
                      <ModelSelectorList>
                        <ModelSelectorEmpty>未找到模型</ModelSelectorEmpty>
                        <ModelSelectorGroup heading="可用模型">
                          {modelOptions.map((m) => (
                            <ModelSelectorItem
                              key={m.id}
                              onSelect={() => {
                                onModelChange(m.id);
                                setIsModelSelectorOpen(false);
                              }}
                              className="gap-2"
                            >
                              <ModelSelectorLogo provider={m.provider} />
                              <ModelSelectorName>{m.label ?? m.name}</ModelSelectorName>
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
                    disabled={!input.trim() && elementAttachments.length === 0}
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
    </div>
  );
}
