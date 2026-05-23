import { ContextViewer } from "@/components/app/context-viewer";
import { CodeChangePanel } from "@/components/app/code-change-panel";
import { ChatComposerEditor } from "@/components/app/chat-composer-editor";
import { cn } from "@/lib/utils";
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
import { Sources, SourceTag } from "@/components/ai-elements/sources";
import {
  InlineCitation,
  InlineCitationCard,
  InlineCitationCardBody,
  InlineCitationCardTrigger,
  InlineCitationCarousel,
  InlineCitationCarouselContent,
  InlineCitationCarouselHeader,
  InlineCitationCarouselIndex,
  InlineCitationCarouselItem,
  InlineCitationCarouselNext,
  InlineCitationCarouselPrev,
  InlineCitationSource,
} from "@/components/ai-elements/inline-citation";
import { DeployConnectForm } from "@/components/ai-elements/deploy-connect-form";
import {
  Plan,
  PlanAction,
  PlanContent,
  PlanDescription,
  PlanFooter,
  PlanHeader,
  PlanTitle,
  PlanTrigger,
} from "@/components/ai-elements/plan";
import {
  PlanQuestionsQuiz,
  type Question as PlanQuizQuestion,
  type QuizSubmission,
} from "@/components/ai-elements/plan-questions-quiz";
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getShikiLanguage } from "@/lib/app-utils";
import {
  buildPlanDraftMarkdown,
  normalizePlanDraft,
  parseStreamingPlanDraft,
  resolvePlanDraftTitle,
} from "@/lib/plan-draft";
import { getFileIcon } from "@/lib/file-icons";
import type {
  AgentMode,
  ChatMessage,
  CodeChangeRecord,
  CompletionActionKey,
  ContentBlock,
  FileTreeNode,
  ModelOption,
  PlanStep,
  SessionContextPayload,
  SkillSummary,
  ToolCallRecord,
} from "@/lib/app-types";
import {
  ChevronDown,
  ChevronRight,
  BarChart3Icon,
  DatabaseIcon,
  FileCodeIcon,
  FileSearchIcon,
  FileText,
  FolderOpenIcon,
  GitBranch,
  GitCommitHorizontal,
  GlobeIcon,
  Tag,
  ListChecks,
  PencilIcon,
  PlusIcon,
  PaperclipIcon,
  Square,
  SearchIcon,
  TerminalIcon,
  Trash2Icon,
  XIcon,
  LightbulbIcon,
  Code2Icon,
  RocketIcon,
  Copy,
  RotateCcw,
  Archive,
  Eye,
  Loader2,
  Check,
  MessageSquareIcon,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type React from "react";
import { memo, useMemo, useRef, useState, useCallback, useEffect, useId, useLayoutEffect } from "react";

type ElementAttachment = {
  id: string;
  selector: string;
  html: string;
  sourceUrl?: string;
};

type ChatPanelProps = {
  sessionId: string | null;
  contextData: SessionContextPayload | null;
  codeChanges: CodeChangeRecord[];
  messages: ChatMessage[];
  isContextLoading: boolean;
  isContextOpen: boolean;
  input: string;
  isLoading: boolean;
  model: string | null;
  reasoningEffort: string | null;
  modelOptions: ModelOption[];
  availableSkills: SkillSummary[];
  fileTree: FileTreeNode[];
  onContextOpenChange: (open: boolean) => void;
  onInputChange: (value: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => void;
  onSendMessage: () => void;
  onStopMessage: () => void;
  onResolveDeleteConfirmation: (toolCallId: string, approved: boolean) => void;
  onResolveGitConfirmation: (
    toolCallId: string,
    type: "commit" | "tag",
    approved: boolean,
  ) => void;
  onResolveConnectInput?: (toolCallId: string, values: Record<string, string>) => void;
  onResolvePlanQuestionsInput?: (
    toolCallId: string,
    answers: QuizSubmission,
  ) => void | Promise<void>;
  onViewPlan?: (title: string, markdown: string) => void;
  agentMode: AgentMode;
  onAgentModeChange: (mode: AgentMode) => void;
  onModelChange: (modelId: string) => void;
  onReasoningEffortChange: (reasoningEffort: string) => void;
  onCompletionAction?: (action: CompletionActionKey, message: ChatMessage) => void;
  activeCompletionAction?: { messageId: string; action: CompletionActionKey } | null;
  elementAttachments?: ElementAttachment[];
  onRemoveElementAttachment?: (id: string) => void;
};

type MentionSuggestion = {
  id: string;
  kind: "workspace" | "file" | "change" | "element" | "skill";
  label: string;
  description: string;
  insertValue: string;
};

type MentionRenderSegment =
  | { type: "text"; value: string }
  | {
      type: "mention";
      token: string;
      value: string;
      label: string;
      kind?: MentionSuggestion["kind"];
    };

type ComposerSelectionOffsets = {
  start: number;
  end: number;
};

const TOOL_ICONS: Record<string, React.ReactNode> = {
  connect: <GlobeIcon className="size-4" />,
  search_web: <SearchIcon className="size-4" />,
  fetch_url_content: <GlobeIcon className="size-4" />,
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
  ask_plan_questions: <FileText className="size-4" />,
  save_plan: <FileText className="size-4" />,
  create_task: <ListChecks className="size-4" />,
  get_task_status: <ListChecks className="size-4" />,
  finish_task: <ListChecks className="size-4" />,
};

const TOOL_TITLES: Record<string, (args: Record<string, unknown>) => string> = {
  connect: () => "连接部署目标",
  search_web: (args) => {
    const q = (args.query as string)?.trim();
    return q ? `搜索: ${q}` : "网络搜索";
  },
  fetch_url_content: (args) => {
    const urls = args.urls as string[] | undefined;
    if (urls?.length) return `抓取网页 (${urls.length})`;
    return "抓取网页内容";
  },
  list_file: (args) => {
    const f = ((args.filename || args.path || args.file_path) as string)?.split(/[\\/]/).pop();
    return f ? `正在搜索项目列表 ${f}` : "正在搜索项目列表";
  },
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
  ask_plan_questions: () => "正在生成澄清问题",
  save_plan: () => "正在设计计划",
  create_task: () => "正在创建任务",
  get_task_status: () => "正在读取任务状态",
  finish_task: () => "正在完成步骤",
};

function getToolTitle(name: string, args: Record<string, unknown>): string {
  const fn = TOOL_TITLES[name];
  return fn ? fn(args) : "执行中";
}

function getToolIcon(name: string) {
  return TOOL_ICONS[name] ?? <FileCodeIcon className="size-4" />;
}

type PlanQuestionSource = ToolCallRecord["inputRequest"]["questions"][number];

function extractBalancedQuestionObjects(input: string): string[] {
  const questionsKeyIndex = input.indexOf('"questions"');
  if (questionsKeyIndex < 0) return [];
  const arrayStartIndex = input.indexOf("[", questionsKeyIndex);
  if (arrayStartIndex < 0) return [];

  const objects: string[] = [];
  let depth = 0;
  let objectStart = -1;
  let inString = false;
  let escaping = false;

  for (let index = arrayStartIndex + 1; index < input.length; index += 1) {
    const char = input[index];
    if (inString) {
      if (escaping) {
        escaping = false;
      } else if (char === "\\") {
        escaping = true;
      } else if (char === '"') {
        inString = false;
      }
      continue;
    }

    if (char === '"') {
      inString = true;
      continue;
    }

    if (char === "{") {
      if (depth === 0) {
        objectStart = index;
      }
      depth += 1;
      continue;
    }

    if (char === "}") {
      depth -= 1;
      if (depth === 0 && objectStart >= 0) {
        objects.push(input.slice(objectStart, index + 1));
        objectStart = -1;
      }
    }
  }

  return objects;
}

function extractJsonStringField(input: string, field: string) {
  const match = input.match(new RegExp(`"${field}"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"`));
  if (!match) return undefined;
  try {
    return JSON.parse(`"${match[1]}"`) as string;
  } catch {
    return match[1];
  }
}

function normalizePlanQuestions(
  rawQuestions: unknown,
): PlanQuizQuestion[] | undefined {
  if (!Array.isArray(rawQuestions)) return undefined;

  const questions = rawQuestions
    .map((question, index) => {
      if (!question || typeof question !== "object") return null;
      const record = question as Record<string, unknown>;
      const rawType = String(record.type ?? "");
      const title = String(record.prompt ?? "").trim();
      if (!title) return null;

      return {
        id: String(record.id ?? `question_${index + 1}`),
        type:
          rawType === "single_choice"
            ? "single"
            : rawType === "multi_choice"
              ? "multiple"
              : "text",
        title,
        description: undefined,
        placeholder:
          typeof record.placeholder === "string" ? record.placeholder : undefined,
        required:
          typeof record.required === "boolean" ? record.required : undefined,
        includeOtherOption: true,
        options: Array.isArray(record.options)
          ? record.options
              .map((option, optionIndex) => {
                if (!option || typeof option !== "object") return null;
                const optionRecord = option as Record<string, unknown>;
                const label = String(optionRecord.label ?? "").trim();
                if (!label) return null;
                return {
                  id: String(optionRecord.id ?? `option_${index + 1}_${optionIndex + 1}`),
                  label,
                };
              })
              .filter((option): option is NonNullable<typeof option> => option !== null)
          : undefined,
      } satisfies PlanQuizQuestion;
    })
    .filter((question): question is NonNullable<typeof question> => question !== null);

  return questions.length > 0 ? questions : undefined;
}

function parseStreamingPlanQuestions(streamedInput?: string) {
  if (!streamedInput?.trim()) return undefined;

  try {
    const parsed = JSON.parse(streamedInput) as Record<string, unknown>;
    return {
      title:
        typeof parsed.title === "string" && parsed.title.trim()
          ? parsed.title
          : undefined,
      message:
        typeof parsed.message === "string" && parsed.message.trim()
          ? parsed.message
          : undefined,
      questions: normalizePlanQuestions(parsed.questions),
    };
  } catch {
    const partialQuestions = normalizePlanQuestions(
      extractBalancedQuestionObjects(streamedInput).map((item) => {
        try {
          return JSON.parse(item) as PlanQuestionSource;
        } catch {
          return null;
        }
      }).filter((item): item is PlanQuestionSource => item !== null),
    );

    return {
      title: extractJsonStringField(streamedInput, "title"),
      message: extractJsonStringField(streamedInput, "message"),
      questions: partialQuestions,
    };
  }
}

type CitationInfo = { url: string; title?: string; snippet?: string };

const CITATION_RE = /\[\[(https?:\/\/[^\]]+)\]\]/g;
const LEADING_CITATION_RE = /^\[\[(https?:\/\/[^\]]+)\]\]/;
const INLINE_CITATION_SEPARATOR_RE = /^[\t ]+/;

function collectCitations(parts: ContentBlock[]): Map<string, CitationInfo> {
  const map = new Map<string, CitationInfo>();
  for (const part of parts) {
    if (part.type !== "tool_call") continue;
    const tc = part.toolCall;
    const output = tc.output;
    if (!output || typeof output !== "object") continue;
    if (tc.name === "search_web") {
      const results = (output as Record<string, unknown>)?.results as Array<{ url?: string; title?: string; snippet?: string }> | undefined;
      results?.forEach((r) => {
        if (r.url) map.set(r.url, { url: r.url, title: r.title, snippet: r.snippet });
      });
    } else if (tc.name === "fetch_url_content") {
      const docs = (output as Record<string, unknown>)?.documents as Array<{ url?: string; title?: string; content?: string }> | undefined;
      docs?.forEach((d) => {
        if (d.url) map.set(d.url, { url: d.url, title: d.title, snippet: d.content ? d.content.slice(0, 200) : undefined });
      });
    }
  }
  return map;
}

function escapeHtmlAttribute(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function getCitationDisplayTitle(url: string, citations: Map<string, CitationInfo>) {
  const info = citations.get(url);
  if (info?.title?.trim()) {
    return info.title.trim();
  }

  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function serializeCitationMarkdown(
  text: string,
  citations: Map<string, CitationInfo>,
) {
  let markdown = "";
  let lastIndex = 0;
  const re = new RegExp(CITATION_RE.source, "g");
  let match: RegExpExecArray | null;

  while ((match = re.exec(text)) !== null) {
    markdown += text.slice(lastIndex, match.index);

    const sources = [match[1]];
    let groupEnd = re.lastIndex;

    while (groupEnd < text.length) {
      const separatorMatch = INLINE_CITATION_SEPARATOR_RE.exec(
        text.slice(groupEnd),
      );
      if (!separatorMatch) {
        break;
      }

      const nextCitationStart = groupEnd + separatorMatch[0].length;
      const nextCitationMatch = LEADING_CITATION_RE.exec(
        text.slice(nextCitationStart),
      );
      if (!nextCitationMatch) {
        break;
      }

      sources.push(nextCitationMatch[1]);
      groupEnd = nextCitationStart + nextCitationMatch[0].length;
    }

    markdown += `<citation urls="${escapeHtmlAttribute(
      JSON.stringify(sources),
    )}" title="${escapeHtmlAttribute(
      getCitationDisplayTitle(sources[0], citations),
    )}"></citation>`;
    lastIndex = groupEnd;
    re.lastIndex = groupEnd;
  }

  markdown += text.slice(lastIndex);
  return markdown;
}

function renderCitationBadge(sources: string[], citations: Map<string, CitationInfo>) {
  const primaryUrl = sources[0];
  if (!primaryUrl) {
    return null;
  }

  const triggerLabel = getCitationDisplayTitle(primaryUrl, citations);
  const defaultTitle = (() => {
    try {
      return new URL(primaryUrl).hostname;
    } catch {
      return primaryUrl;
    }
  })();

  return (
    <InlineCitation>
      <InlineCitationCard>
        <InlineCitationCardTrigger
          extraCount={sources.length - 1}
          href={primaryUrl}
          label={triggerLabel}
          sources={sources}
        />
        <InlineCitationCardBody>
          <InlineCitationCarousel>
            <InlineCitationCarouselHeader>
              <InlineCitationCarouselPrev />
              <InlineCitationCarouselIndex />
              <InlineCitationCarouselNext />
            </InlineCitationCarouselHeader>
            <InlineCitationCarouselContent>
              {sources.map((url) => {
                const info = citations.get(url);
                return (
                  <InlineCitationCarouselItem key={url}>
                    <InlineCitationSource
                      title={info?.title || defaultTitle}
                      url={url}
                      description={info?.snippet}
                    />
                  </InlineCitationCarouselItem>
                );
              })}
            </InlineCitationCarouselContent>
          </InlineCitationCarousel>
        </InlineCitationCardBody>
      </InlineCitationCard>
    </InlineCitation>
  );
}

function renderCitationMessage(
  text: string,
  citations: Map<string, CitationInfo>,
  options?: {
    className?: string;
    isAnimating?: boolean;
    key?: string;
  },
) {
  const markdown = serializeCitationMarkdown(text, citations);

  return (
    <MessageResponse
      allowedTags={{ citation: ["title", "urls"] }}
      className={options?.className}
      components={{
        citation: ({ urls }) => {
          if (typeof urls !== "string") {
            return null;
          }
          try {
            const parsed = JSON.parse(urls);
            return Array.isArray(parsed) &&
              parsed.every((item) => typeof item === "string")
              ? renderCitationBadge(parsed, citations)
              : null;
          } catch {
            return null;
          }
        },
      }}
      isAnimating={options?.isAnimating}
      key={options?.key}
      literalTagContent={["citation"]}
    >
      {markdown}
    </MessageResponse>
  );
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
  onResolveConnectInput,
  onResolvePlanQuestionsInput,
  onViewPlan,
  replaceCompletedPlanQuestionsWithLoading = false,
}: {
  toolCall: ToolCallRecord;
  sessionId: string | null;
  onResolveDeleteConfirmation: (toolCallId: string, approved: boolean) => void;
  onResolveGitConfirmation: (
    toolCallId: string,
    type: "commit" | "tag",
    approved: boolean,
  ) => void;
  onResolveConnectInput?: (toolCallId: string, values: Record<string, string>) => void;
  onResolvePlanQuestionsInput?: (
    toolCallId: string,
    answers: QuizSubmission,
  ) => void | Promise<void>;
  onViewPlan?: (title: string, markdown: string) => void;
  replaceCompletedPlanQuestionsWithLoading?: boolean;
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
  const asTaskObject = (
    value: unknown,
  ): { title?: string; summary?: string; steps?: Array<Record<string, unknown>> } | undefined =>
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as { title?: string; summary?: string; steps?: Array<Record<string, unknown>> })
      : undefined;
  const normalizeQueueStatus = (
    status: unknown,
  ): "pending" | "running" | "completed" | "error" => {
    if (status === "completed") return "completed";
    if (status === "error") return "error";
    if (status === "running") return "running";
    return "pending";
  };
  const renderStepQueue = (steps: Array<Record<string, unknown>> | undefined) => {
    if (!steps || steps.length === 0) return null;
    return (
      <Queue isStreaming={isStreaming}>
        {steps.map((step, index) => (
          <QueueItem
            key={String(step.id ?? index)}
            status={normalizeQueueStatus(step.status)}
          >
            <QueueItemTitle>{String(step.title ?? `Step ${index + 1}`)}</QueueItemTitle>
            <QueueItemDescription>
              {String(step.summary ?? step.description ?? "")}
            </QueueItemDescription>
          </QueueItem>
        ))}
      </Queue>
    );
  };

  if (toolCall.name === "connect") {
    if (toolCall.inputRequest && toolCall.state === "input-requested") {
      return (
        <DeployConnectForm
          inputRequest={toolCall.inputRequest}
          sessionId={sessionId}
          onSubmit={(values) => onResolveConnectInput?.(toolCall.id, values)}
          disabled={toolCall.state !== "input-requested"}
        />
      );
    }
    const connectOutput =
      output && typeof output === "object" && !Array.isArray(output)
        ? (output as Record<string, unknown>)
        : undefined;
    const message = typeof connectOutput?.message === "string" ? connectOutput.message : undefined;
    const sessionIdOut = typeof connectOutput?.session_id === "string" ? connectOutput.session_id : undefined;
    const rootPath = typeof connectOutput?.root_path === "string" ? connectOutput.root_path : undefined;
    const displayName = typeof connectOutput?.display_name === "string" ? connectOutput.display_name : undefined;
    const hostOut = typeof connectOutput?.host === "string" ? connectOutput.host : undefined;
    const usernameOut = typeof connectOutput?.username === "string" ? connectOutput.username : undefined;
    return (
      <div className="space-y-2">
        {message && (
          <div className="rounded-md bg-muted/50 p-2 text-xs">
            <p className="font-medium text-muted-foreground mb-1">结果</p>
            <p>{message}</p>
          </div>
        )}
        {sessionIdOut && (
          <div className="flex items-center gap-2 rounded-md bg-emerald-500/10 px-3 py-2 text-xs">
            <span className="text-emerald-600 font-medium">已连接</span>
            <span className="text-muted-foreground">
              {hostOut ? `${usernameOut ? `${usernameOut}@` : ''}${hostOut}` : (displayName || rootPath || sessionIdOut)}
            </span>
          </div>
        )}
      </div>
    );
  }

  const streamingPlanPreview = parseStreamingPlanQuestions(toolCall.streamedInput);
  const questions =
    normalizePlanQuestions(toolCall.inputRequest?.questions) ??
    normalizePlanQuestions(args.questions) ??
    streamingPlanPreview?.questions;
  const isPlanQuestionsTool =
    toolCall.inputRequest?.kind === "plan_questions" ||
    toolCall.name === "ask_plan_questions" ||
    Array.isArray(args.questions) ||
    Boolean(streamingPlanPreview?.title || streamingPlanPreview?.message || streamingPlanPreview?.questions?.length);

  if (isPlanQuestionsTool) {
    if (toolCall.state === "input-requested") {
      return (
        <PlanQuestionsQuiz
          questions={questions ?? []}
          embedded
          streaming={isStreaming}
          disabled={false}
          title={
            toolCall.inputRequest?.title ||
            (typeof args.title === "string" ? args.title : undefined) ||
            streamingPlanPreview?.title
          }
          description={
            toolCall.inputRequest?.message ||
            (typeof args.message === "string" ? args.message : undefined) ||
            streamingPlanPreview?.message
          }
          submitted={false}
          onSubmit={(answers) =>
            onResolvePlanQuestionsInput?.(toolCall.id, answers)
          }
        />
      );
    }

    if (replaceCompletedPlanQuestionsWithLoading) {
      return (
        <Button size="sm" variant="outline" disabled>
          <Loader2 className="mr-2 size-3.5 animate-spin" />
          正在生成计划中
        </Button>
      );
    }

    return null;
  }

  if (toolCall.name === "save_plan") {
    const planDraft = {
      ...parseStreamingPlanDraft(toolCall.streamedInput),
      ...normalizePlanDraft(args),
    };
    const planTitle = resolvePlanDraftTitle(
      planDraft,
      isStreaming ? "正在设计计划" : "计划草案",
    );
    const detailMd = buildPlanDraftMarkdown(planDraft, planTitle);

    return (
      <PlanDraftCard
        title={planTitle}
        summary={planDraft.summary ?? ""}
        keySteps={planDraft.keySteps ?? []}
        detailMarkdown={detailMd}
        onViewPlan={onViewPlan}
        isStreaming={isStreaming}
      />
    );
  }

  if (toolCall.name === "create_task") {
    const taskPayload =
      output && typeof output === "object" && !Array.isArray(output)
        ? (output as Record<string, unknown>)
        : undefined;
    const task = asTaskObject(taskPayload?.task);
    const stepIds = Array.isArray(taskPayload?.step_ids) ? taskPayload.step_ids : [];

    return (
      <div className="space-y-3 rounded-md bg-muted/40 p-3 text-xs">
        <div>
          <p className="font-medium text-foreground">
            {String(task?.title ?? args.title ?? "Task")}
          </p>
          <p className="mt-1 text-muted-foreground">
            {String(task?.summary ?? args.summary ?? "")}
          </p>
        </div>
        {renderStepQueue(task?.steps)}
        {stepIds.length > 0 ? (
          <p className="text-muted-foreground">已创建 {stepIds.length} 个 steps。</p>
        ) : null}
      </div>
    );
  }

  if (toolCall.name === "get_task_status" || toolCall.name === "finish_task") {
    const taskPayload =
      output && typeof output === "object" && !Array.isArray(output)
        ? (output as Record<string, unknown>)
        : undefined;
    const activeTask = asTaskObject(taskPayload?.active_task);
    const planSteps = Array.isArray(taskPayload?.planSteps)
      ? (taskPayload.planSteps as Array<Record<string, unknown>>)
      : undefined;
    const nextStepId =
      typeof taskPayload?.next_step_id === "string"
        ? taskPayload.next_step_id
        : undefined;

    return (
      <div className="space-y-3 rounded-md bg-muted/40 p-3 text-xs">
        <div>
          <p className="font-medium text-foreground">
            {String(activeTask?.title ?? "当前 Task 状态")}
          </p>
          <p className="mt-1 text-muted-foreground">
            {String(activeTask?.summary ?? "")}
          </p>
        </div>
        {activeTask?.steps ? renderStepQueue(activeTask.steps) : renderStepQueue(planSteps)}
        {toolCall.name === "finish_task" ? (
          <p className="text-muted-foreground">
            {nextStepId ? `已推进到下一步：${nextStepId}` : "当前 task 已完成。"}
          </p>
        ) : null}
      </div>
    );
  }

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
          language={filename ? (getShikiLanguage(filename) as never) : "text"}
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
          language={filename ? (getShikiLanguage(filename) as never) : "text"}
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

  if (toolCall.name === "list_file") {
    return (
      <div className="space-y-2">
        {filename && (
          <TaskItemFile>
            <FolderOpenIcon className="size-3" />
            {filename}
          </TaskItemFile>
        )}
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

  if (toolCall.name === "search_web") {
    const results = output && typeof output === "object"
      ? (output as Record<string, unknown>)?.results as Array<{ rank?: number; title?: string; url?: string; snippet?: string; source?: string; publishedAt?: string }> | undefined
      : undefined;
    if (results && results.length > 0) {
      return (
        <Sources title="搜索的内容">
          {results.map((r, i) => (
            <SourceTag key={i} href={r.url ?? "#"} title={r.title || r.source} />
          ))}
        </Sources>
      );
    }
    return <p className="text-xs text-muted-foreground">无搜索结果</p>;
  }

  if (toolCall.name === "fetch_url_content") {
    const documents = output && typeof output === "object"
      ? (output as Record<string, unknown>)?.documents as Array<{ url?: string; title?: string; content?: string }> | undefined
      : undefined;
    if (documents && documents.length > 0) {
      return (
        <Sources title="抓取的内容">
          {documents.map((d, i) => (
            <SourceTag key={i} href={d.url ?? "#"} title={d.title} />
          ))}
        </Sources>
      );
    }
    return <p className="text-xs text-muted-foreground">无抓取结果</p>;
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

function PlanDraftCard({
  title,
  summary,
  keySteps,
  detailMarkdown,
  onViewPlan,
  isStreaming = false,
}: {
  title: string;
  summary: string;
  keySteps: string[];
  detailMarkdown: string;
  onViewPlan?: (title: string, markdown: string) => void;
  isStreaming?: boolean;
}) {
  return (
    <Plan defaultOpen={false} isStreaming={isStreaming}>
      <PlanHeader>
        <div>
          <div className="mb-4 flex items-center gap-2">
            <FileText className="size-4" />
            <PlanTitle>{title || "计划草案"}</PlanTitle>
          </div>
          {summary && <PlanDescription>{summary}</PlanDescription>}
        </div>
        <PlanTrigger />
      </PlanHeader>
      <PlanContent>
        <div className="py-1 text-sm text-muted-foreground">
          {summary && <p>{summary}</p>}
          {keySteps.length > 0 && (
            <ul className="mt-2 list-inside list-disc space-y-0.5">
              {keySteps.map((step, idx) => (
                <li key={idx}>{step}</li>
              ))}
            </ul>
          )}
        </div>
      </PlanContent>
      <PlanFooter className="justify-end">
        <PlanAction>
          {isStreaming ? (
            <Button size="sm" variant="outline" disabled>
              <Loader2 className="mr-1.5 size-3.5 animate-spin" />
              生成中
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={() => onViewPlan?.(title || "计划草案", detailMarkdown)}
            >
              <Eye className="mr-1.5 size-3.5" />
              查看详情
            </Button>
          )}
        </PlanAction>
      </PlanFooter>
    </Plan>
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
        <span className="flex-1 text-left">步骤</span>
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
  onViewPlan,
}: {
  part: Extract<ContentBlock, { type: "data" }>;
  onViewPlan?: (title: string, markdown: string) => void;
}) {
  const data = part.data;

  if (part.dataType === "data-session-state") {
    const agentType = data?.agentType as string | undefined;
    if (!agentType) return null;

    const modeConfig: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
      plan: {
        label: "计划",
        icon: <LightbulbIcon className="size-3.5" />,
        color: "text-amber-600",
      },
      coding: {
        label: "编码",
        icon: <Code2Icon className="size-3.5" />,
        color: "text-blue-600",
      },
      deploy: {
        label: "部署",
        icon: <RocketIcon className="size-3.5" />,
        color: "text-emerald-600",
      },
    };

    const config = modeConfig[agentType];
    if (!config) return null;

    return (
      <div className="flex items-center gap-2 rounded-md bg-muted/30 px-3 py-2 text-xs">
        <span className={config.color}>{config.icon}</span>
        <span className="font-medium text-foreground">开始 {config.label} 环节</span>
      </div>
    );
  }

  if (part.dataType === "data-plan-questions") return null;

  if (
    part.dataType === "data-plan-draft" &&
    data &&
    typeof data === "object" &&
    !Array.isArray(data)
  ) {
    const draft = data as {
      title?: unknown;
      summary?: unknown;
      overview?: unknown;
      keySteps?: unknown;
      markdown?: unknown;
    };
    const draftTitle = typeof draft.title === "string" ? draft.title : "";
    const draftSummary = typeof draft.summary === "string" ? draft.summary : "";
    const draftKeySteps = Array.isArray(draft.keySteps)
      ? draft.keySteps.filter((s): s is string => typeof s === "string")
      : [] as string[];
    const draftMarkdown = typeof draft.markdown === "string" ? draft.markdown : "";

    const detailMd = draftMarkdown || [
      `# ${draftTitle}`,
      "",
      draftSummary,
      "",
      typeof draft.overview === "string" ? `## 概览\n\n${draft.overview}\n` : "",
      draftKeySteps.length > 0 ? ["## 关键步骤", "", ...draftKeySteps.map((s, i) => `${i + 1}. ${s}`)].join("\n") : "",
    ].join("\n");

    return <PlanDraftCard title={draftTitle} summary={draftSummary} keySteps={draftKeySteps} detailMarkdown={detailMd} onViewPlan={onViewPlan} />;
  }

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
const CONTEXT_COMPRESSION_USAGE_THRESHOLD = 0.7;

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

const COMPLETION_ACTIONS = [
  { icon: Copy, label: "复制回答", key: "copy" },
  { icon: Eye, label: "查看修改", key: "view-changes" },
  { icon: Archive, label: "压缩会话", key: "compress" },
  { icon: GitBranch, label: "派生分支", key: "fork" },
  { icon: RotateCcw, label: "还原对话", key: "restore" },
  { icon: RocketIcon, label: "发布版本", key: "publish" },
] as const;

const DEFAULT_DISABLED_COMPLETION_ACTIONS: Record<CompletionActionKey, boolean> = {
  copy: false,
  "view-changes": true,
  compress: false,
  fork: false,
  restore: false,
  publish: true,
};

const CompletionActionToolbar = memo(function CompletionActionToolbar({
  onAction,
  disabledActions,
}: {
  onAction?: (action: CompletionActionKey) => void;
  disabledActions?: Partial<Record<CompletionActionKey, boolean>>;
}) {
  return (
    <div className="flex items-center gap-0.5 py-1">
      <TooltipProvider delayDuration={300}>
        {COMPLETION_ACTIONS.map((action) => (
          <Tooltip key={action.key}>
            <TooltipTrigger asChild>
              <Button
                size="icon-sm"
                variant="ghost"
                disabled={Boolean(
                  DEFAULT_DISABLED_COMPLETION_ACTIONS[action.key] ||
                    disabledActions?.[action.key] ||
                    !onAction,
                )}
                className={cn(
                  "shrink-0",
                  DEFAULT_DISABLED_COMPLETION_ACTIONS[action.key] || disabledActions?.[action.key] || !onAction
                    ? "text-muted-foreground/40"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/60",
                )}
                onClick={() => onAction?.(action.key)}
              >
                <action.icon className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top" sideOffset={4}>
              {action.label}
            </TooltipContent>
          </Tooltip>
        ))}
      </TooltipProvider>
    </div>
  );
});

const CompressStatusLine = memo(function CompressStatusLine({
  status,
}: {
  status: "compressing" | "compressed";
}) {
  const isDone = status === "compressed";

  return (
    <div className="flex items-center gap-2 py-1.5 text-xs text-muted-foreground">
      <div className="h-px flex-1 bg-border" />
      <AnimatePresence mode="wait">
        {!isDone ? (
          <motion.span
            key="compressing"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.2 }}
            className="flex shrink-0 items-center gap-1.5"
          >
            <Loader2 className="size-3 animate-spin" />
            正在压缩
          </motion.span>
        ) : (
          <motion.span
            key="compressed"
            initial={{ y: 14, opacity: 0, rotateX: -90 }}
            animate={{ y: 0, opacity: 1, rotateX: 0 }}
            transition={{ type: "spring", stiffness: 500, damping: 30 }}
            className="flex shrink-0 items-center gap-1.5 text-emerald-600 dark:text-emerald-400"
            style={{ perspective: 200 }}
          >
            <Check className="size-3" />
            已压缩上下文
          </motion.span>
        )}
      </AnimatePresence>
      <div className="h-px flex-1 bg-border" />
    </div>
  );
});

const PersonaRail = memo(function PersonaRail({
  state,
  isCompleted,
  message,
  onCompletionAction,
  disabledActions,
}: {
  state: PersonaState;
  isCompleted: boolean;
  message?: ChatMessage | null;
  onCompletionAction?: (action: CompletionActionKey, message: ChatMessage) => void;
  disabledActions?: Partial<Record<CompletionActionKey, boolean>>;
}) {
  const [isHovered, setIsHovered] = useState(false);
  const activeState: PersonaState = isCompleted && isHovered ? "asleep" : state;

  return (
    <motion.div
      layout
      className="flex items-center gap-2 py-2"
      onMouseEnter={() => isCompleted && setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <PersonaShell state={activeState} />
      <AnimatePresence>
        {isCompleted && isHovered && (
          <motion.div
            initial={{ opacity: 0, width: 0, overflow: "hidden" }}
            animate={{ opacity: 1, width: "auto" }}
            exit={{ opacity: 0, width: 0, overflow: "hidden" }}
            transition={{ type: "spring", stiffness: 400, damping: 30 }}
            className="flex items-center gap-0.5"
          >
            <CompletionActionToolbar
              disabledActions={disabledActions}
              onAction={
                message && onCompletionAction
                  ? (action) => onCompletionAction(action, message)
                  : undefined
              }
            />
          </motion.div>
        )}
      </AnimatePresence>
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
  onResolveConnectInput,
  onResolvePlanQuestionsInput,
  onViewPlan,
  onCompletionAction,
  activeCompletionAction,
  compressedMessageIds,
  canCompress,
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
  onResolveConnectInput?: (toolCallId: string, values: Record<string, string>) => void;
  onResolvePlanQuestionsInput?: (
    toolCallId: string,
    answers: QuizSubmission,
  ) => void | Promise<void>;
  onViewPlan?: (title: string, markdown: string) => void;
  onCompletionAction?: (action: CompletionActionKey, message: ChatMessage) => void;
  activeCompletionAction?: { messageId: string; action: CompletionActionKey } | null;
  compressedMessageIds: Set<string>;
  canCompress: boolean;
}) {
  const [taskOpenState, setTaskOpenState] = useState<Record<string, boolean>>(
    {},
  );

  useEffect(() => {
    setTaskOpenState((prev) => {
      let changed = false;
      const next = { ...prev };

      for (const message of messages) {
        for (const toolCall of message.toolCalls ?? []) {
          const shouldAutoCollapse =
            toolCall.name === "save_plan" &&
            (toolCall.state === "completed" ||
              toolCall.state === "output-available");
          if (shouldAutoCollapse && next[toolCall.id] !== false) {
            next[toolCall.id] = false;
            changed = true;
          }
        }
      }

      return changed ? next : prev;
    });
  }, [messages]);

  const statusLabelMap: Record<ToolCallRecord["state"], string> = {
    running: "执行中",
    completed: "已完成",
    error: "出错",
    "approval-requested": "待确认",
    "output-available": "已完成",
    "output-denied": "已拒绝",
    "input-requested": "待填写",
  };

  const renderToolCall = (
    tc: ToolCallRecord,
    isLastRunning: boolean,
    options?: {
      replaceCompletedPlanQuestionsWithLoading?: boolean;
    },
  ) => {
    const statusLabel = statusLabelMap[tc.state] ?? "执行中";
    const shouldOpen =
      isLastRunning ||
      tc.state === "input-requested" ||
      tc.name.startsWith("git_") ||
      tc.name === "connect" ||
      tc.name === "ask_plan_questions" ||
      tc.inputRequest?.kind === "plan_questions";
    const toolTitle = `${getToolTitle(tc.name, tc.arguments ?? {})} · ${statusLabel}`;
    const hasControlledOpen = Object.prototype.hasOwnProperty.call(
      taskOpenState,
      tc.id,
    );

    return (
      <Task
        key={tc.id}
        defaultOpen={shouldOpen}
        {...(hasControlledOpen
          ? {
              open: taskOpenState[tc.id],
              onOpenChange: (open: boolean) =>
                setTaskOpenState((prev) => ({ ...prev, [tc.id]: open })),
            }
          : {})}
      >
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
              onResolveConnectInput={onResolveConnectInput}
              onResolvePlanQuestionsInput={onResolvePlanQuestionsInput}
              onViewPlan={onViewPlan}
              replaceCompletedPlanQuestionsWithLoading={
                options?.replaceCompletedPlanQuestionsWithLoading
              }
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
                  label={<MessageResponse>{thoughtText}</MessageResponse>}
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
    const citations = collectCitations(parts);
    const groups: (
      | { type: "cot"; blocks: ContentBlock[]; hasThinking: boolean }
      | { type: "text"; block: Extract<ContentBlock, { type: "text" }> }
      | { type: "tools"; blocks: ContentBlock[] }
      | { type: "data"; block: Extract<ContentBlock, { type: "data" }> }
    )[] = [];
    let cotBuffer: ContentBlock[] = [];
    let lastAgentType = "";

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
        if (part.dataType === "data-session-state") {
          const agentType = (part.data as Record<string, unknown> | undefined)?.agentType as string | undefined;
          if (agentType && agentType !== lastAgentType) {
            lastAgentType = agentType;
            cotBuffer.push(part);
          }
        } else {
          flushCot();
          groups.push({ type: "data", block: part });
        }
      }
    }
    flushCot();

    const activeCotGroupIdx =
      isLast && isLoading && groups[groups.length - 1]?.type === "cot"
        ? groups.length - 1
        : -1;

    return groups.map((group, gi) => {
      if (group.type === "text") {
        const isStreamingText = isLast && isLoading && gi === groups.length - 1;
        return group.block.text
          ? renderCitationMessage(group.block.text, citations, {
              className: isStreamingText ? "streaming-tail-fade" : undefined,
              isAnimating: isStreamingText,
              key: `text-${gi}`,
            })
          : null;
      }

      if (group.type === "data") {
        return <DataPartView key={`data-${gi}`} part={group.block} onViewPlan={onViewPlan} />;
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
      const isActive = gi === activeCotGroupIdx;
      const hasAutoOpenTool = group.blocks.some(
        (block) =>
          block.type === "tool_call" &&
          ["running", "input-requested", "approval-requested"].includes(
            block.toolCall.state,
          ),
      );
      const autoCloseDelay = group.blocks.some(
        (block) =>
          block.type === "tool_call" &&
          block.toolCall.inputRequest?.kind === "plan_questions",
      )
        ? 3500
        : 0;
      const lastRunningTool = isActive
        ? [...group.blocks]
            .reverse()
            .find(
              (b) =>
                b.type === "tool_call" &&
                b.toolCall.state === "running",
            )
        : undefined;
      const isDraftingPlan = group.blocks.some(
        (block) =>
          block.type === "tool_call" &&
          block.toolCall.name === "save_plan" &&
          block.toolCall.state === "running",
      );
      const activeLabel = lastRunningTool
        ? getToolTitle(
            lastRunningTool.toolCall.name,
            lastRunningTool.toolCall.arguments ?? {},
          )
        : isActive
          ? "正在思考..."
          : "思考过程";
      return (
        <ChainOfThought
          key={`cot-${gi}`}
          defaultOpen={isActive || hasContent}
          autoOpen={isActive || hasAutoOpenTool}
          autoCloseDelay={autoCloseDelay}
        >
          <ChainOfThoughtHeader>
            {isActive ? (
              <Shimmer duration={1}>{activeLabel}</Shimmer>
            ) : (
              <span>思考过程</span>
            )}
          </ChainOfThoughtHeader>
          <ChainOfThoughtContent>
            {(() => {
              const lastRunningIdx = isActive
                ? group.blocks.findLastIndex(
                    (b) =>
                      (b.type === "tool_call" && b.toolCall.state === "running") ||
                      b.type === "thinking",
                  )
                : -1;
              return group.blocks.map((block, bi) => {
                if (block.type === "thinking") {
                  return block.text.trim() ? (
                    <ChainOfThoughtStep
                      key={`thinking-${gi}-${bi}`}
                      label={renderCitationMessage(block.text, citations)}
                      status={bi === lastRunningIdx && isActive ? "active" : "complete"}
                    />
                  ) : null;
                }
                if (block.type === "tool_call") {
                  return (
                    <div key={`tool-${gi}-${bi}`}>
                      {renderToolCall(block.toolCall, bi === lastRunningIdx, {
                        replaceCompletedPlanQuestionsWithLoading:
                          isDraftingPlan &&
                          (block.toolCall.inputRequest?.kind ===
                            "plan_questions" ||
                            block.toolCall.name === "ask_plan_questions"),
                      })}
                    </div>
                  );
                }
                if (block.type === "data" && block.dataType === "data-session-state") {
                  return (
                    <div key={`session-state-${gi}-${bi}`}>
                      <DataPartView part={block} />
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

  const lastAssistantIdx = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return i;
    }
    return -1;
  }, [messages]);

  return (
    <>
      {messages.map((msg, idx) => {
        const isLast = idx === messages.length - 1;
        const isLastAssistant = idx === lastAssistantIdx;
        const showInlineActions = msg.role === "assistant" && !isLastAssistant;
        const isCompressing = activeCompletionAction?.action === "compress" && activeCompletionAction.messageId === msg.id;
        const isCompressed = compressedMessageIds.has(msg.id ?? "");
        const compressStatus: "compressing" | "compressed" | null = isCompressing ? "compressing" : isCompressed ? "compressed" : null;
        return (
          <Message key={msg.id || idx} from={msg.role} data-message-id={msg.id}>
            <MessageContent>
              {msg.role === "assistant" &&
                (msg.parts
                  ? renderPartsAssistant(msg, isLast)
                  : renderLegacyAssistant(msg, isLast))}
              {!msg.parts && msg.content ? (
                renderCitationMessage(msg.content, new Map(), {
                  className: isLast && isLoading ? "streaming-tail-fade" : undefined,
                  isAnimating: isLast && isLoading,
                })
              ) : null}
            </MessageContent>
            {msg.role === "assistant" && compressStatus && (
              <CompressStatusLine status={compressStatus} />
            )}
            {showInlineActions && (
              <CompletionActionToolbar
                disabledActions={{
                  copy: !msg.content.trim(),
                  compress: isLoading || Boolean(activeCompletionAction) || isCompressed || !canCompress,
                  fork: isLoading || Boolean(activeCompletionAction),
                  restore: isLoading || Boolean(activeCompletionAction),
                }}
                onAction={
                  onCompletionAction
                    ? (action) => onCompletionAction(action, msg)
                    : undefined
                }
              />
            )}
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
  onResolveConnectInput,
  onResolvePlanQuestionsInput,
  onViewPlan,
  personaState,
  onCompletionAction,
  activeCompletionAction,
  canCompress,
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
  onResolveConnectInput?: (toolCallId: string, values: Record<string, string>) => void;
  onResolvePlanQuestionsInput?: (
    toolCallId: string,
    answers: QuizSubmission,
  ) => void | Promise<void>;
  onViewPlan?: (title: string, markdown: string) => void;
  personaState: PersonaState;
  onCompletionAction?: (action: CompletionActionKey, message: ChatMessage) => void;
  activeCompletionAction?: { messageId: string; action: CompletionActionKey } | null;
  canCompress: boolean;
}) {
  const [compressedMessageIds, setCompressedMessageIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!activeCompletionAction) return;
    if (activeCompletionAction.action !== "compress") return;
    if (compressedMessageIds.has(activeCompletionAction.messageId)) return;
    const timer = setTimeout(() => {
      setCompressedMessageIds((prev) => {
        const next = new Set(prev);
        next.add(activeCompletionAction.messageId);
        return next;
      });
    }, 1200);
    return () => clearTimeout(timer);
  }, [activeCompletionAction, compressedMessageIds]);

  if (messages.length === 0) {
    return <EmptyStateWithPersona state={personaState} />;
  }

  const lastAssistantMessage =
    [...messages].reverse().find((message) => message.role === "assistant") ?? null;

  const lastCompressStatus: "compressing" | "compressed" | null =
    activeCompletionAction?.action === "compress" && activeCompletionAction.messageId === lastAssistantMessage?.id
      ? "compressing"
      : lastAssistantMessage?.id && compressedMessageIds.has(lastAssistantMessage.id)
        ? "compressed"
        : null;

  return (
    <>
      <MessageList
        sessionId={sessionId}
        isLoading={isLoading}
        messages={messages}
        onResolveDeleteConfirmation={onResolveDeleteConfirmation}
        onResolveGitConfirmation={onResolveGitConfirmation}
        onResolveConnectInput={onResolveConnectInput}
        onResolvePlanQuestionsInput={onResolvePlanQuestionsInput}
        onViewPlan={onViewPlan}
        onCompletionAction={onCompletionAction}
        activeCompletionAction={activeCompletionAction}
        compressedMessageIds={compressedMessageIds}
        canCompress={canCompress}
      />
      <PersonaRail
        state={personaState}
        isCompleted={!isLoading && messages.length > 0}
        message={lastAssistantMessage}
        onCompletionAction={onCompletionAction}
        disabledActions={{
          copy: !lastAssistantMessage?.content?.trim(),
          compress: isLoading || Boolean(activeCompletionAction) || Boolean(lastCompressStatus) || !canCompress,
          fork: isLoading || Boolean(activeCompletionAction),
          restore: true,
        }}
      />
    </>
  );
});

function useCompletionNotification(isLoading: boolean, hasMessages: boolean) {
  const wasLoading = useRef(false);

  useEffect(() => {
    if (typeof Notification === "undefined") return;
    if (Notification.permission === "default") {
      Notification.requestPermission();
    }
  }, []);

  useEffect(() => {
    if (wasLoading.current && !isLoading && hasMessages) {
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        try {
          new Notification("SuperCode", {
            body: "生成完成",
            tag: "supercode-completion",
          });
        } catch {
          // Ignore notification failures when the browser blocks system notices.
        }
      }
    }
    wasLoading.current = isLoading;
  }, [isLoading, hasMessages]);
}

const MessageOutline = memo(function MessageOutline({
  messages,
  isLoading,
}: {
  messages: ChatMessage[];
  isLoading: boolean;
}) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const [tooltipRect, setTooltipRect] = useState<{ top: number; right: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const getPreview = useCallback((msg: ChatMessage): string => {
    const raw = msg.parts
      ?.filter((p) => p.type === "text")
      .map((p) => (p as { type: "text"; text: string }).text)
      .join("") ?? msg.content ?? "";
    const clean = raw.replace(/[#*`\n]/g, " ").replace(/\s+/g, " ").trim();
    return clean.length > 28 ? clean.slice(0, 28) + "…" : clean || (msg.role === "user" ? "用户消息" : "AI 回复");
  }, []);

  const scrollToMessage = useCallback((msgId: string) => {
    const el = document.querySelector(`[data-message-id="${msgId}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, []);

  const handleHover = useCallback((idx: number) => {
    setHoveredIdx(idx);
    const bar = containerRef.current?.querySelector(`[data-outline-idx="${idx}"]`);
    if (bar) {
      const barRect = bar.getBoundingClientRect();
      const containerRect = containerRef.current!.getBoundingClientRect();
      setTooltipRect({
        top: barRect.top + barRect.height / 2,
        right: window.innerWidth - containerRect.left + 6,
      });
    }
  }, []);

  const handleLeave = useCallback(() => {
    setHoveredIdx(null);
    setTooltipRect(null);
  }, []);

  const lineLengths = useMemo(() => {
    return messages.map((msg) => {
      const textLen = (msg.parts
        ?.filter((p) => p.type === "text")
        .map((p) => (p as { type: "text"; text: string }).text)
        .join("") ?? msg.content ?? "").length;
      if (msg.role === "user") return 10;
      if (textLen === 0) return 6;
      if (textLen < 20) return 8;
      if (textLen < 80) return 12;
      if (textLen < 200) return 16;
      return 20;
    });
  }, [messages]);

  if (messages.length === 0) return null;

  return (
    <>
      <div
        ref={containerRef}
        className="flex flex-col gap-[9px] items-end select-none"
      >
        {messages.map((msg, idx) => {
          const isLast = idx === messages.length - 1;
          const isStreaming = isLast && isLoading && msg.role === "assistant";
          const isActive = isStreaming || (isLast && !isLoading);
          const isHovered = hoveredIdx === idx;
          const w = lineLengths[idx];

          return (
            <div
              key={msg.id || idx}
              data-outline-idx={idx}
              className="cursor-pointer"
              onMouseEnter={() => handleHover(idx)}
              onMouseLeave={handleLeave}
              onClick={() => msg.id && scrollToMessage(msg.id)}
            >
              <motion.div
                className={cn(
                  "h-[3px] rounded-full transition-colors duration-200",
                  isActive
                    ? "bg-foreground/90"
                    : isHovered
                      ? "bg-foreground/50"
                      : msg.role === "user"
                        ? "bg-foreground/20"
                        : "bg-foreground/12",
                )}
                animate={isStreaming ? { opacity: [1, 0.4, 1] } : undefined}
                transition={isStreaming ? { duration: 2, repeat: Infinity, ease: "easeInOut" } : { duration: 0.15 }}
                style={{ width: w * (isActive ? 1.3 : isHovered ? 1.15 : 1) }}
              />
            </div>
          );
        })}
      </div>

      <AnimatePresence>
        {hoveredIdx !== null && tooltipRect && messages[hoveredIdx] && (
          <motion.div
            initial={{ opacity: 0, x: 4 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 4 }}
            transition={{ duration: 0.12, ease: "easeOut" }}
            className="fixed z-[9999] pointer-events-none"
            style={{
              top: tooltipRect.top,
              right: tooltipRect.right,
              transform: "translateY(-50%)",
            }}
          >
            <div
              className="flex items-center gap-1.5 rounded px-2 py-1 text-[11px] whitespace-nowrap shadow-sm"
              style={{
                background: "oklch(0.22 0 0 / 0.92)",
                color: "oklch(0.82 0 0)",
                backdropFilter: "blur(8px)",
              }}
            >
              <span
                className="size-1.5 rounded-full shrink-0"
                style={{
                  background: messages[hoveredIdx].role === "user"
                    ? "oklch(0.65 0.15 250)"
                    : "oklch(0.7 0.14 160)",
                }}
              />
              <span className="truncate max-w-[160px]">
                {getPreview(messages[hoveredIdx])}
              </span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
});

function getPathLeaf(input: string) {
  const normalized = input.replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).pop() ?? input;
}

function getActiveMentionAtCaret(value: string, caret: number) {
  const safeCaret = Math.max(0, Math.min(caret, value.length));
  const mentionToken = findMentionTokenAtCaret(value, safeCaret);
  if (mentionToken && safeCaret > mentionToken.start && safeCaret <= mentionToken.end) {
    return null;
  }
  const mentionStart = value.lastIndexOf("@", safeCaret - 1);
  if (mentionStart < 0) return null;

  const previousChar = value[mentionStart - 1];
  if (previousChar && !/[\s([{"'`]/.test(previousChar)) {
    return null;
  }

  const query = value.slice(mentionStart + 1, safeCaret);
  if (/[\s@]/.test(query)) {
    return null;
  }

  return {
    start: mentionStart,
    end: safeCaret,
    query,
  };
}

const MENTION_KIND_LABELS: Record<MentionSuggestion["kind"], string> = {
  workspace: "工作区",
  file: "文件",
  change: "改动",
  element: "元素",
  skill: "技能",
};

function getMentionSuggestionIcon(kind: MentionSuggestion["kind"]) {
  switch (kind) {
    case "workspace":
      return <FolderOpenIcon className="size-3.5" />;
    case "file":
      return <FileCodeIcon className="size-3.5" />;
    case "change":
      return <PencilIcon className="size-3.5" />;
    case "element":
      return <GlobeIcon className="size-3.5" />;
    case "skill":
      return <LightbulbIcon className="size-3.5" />;
    default:
      return <MessageSquareIcon className="size-3.5" />;
  }
}

function formatMentionToken(value: string) {
  return `@[${value.replaceAll("]", "\\]")}]`;
}

function decodeMentionTokenValue(value: string) {
  return value.replace(/\\\]/g, "]");
}

function findMentionTokenAtCaret(value: string, caret: number) {
  const mentionTokenRe = /@\[((?:\\.|[^\]])*)\]/g;
  let match: RegExpExecArray | null;

  while ((match = mentionTokenRe.exec(value)) !== null) {
    const token = match[0];
    const start = match.index;
    const end = start + token.length;
    if (caret >= start && caret <= end) {
      return {
        start,
        end,
        token,
        value: decodeMentionTokenValue(match[1] ?? ""),
      };
    }
  }

  return null;
}

function getComposerNodeLength(node: Node): number {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent?.length ?? 0;
  }

  if (node instanceof HTMLElement) {
    const mentionToken = node.dataset.mentionToken;
    if (mentionToken) {
      return mentionToken.length;
    }

    if (node.tagName === "BR") {
      return 1;
    }
  }

  return Array.from(node.childNodes).reduce(
    (total, child) => total + getComposerNodeLength(child),
    0,
  );
}

function getComposerPointOffset(root: HTMLElement, container: Node, offset: number): number {
  if (container === root) {
    return Array.from(root.childNodes)
      .slice(0, offset)
      .reduce((total, child) => total + getComposerNodeLength(child), 0);
  }

  let total = 0;
  for (const child of Array.from(root.childNodes)) {
    if (child === container) {
      if (child.nodeType === Node.TEXT_NODE) {
        return total + offset;
      }

      if (child instanceof HTMLElement && child.dataset.mentionToken) {
        return total + (offset > 0 ? child.dataset.mentionToken.length : 0);
      }
    }

    if (child.contains?.(container)) {
      if (child instanceof HTMLElement && child.dataset.mentionToken) {
        return total + (offset > 0 ? child.dataset.mentionToken.length : 0);
      }

      return total + getComposerPointOffset(child as HTMLElement, container, offset);
    }

    total += getComposerNodeLength(child);
  }

  return total;
}

function getComposerSelectionOffsets(
  root: HTMLElement,
): ComposerSelectionOffsets | null {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;

  const range = selection.getRangeAt(0);
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) {
    return null;
  }

  return {
    start: getComposerPointOffset(root, range.startContainer, range.startOffset),
    end: getComposerPointOffset(root, range.endContainer, range.endOffset),
  };
}

function resolveComposerOffsetToPoint(root: HTMLElement, offset: number) {
  let total = 0;
  const children = Array.from(root.childNodes);

  for (let index = 0; index < children.length; index += 1) {
    const child = children[index];
    const childLength = getComposerNodeLength(child);

    if (offset <= total + childLength) {
      if (child.nodeType === Node.TEXT_NODE) {
        return {
          container: child,
          offset: Math.max(0, Math.min(offset - total, childLength)),
        };
      }

      if (child instanceof HTMLElement && child.dataset.mentionToken) {
        return offset <= total + childLength / 2
          ? { container: root, offset: index }
          : { container: root, offset: index + 1 };
      }
    }

    total += childLength;
  }

  return { container: root, offset: root.childNodes.length };
}

function setComposerSelectionOffsets(
  root: HTMLElement,
  start: number,
  end = start,
) {
  const selection = window.getSelection();
  if (!selection) return;

  const range = document.createRange();
  const startPoint = resolveComposerOffsetToPoint(root, start);
  const endPoint = resolveComposerOffsetToPoint(root, end);
  range.setStart(startPoint.container, startPoint.offset);
  range.setEnd(endPoint.container, endPoint.offset);
  selection.removeAllRanges();
  selection.addRange(range);
}

function serializeComposerContent(root: HTMLElement) {
  return Array.from(root.childNodes)
    .map((child) => {
      if (child.nodeType === Node.TEXT_NODE) {
        return child.textContent?.replace(/\u00a0/g, " ") ?? "";
      }

      if (child instanceof HTMLElement) {
        if (child.dataset.mentionToken) {
          return child.dataset.mentionToken;
        }

        if (child.tagName === "BR") {
          return "\n";
        }
      }

      return child.textContent?.replace(/\u00a0/g, " ") ?? "";
    })
    .join("");
}

function buildMentionRenderSegments(
  value: string,
  suggestionByToken: Map<string, MentionSuggestion>,
): MentionRenderSegment[] {
  const segments: MentionRenderSegment[] = [];
  const mentionTokenRe = /@\[((?:\\.|[^\]])*)\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = mentionTokenRe.exec(value)) !== null) {
    if (match.index > lastIndex) {
      segments.push({
        type: "text",
        value: value.slice(lastIndex, match.index),
      });
    }

    const rawValue = match[1] ?? "";
    const tokenValue = match[0];
    const mentionValue = decodeMentionTokenValue(rawValue);
    const suggestion = suggestionByToken.get(tokenValue);
    segments.push({
      type: "mention",
      token: tokenValue,
      value: mentionValue,
      label: suggestion?.label ?? getPathLeaf(mentionValue),
      kind: suggestion?.kind,
    });
    lastIndex = match.index + tokenValue.length;
  }

  if (lastIndex < value.length) {
    segments.push({
      type: "text",
      value: value.slice(lastIndex),
    });
  }

  return segments;
}

const MENTION_KIND_ICON_COLORS: Record<MentionSuggestion["kind"], string> = {
  workspace: "text-amber-600 bg-amber-50 dark:text-amber-400 dark:bg-amber-950/60",
  file: "text-blue-600 bg-blue-50 dark:text-blue-400 dark:bg-blue-950/60",
  change: "text-emerald-600 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-950/60",
  element: "text-violet-600 bg-violet-50 dark:text-violet-400 dark:bg-violet-950/60",
};

const MENTION_KIND_BADGE_STYLES: Record<MentionSuggestion["kind"], string> = {
  workspace:
    "border-amber-200/80 bg-amber-50/95 text-amber-950 dark:border-amber-900/80 dark:bg-amber-950/70 dark:text-amber-100",
  file:
    "border-blue-200/80 bg-blue-50/95 text-blue-950 dark:border-blue-900/80 dark:bg-blue-950/70 dark:text-blue-100",
  change:
    "border-emerald-200/80 bg-emerald-50/95 text-emerald-950 dark:border-emerald-900/80 dark:bg-emerald-950/70 dark:text-emerald-100",
  element:
    "border-violet-200/80 bg-violet-50/95 text-violet-950 dark:border-violet-900/80 dark:bg-violet-950/70 dark:text-violet-100",
};

function focusComposerAtOffset(composerId: string, start: number, end = start) {
  window.requestAnimationFrame(() => {
    const composer = document.getElementById(composerId);
    if (!(composer instanceof HTMLElement)) return;
    composer.focus({ preventScroll: true });
    setComposerSelectionOffsets(composer, start, end);
  });
}

function normalizeMentionCaret(value: string, caret: number) {
  const token = findMentionTokenAtCaret(value, caret);
  if (!token) return caret;
  if (caret === token.start || caret === token.end) return caret;
  return caret - token.start < token.end - caret ? token.start : token.end;
}

export function ChatPanel({
  sessionId,
  contextData,
  codeChanges,
  messages,
  isContextLoading,
  isContextOpen,
  input,
  isLoading,
  model,
  reasoningEffort,
  modelOptions,
  availableSkills,
  fileTree,
  onContextOpenChange,
  onInputChange,
  onKeyDown,
  onSendMessage,
  onStopMessage,
  onResolveDeleteConfirmation,
  onResolveGitConfirmation,
  onResolveConnectInput,
  onResolvePlanQuestionsInput,
  onViewPlan,
  agentMode,
  onAgentModeChange,
  onModelChange,
  onReasoningEffortChange,
  onCompletionAction,
  activeCompletionAction,
  elementAttachments = [],
  onRemoveElementAttachment,
}: ChatPanelProps) {
  const planSteps = contextData?.planSteps ?? [];
  const composerRef = useRef<HTMLDivElement>(null);
  const [isFocused, setIsFocused] = useState(false);
  const [attachmentFiles, setAttachmentFiles] = useState<AttachmentData[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerInputRef = useRef<HTMLDivElement>(null);
  const composerInputId = useId();
  const [isModelSelectorOpen, setIsModelSelectorOpen] = useState(false);
  const [composerSelection, setComposerSelection] = useState<ComposerSelectionOffsets>({
    start: 0,
    end: 0,
  });
  const [mentionNavigation, setMentionNavigation] = useState<{
    key: string | null;
    index: number;
  }>({
    key: null,
    index: 0,
  });
  const [dismissedMentionKey, setDismissedMentionKey] = useState<string | null>(null);

  useCompletionNotification(isLoading, messages.length > 0);

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
  const selectedReasoningEffort = reasoningEffort ?? "default";
  const mentionSuggestions = useMemo(() => {
    const items: MentionSuggestion[] = [];
    const seen = new Set<string>();
    const pushSuggestion = (suggestion: MentionSuggestion) => {
      const normalizedKey = suggestion.insertValue.toLowerCase();
      if (seen.has(normalizedKey)) return;
      seen.add(normalizedKey);
      items.push(suggestion);
    };

    for (const skill of availableSkills) {
      pushSuggestion({
        id: `skill:${skill.id}`,
        kind: "skill",
        label: skill.name,
        description: `${skill.scope === "builtin" ? "内置" : "工作区"} skill · ${skill.description}`,
        insertValue: formatMentionToken(`skill:${skill.id}`),
      });
    }

    if (contextData?.workspace) {
      pushSuggestion({
        id: `workspace:${contextData.workspace}`,
        kind: "workspace",
        label: getPathLeaf(contextData.workspace),
        description: contextData.workspace,
        insertValue: formatMentionToken(contextData.workspace),
      });
    }

    for (const filePath of contextData?.openFiles ?? []) {
      pushSuggestion({
        id: `file:${filePath}`,
        kind: "file",
        label: getPathLeaf(filePath),
        description: filePath,
        insertValue: formatMentionToken(filePath),
      });
    }

    const flattenFileTree = (nodes: FileTreeNode[]) => {
      for (const node of nodes) {
        if (node.type === "file") {
          pushSuggestion({
            id: `file:${node.path}`,
            kind: "file",
            label: node.name,
            description: node.path,
            insertValue: formatMentionToken(node.path),
          });
        }
        if (node.children) {
          flattenFileTree(node.children);
        }
      }
    };
    flattenFileTree(fileTree);

    const recentChangePaths = [
      ...codeChanges.map((change) => change.path),
      ...(contextData?.recentCodeChanges ?? []).map((change) => change.path),
    ];
    for (const path of recentChangePaths) {
      if (!path) continue;
      pushSuggestion({
        id: `change:${path}`,
        kind: "change",
        label: getPathLeaf(path),
        description: `最近改动 · ${path}`,
        insertValue: formatMentionToken(path),
      });
    }

    for (const element of elementAttachments) {
      pushSuggestion({
        id: `element:${element.id}`,
        kind: "element",
        label: element.selector,
        description: element.sourceUrl
          ? `${element.sourceUrl.replace(/^https?:\/\//, "")}`
          : "已附加页面元素",
        insertValue: formatMentionToken(element.selector),
      });
    }

    return items;
  }, [availableSkills, codeChanges, contextData, elementAttachments, fileTree]);
  const mentionSuggestionByToken = useMemo(() => {
    const map = new Map<string, MentionSuggestion>();
    for (const suggestion of mentionSuggestions) {
      map.set(suggestion.insertValue, suggestion);
    }
    return map;
  }, [mentionSuggestions]);
  const mentionRenderSegments = useMemo(
    () => buildMentionRenderSegments(input, mentionSuggestionByToken),
    [input, mentionSuggestionByToken],
  );

  const activeMention = useMemo(
    () => getActiveMentionAtCaret(input, composerSelection.start),
    [composerSelection.start, input],
  );
  const activeMentionKey = activeMention
    ? `${activeMention.start}:${activeMention.query}`
    : null;
  const filteredMentionSuggestions = useMemo(() => {
    if (!activeMention) return [];

    const normalizedQuery = activeMention.query.trim().toLowerCase();
    if (!normalizedQuery) {
      return mentionSuggestions;
    }

    return mentionSuggestions.filter((suggestion) =>
      [
        suggestion.label,
        suggestion.description,
        suggestion.insertValue,
      ].some((value) => value.toLowerCase().includes(normalizedQuery)),
    );
  }, [activeMention, mentionSuggestions]);
  const mentionSelectedIndex =
    activeMentionKey && mentionNavigation.key === activeMentionKey
      ? Math.min(
          mentionNavigation.index,
          Math.max(filteredMentionSuggestions.length - 1, 0),
        )
      : 0;
  const isMentionMenuOpen =
    Boolean(activeMention) && dismissedMentionKey !== activeMentionKey;

  const lastAssistantMessage = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") {
        return messages[i];
      }
    }
    return null;
  }, [messages]);
  const canCompress =
    ((contextData?.estimatedTokens ?? 0) / Math.max(contextData?.maxTokens ?? 1, 1)) >=
    CONTEXT_COMPRESSION_USAGE_THRESHOLD;

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

  useEffect(() => {
    if (!isMentionMenuOpen) return;
    const frame = window.requestAnimationFrame(() => {
      composerInputRef.current?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isMentionMenuOpen]);

  useLayoutEffect(() => {
    const composer = composerInputRef.current;
    if (!composer || document.activeElement !== composer) return;
    setComposerSelectionOffsets(
      composer,
      composerSelection.start,
      composerSelection.end,
    );
  }, [composerSelection, input]);

  const syncComposerSelection = useCallback((target: HTMLElement) => {
    const selection = getComposerSelectionOffsets(target);
    if (!selection) return;
    const normalizedStart = normalizeMentionCaret(input, selection.start);
    const normalizedEnd = normalizeMentionCaret(input, selection.end);
    if (
      normalizedStart !== selection.start ||
      normalizedEnd !== selection.end
    ) {
      setComposerSelectionOffsets(target, normalizedStart, normalizedEnd);
    }
    setComposerSelection({
      start: normalizedStart,
      end: normalizedEnd,
    });
  }, [input]);

  const buildMentionInsertion = useCallback(
    (suggestion: MentionSuggestion) => {
      if (!activeMention) return null;

      const nextValue =
        input.slice(0, activeMention.start) +
        `${suggestion.insertValue} ` +
        input.slice(activeMention.end);
      const nextCaret = activeMention.start + suggestion.insertValue.length + 1;

      return { nextValue, nextCaret };
    },
    [activeMention, input],
  );

  const removeMentionToken = useCallback(
    (start: number, end: number) => {
      const nextValue = input.slice(0, start) + input.slice(end);
      onInputChange(nextValue);
      setComposerSelection({ start, end: start });
      setDismissedMentionKey(null);
      focusComposerAtOffset(composerInputId, start);
    },
    [composerInputId, input, onInputChange],
  );

  const handleComposerInput = useCallback(
    (e: React.FormEvent<HTMLDivElement>) => {
      const nextValue = serializeComposerContent(e.currentTarget);
      const selection = getComposerSelectionOffsets(e.currentTarget);
      onInputChange(nextValue);
      setComposerSelection({
        start: normalizeMentionCaret(nextValue, selection?.start ?? nextValue.length),
        end: normalizeMentionCaret(nextValue, selection?.end ?? nextValue.length),
      });
    },
    [onInputChange],
  );

  const handleComposerPaste = useCallback(
    (e: React.ClipboardEvent<HTMLDivElement>) => {
      e.preventDefault();
      const pastedText = e.clipboardData.getData("text/plain");
      if (!pastedText) return;

      const nextValue =
        input.slice(0, composerSelection.start) +
        pastedText +
        input.slice(composerSelection.end);
      const nextCaret = composerSelection.start + pastedText.length;
      onInputChange(nextValue);
      setComposerSelection({ start: nextCaret, end: nextCaret });
      focusComposerAtOffset(composerInputId, nextCaret);
    },
    [composerInputId, composerSelection.end, composerSelection.start, input, onInputChange],
  );

  const handleComposerKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      const caretStart = composerSelection.start;
      const caretEnd = composerSelection.end;
      const suggestionCount = filteredMentionSuggestions.length;

      if (caretStart === caretEnd) {
        if (e.key === "Backspace") {
          const activeToken =
            findMentionTokenAtCaret(input, caretStart) ??
            findMentionTokenAtCaret(input, Math.max(caretStart - 1, 0));
          if (activeToken && caretStart > activeToken.start) {
            e.preventDefault();
            removeMentionToken(activeToken.start, activeToken.end);
            return;
          }
        }

        if (e.key === "Delete") {
          const activeToken = findMentionTokenAtCaret(input, caretStart);
          if (activeToken && caretStart < activeToken.end) {
            e.preventDefault();
            removeMentionToken(activeToken.start, activeToken.end);
            return;
          }
        }
      }

      if (isMentionMenuOpen && suggestionCount > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setMentionNavigation((prev) => ({
            key: activeMentionKey,
            index:
              prev.key === activeMentionKey
                ? (prev.index + 1) % suggestionCount
                : 0,
          }));
          return;
        }

        if (e.key === "ArrowUp") {
          e.preventDefault();
          setMentionNavigation((prev) => ({
            key: activeMentionKey,
            index:
              prev.key === activeMentionKey
                ? (prev.index - 1 + suggestionCount) % suggestionCount
                : suggestionCount - 1,
          }));
          return;
        }

        if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
          e.preventDefault();
          const insertion = buildMentionInsertion(
            filteredMentionSuggestions[
              Math.min(mentionSelectedIndex, suggestionCount - 1)
            ],
          );
          if (insertion) {
            onInputChange(insertion.nextValue);
            setComposerSelection({
              start: insertion.nextCaret,
              end: insertion.nextCaret,
            });
            setDismissedMentionKey(null);
            focusComposerAtOffset(composerInputId, insertion.nextCaret);
          }
          return;
        }
      }

      if (e.key === "Enter" && e.shiftKey) {
        e.preventDefault();
        const nextValue = input.slice(0, caretStart) + "\n" + input.slice(caretEnd);
        const nextCaret = caretStart + 1;
        onInputChange(nextValue);
        setComposerSelection({ start: nextCaret, end: nextCaret });
        focusComposerAtOffset(composerInputId, nextCaret);
        return;
      }

      if (isMentionMenuOpen && (e.key === "Escape" || e.key === "Tab")) {
        setDismissedMentionKey(activeMentionKey);
      }

      onKeyDown(e);
      window.requestAnimationFrame(() => {
        if (composerInputRef.current) {
          syncComposerSelection(composerInputRef.current);
        }
      });
    },
    [
      activeMentionKey,
      buildMentionInsertion,
      composerInputId,
      composerSelection.end,
      composerSelection.start,
      filteredMentionSuggestions,
      input,
      isMentionMenuOpen,
      mentionSelectedIndex,
      onKeyDown,
      onInputChange,
      removeMentionToken,
      syncComposerSelection,
    ],
  );

  const handleMentionInteractOutside = useCallback(
    (event: Event) => {
      const target = event.target;
      if (target instanceof Node && composerRef.current?.contains(target)) {
        return;
      }
      setDismissedMentionKey(activeMentionKey);
    },
    [activeMentionKey],
  );

  return (
    <div className="h-full flex flex-col min-w-0 border-r">
      <div className="flex-1 relative min-h-0">
        <Conversation className="absolute inset-0">
          <ConversationContent className="gap-4 pb-4 max-w-[720px] mx-auto w-full">
            <ChatStreamBody
              sessionId={sessionId}
              isLoading={isLoading}
              messages={messages}
              onResolveDeleteConfirmation={onResolveDeleteConfirmation}
              onResolveGitConfirmation={onResolveGitConfirmation}
              onResolveConnectInput={onResolveConnectInput}
              onResolvePlanQuestionsInput={onResolvePlanQuestionsInput}
              onViewPlan={onViewPlan}
              personaState={personaState}
              onCompletionAction={onCompletionAction}
              activeCompletionAction={activeCompletionAction}
              canCompress={canCompress}
            />
          </ConversationContent>
        </Conversation>
        <div className="absolute right-2 top-0 bottom-0 flex items-center pointer-events-none z-10">
          <div className="pointer-events-auto">
            <MessageOutline messages={messages} isLoading={isLoading} />
          </div>
        </div>
      </div>

        <div className="shrink-0 border-t bg-background">
          <div className="max-w-[720px] mx-auto w-full">
            <PlanToggle planSteps={planSteps} isStreaming={isLoading} />
            <div className="px-3 pb-1">
              <CodeChangePanel
                changes={codeChanges}
                title="本次会话代码追踪"
                emptyMessage="本轮对话还没有发生新增、修改或删除代码。"
                collapsible
                compact
                defaultOpen={false}
              />
            </div>

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

              <div
                ref={composerRef}
                className="relative"
                onFocusCapture={() => setIsFocused(true)}
                onBlurCapture={(event) => {
                  if (
                    event.relatedTarget instanceof Node &&
                    event.currentTarget.contains(event.relatedTarget)
                  ) {
                    return;
                  }
                  setIsFocused(false);
                }}
              >
                <ChatComposerEditor
                  value={input}
                  suggestions={mentionSuggestions}
                  onChange={onInputChange}
                  onSubmit={onSendMessage}
                />
              </div>
              <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2 border-t border-border/50 pt-2">
                <div className="flex min-w-0 flex-wrap items-center gap-1">
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

                  <Select
                    value={agentMode}
                    onValueChange={(value) => onAgentModeChange(value as AgentMode)}
                  >
                    <SelectTrigger
                      size="sm"
                      className="h-7 min-w-[96px] max-w-full gap-1.5 border-0 px-2 text-xs text-muted-foreground shadow-none"
                      aria-label="选择智能体模式"
                    >
                      <Code2Icon className="size-3.5" />
                      <SelectValue placeholder="模式" />
                    </SelectTrigger>
                    <SelectContent align="start">
                      <SelectItem value="auto">自动</SelectItem>
                      <SelectItem value="plan">计划</SelectItem>
                      <SelectItem value="coding">编码</SelectItem>
                      <SelectItem value="deploy">部署</SelectItem>
                    </SelectContent>
                  </Select>

                  <Select
                    value={selectedReasoningEffort}
                    onValueChange={onReasoningEffortChange}
                  >
                    <SelectTrigger
                      size="sm"
                      className="h-7 min-w-[108px] max-w-full gap-1.5 border-0 px-2 text-xs text-muted-foreground shadow-none"
                      aria-label="选择思考程度"
                    >
                      <LightbulbIcon className="size-3.5" />
                      <SelectValue placeholder="思考程度" />
                    </SelectTrigger>
                    <SelectContent align="start">
                      <SelectItem value="default">默认</SelectItem>
                      <SelectItem value="none">不思考</SelectItem>
                      <SelectItem value="minimal">极低</SelectItem>
                      <SelectItem value="low">低</SelectItem>
                      <SelectItem value="medium">中</SelectItem>
                      <SelectItem value="high">高</SelectItem>
                      <SelectItem value="xhigh">超高</SelectItem>
                    </SelectContent>
                  </Select>

                  <ContextViewer
                    contextData={contextData}
                    codeChanges={codeChanges}
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
