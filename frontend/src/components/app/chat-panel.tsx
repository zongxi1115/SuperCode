import { ContextViewer } from "@/components/app/context-viewer";
import { TurnFileChangeList } from "@/components/ai-elements/file-change-list";
import { SubagentTaskCard } from "@/components/ai-elements/subagent-task";
import { ChatComposerEditor } from "@/components/app/chat-composer-editor";
import { cn } from "@/lib/utils";
import { apiFetch } from "@/lib/api-client";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep,
  ErrorChainBlock,
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
  SessionExecutionMode,
  SkillSummary,
  SubagentSnapshot,
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
  Pencil,
  RotateCcw,
  Archive,
  Eye,
  Loader2,
  Check,
  BotIcon,
  MessageSquareIcon,
  MemoryStick,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type React from "react";
import {
  memo,
  useMemo,
  useRef,
  useState,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
} from "react";

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
  composerFocusRevision?: number;
  isLoading: boolean;
  model: string | null;
  reasoningEffort: string | null;
  executionMode: SessionExecutionMode;
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
  onResolveConnectInput?: (
    toolCallId: string,
    values: Record<string, string>,
  ) => void;
  onResolvePlanQuestionsInput?: (
    toolCallId: string,
    answers: QuizSubmission,
  ) => void | Promise<void>;
  onViewPlan?: (title: string, markdown: string) => void;
  agentMode: AgentMode;
  onAgentModeChange: (mode: AgentMode) => void;
  onModelChange: (modelId: string) => void;
  onReasoningEffortChange: (reasoningEffort: string) => void;
  onExecutionModeChange: (mode: SessionExecutionMode) => void;
  onCompletionAction?: (
    action: CompletionActionKey,
    message: ChatMessage,
  ) => void;
  activeCompletionAction?: {
    messageId: string;
    action: CompletionActionKey;
  } | null;
  elementAttachments?: ElementAttachment[];
  onRemoveElementAttachment?: (id: string) => void;
  onEditMessage?: (content: string) => void;
  thinkingRendering?: "text" | "markdown";
  finalAnswerRendering?: "markdown" | "html";
};

type MentionSuggestion = {
  id: string;
  kind: "workspace" | "file" | "change" | "element" | "skill";
  label: string;
  description: string;
  insertValue: string;
  filePath?: string;
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
  remember_preference: <MemoryStick className="size-4" />,
  delegate_code_exploration: <BotIcon className="size-4" />,
};

function isSubagentMessage(message: ChatMessage) {
  return message.agentScope === "subagent" || Boolean(message.subagentId);
}

function getSubagentSnapshot(message: ChatMessage): SubagentSnapshot | null {
  const dataPart = [...(message.parts ?? [])].reverse().find(
    (part): part is Extract<ContentBlock, { type: "data" }> =>
      part.type === "data" &&
      part.dataType === "data-subagent-task" &&
      Boolean(part.data) &&
      typeof part.data === "object" &&
      !Array.isArray(part.data),
  );
  return dataPart ? (dataPart.data as SubagentSnapshot) : null;
}

function getSubagentMessagesForParent(
  messages: ChatMessage[],
  parentToolCallId: string,
) {
  return messages.filter((message) => {
    if (message.parentToolCallId === parentToolCallId) {
      return true;
    }
    return getSubagentSnapshot(message)?.parentToolCallId === parentToolCallId;
  });
}

function isSubagentMessageRunning(message: ChatMessage) {
  const snapshot = getSubagentSnapshot(message);
  if (snapshot?.status === "running") {
    return true;
  }
  if (
    snapshot?.status === "completed" ||
    snapshot?.status === "error" ||
    snapshot?.status === "paused"
  ) {
    return false;
  }
  return (message.toolCalls ?? []).some((toolCall) => toolCall.state === "running");
}

function latestSubagentSnapshot(messages: ChatMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const snapshot = getSubagentSnapshot(messages[index]);
    if (snapshot) {
      return snapshot;
    }
  }
  return null;
}

function stripSubagentSnapshotParts(messages: ChatMessage[]) {
  return messages.map((message) => ({
    ...message,
    parts: (message.parts ?? []).filter(
      (part) => !(part.type === "data" && part.dataType === "data-subagent-task"),
    ),
  }));
}

function findToolCallById(messages: ChatMessage[], toolCallId: string) {
  for (const message of messages) {
    const toolCalls = [
      ...(message.toolCalls ?? []),
      ...((message.parts ?? [])
        .filter(
          (part): part is Extract<ContentBlock, { type: "tool_call" }> =>
            part.type === "tool_call",
        )
        .map((part) => part.toolCall) ?? []),
    ];
    const match = toolCalls.find((toolCall) => toolCall.id === toolCallId);
    if (match) {
      return match;
    }
  }
  return null;
}

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
    const f = ((args.filename || args.path || args.file_path) as string)
      ?.split(/[\\/]/)
      .pop();
    return f ? `正在搜索项目列表 ${f}` : "正在搜索项目列表";
  },
  read_file: (args) => {
    const f = ((args.filename || args.path || args.file_path) as string)
      ?.split(/[\\/]/)
      .pop();
    return f ? `正在阅读 ${f}` : "正在阅读文件";
  },
  write_file: (args) => {
    const f = ((args.filename || args.path || args.file_path) as string)
      ?.split(/[\\/]/)
      .pop();
    return f ? `正在创建 ${f}` : "正在创建文件";
  },
  apply_patch: (args) => {
    const f = ((args.filename || args.path || args.file_path) as string)
      ?.split(/[\\/]/)
      .pop();
    return f ? `正在编辑 ${f}` : "正在编辑文件";
  },
  replace_file: (args) => {
    const f = ((args.filename || args.path || args.file_path) as string)
      ?.split(/[\\/]/)
      .pop();
    return f ? `正在替换 ${f}` : "正在替换文件";
  },
  delete_file: (args) => {
    const f = ((args.filename || args.path || args.file_path) as string)
      ?.split(/[\\/]/)
      .pop();
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
  remember_preference: () => "正在记录长期记忆",
  delegate_code_exploration: () => "代码探索",
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
  const match = input.match(
    new RegExp(`"${field}"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"`),
  );
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
          typeof record.placeholder === "string"
            ? record.placeholder
            : undefined,
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
                  id: String(
                    optionRecord.id ?? `option_${index + 1}_${optionIndex + 1}`,
                  ),
                  label,
                };
              })
              .filter(
                (option): option is NonNullable<typeof option> =>
                  option !== null,
              )
          : undefined,
      } satisfies PlanQuizQuestion;
    })
    .filter(
      (question): question is NonNullable<typeof question> => question !== null,
    );

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
      extractBalancedQuestionObjects(streamedInput)
        .map((item) => {
          try {
            return JSON.parse(item) as PlanQuestionSource;
          } catch {
            return null;
          }
        })
        .filter((item): item is PlanQuestionSource => item !== null),
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
      const results = (output as Record<string, unknown>)?.results as
        | Array<{ url?: string; title?: string; snippet?: string }>
        | undefined;
      results?.forEach((r) => {
        if (r.url)
          map.set(r.url, { url: r.url, title: r.title, snippet: r.snippet });
      });
    } else if (tc.name === "fetch_url_content") {
      const docs = (output as Record<string, unknown>)?.documents as
        | Array<{ url?: string; title?: string; content?: string }>
        | undefined;
      docs?.forEach((d) => {
        if (d.url)
          map.set(d.url, {
            url: d.url,
            title: d.title,
            snippet: d.content ? d.content.slice(0, 200) : undefined,
          });
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

type HtmlArtifact = {
  type: "html";
  title: string;
  html: string;
  isPartial?: boolean;
};

type FinalAnswerSegment =
  | { type: "text"; value: string }
  | { type: "artifact"; artifact: HtmlArtifact }
  | { type: "pending-artifact"; title: string };

const ARTIFACT_OPEN_TAG_RE = /<supercode-artifact\b([^>]*)>/i;
const PARTIAL_ARTIFACT_OPEN_TAG_RE = /<supercode-artifact\b[\s\S]*$/i;
const ARTIFACT_CLOSE_TAG_RE = /<\/supercode-artifact>/i;
const ARTIFACT_TITLE_RE = /\btitle\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i;
const ARTIFACT_TYPE_RE = /\btype\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i;
const FENCED_HTML_BLOCK_RE = /```html\b[^\n]*\n([\s\S]*?)\n```/i;
const FENCED_HTML_OPEN_RE = /```html\b[^\n]*\n/i;
const COMPLETE_HTML_DOC_RE = /(?:<!doctype\s+html[^>]*>\s*)?<html\b[\s\S]*?<\/html>/i;
const HTML_FRAGMENT_RE = /<(?:style|script|main|section|article|div|svg)\b[\s\S]*?<\/(?:style|script|main|section|article|div|svg)>/i;
const PARTIAL_HTML_START_RE = /(?:<!doctype\s+html[^>]*>\s*)?<(?:html|main|section|article|div|svg|style|script)\b/i;
const HTML_TITLE_RE = /<title[^>]*>([\s\S]*?)<\/title>/i;
const HTML_H1_RE = /<h1[^>]*>([\s\S]*?)<\/h1>/i;
const LIVE_ARTIFACT_UPDATE_INTERVAL_MS = 140;

const CHAT_CONTENT_MAX_WIDTH = "max-w-[880px]";
const CHAT_HERO_MAX_WIDTH = "max-w-[960px]";

function decodeHtmlAttributeValue(value: string) {
  if (typeof document === "undefined") return value;
  const textarea = document.createElement("textarea");
  textarea.innerHTML = value;
  return textarea.value;
}

function readArtifactAttribute(attributes: string, regex: RegExp) {
  const match = regex.exec(attributes);
  const rawValue = match?.[1] ?? match?.[2] ?? match?.[3] ?? "";
  return decodeHtmlAttributeValue(rawValue.trim());
}

function stripHtmlForTitle(value: string) {
  return decodeHtmlAttributeValue(value.replace(/<[^>]*>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function inferHtmlArtifactTitle(html: string) {
  const title = HTML_TITLE_RE.exec(html)?.[1] ?? HTML_H1_RE.exec(html)?.[1] ?? "";
  return stripHtmlForTitle(title) || "HTML Artifact";
}

function parseFinalAnswerSegments(
  text: string,
  options?: { allowAutoHtml?: boolean },
): FinalAnswerSegment[] {
  const segments: FinalAnswerSegment[] = [];
  let cursor = 0;
  const allowAutoHtml = options?.allowAutoHtml ?? false;

  while (cursor < text.length) {
    const remaining = text.slice(cursor);
    const openMatch = ARTIFACT_OPEN_TAG_RE.exec(remaining);
    const partialOpenMatch = !openMatch ? PARTIAL_ARTIFACT_OPEN_TAG_RE.exec(remaining) : null;
    const fencedHtmlOpenMatch = allowAutoHtml ? FENCED_HTML_OPEN_RE.exec(remaining) : null;
    const explicitBoundaryIndex = Math.min(
      openMatch?.index ?? Number.POSITIVE_INFINITY,
      partialOpenMatch?.index ?? Number.POSITIVE_INFINITY,
      fencedHtmlOpenMatch?.index ?? Number.POSITIVE_INFINITY,
    );
    const hasExplicitBoundary = Number.isFinite(explicitBoundaryIndex);
    const autoHtmlScanText =
      allowAutoHtml && hasExplicitBoundary
        ? remaining.slice(0, explicitBoundaryIndex)
        : remaining;
    const shouldScanFencedBlock =
      allowAutoHtml &&
      (!hasExplicitBoundary ||
        Boolean(
          fencedHtmlOpenMatch &&
            fencedHtmlOpenMatch.index <= explicitBoundaryIndex,
        ));
    const fencedHtmlMatch = shouldScanFencedBlock
      ? FENCED_HTML_BLOCK_RE.exec(remaining)
      : null;
    const htmlDocMatch = allowAutoHtml ? COMPLETE_HTML_DOC_RE.exec(autoHtmlScanText) : null;
    const htmlFragmentMatch = allowAutoHtml ? HTML_FRAGMENT_RE.exec(autoHtmlScanText) : null;
    const partialHtmlMatch =
      allowAutoHtml && !htmlDocMatch && !htmlFragmentMatch
        ? PARTIAL_HTML_START_RE.exec(autoHtmlScanText)
        : null;

    const candidates = [
      openMatch ? { kind: "artifact" as const, index: openMatch.index, match: openMatch } : null,
      partialOpenMatch
        ? { kind: "partial-artifact-open" as const, index: partialOpenMatch.index, match: partialOpenMatch }
        : null,
      fencedHtmlMatch ? { kind: "fenced" as const, index: fencedHtmlMatch.index, match: fencedHtmlMatch } : null,
      htmlDocMatch ? { kind: "document" as const, index: htmlDocMatch.index, match: htmlDocMatch } : null,
      htmlFragmentMatch ? { kind: "fragment" as const, index: htmlFragmentMatch.index, match: htmlFragmentMatch } : null,
      partialHtmlMatch
        ? { kind: "partial-html" as const, index: partialHtmlMatch.index, match: partialHtmlMatch }
        : null,
      fencedHtmlOpenMatch && !fencedHtmlMatch
        ? { kind: "pending-fenced" as const, index: fencedHtmlOpenMatch.index, match: fencedHtmlOpenMatch }
        : null,
    ]
      .filter((candidate): candidate is NonNullable<typeof candidate> => candidate !== null)
      .sort((a, b) => a.index - b.index);

    const candidate = candidates[0];
    if (!candidate) {
      const value = text.slice(cursor);
      if (value) segments.push({ type: "text", value });
      break;
    }

    const start = cursor + candidate.index;
    const before = text.slice(cursor, start);
    if (before) segments.push({ type: "text", value: before });

    if (candidate.kind === "fenced") {
      const html = (candidate.match[1] ?? "").trim();
      segments.push({
        type: "artifact",
        artifact: {
          type: "html",
          title: inferHtmlArtifactTitle(html),
          html,
        },
      });
      cursor = start + candidate.match[0].length;
      continue;
    }

    if (candidate.kind === "partial-artifact-open") {
      segments.push({ type: "pending-artifact", title: "HTML Artifact" });
      break;
    }

    if (candidate.kind === "pending-fenced") {
      const openEnd = start + candidate.match[0].length;
      const html = text.slice(openEnd).trim();
      if (html) {
        segments.push({
          type: "artifact",
          artifact: {
            type: "html",
            title: inferHtmlArtifactTitle(html),
            html,
            isPartial: true,
          },
        });
      } else {
        segments.push({ type: "pending-artifact", title: "HTML Artifact" });
      }
      break;
    }

    if (candidate.kind === "document") {
      const html = candidate.match[0].trim();
      segments.push({
        type: "artifact",
        artifact: {
          type: "html",
          title: inferHtmlArtifactTitle(html),
          html,
        },
      });
      cursor = start + candidate.match[0].length;
      continue;
    }

    if (candidate.kind === "fragment") {
      const html = candidate.match[0].trim();
      segments.push({
        type: "artifact",
        artifact: {
          type: "html",
          title: inferHtmlArtifactTitle(html),
          html,
        },
      });
      cursor = start + candidate.match[0].length;
      continue;
    }

    if (candidate.kind === "partial-html") {
      const html = text.slice(start).trim();
      if (html) {
        segments.push({
          type: "artifact",
          artifact: {
            type: "html",
            title: inferHtmlArtifactTitle(html),
            html,
            isPartial: true,
          },
        });
      } else {
        segments.push({ type: "pending-artifact", title: "HTML Artifact" });
      }
      break;
    }

    const openStart = start;
    const openEnd = openStart + candidate.match[0].length;
    const attributes = candidate.match[1] ?? "";
    const artifactType = readArtifactAttribute(attributes, ARTIFACT_TYPE_RE).toLowerCase();
    const title = readArtifactAttribute(attributes, ARTIFACT_TITLE_RE) || "HTML Artifact";
    const closeMatch = ARTIFACT_CLOSE_TAG_RE.exec(text.slice(openEnd));
    if (!closeMatch || closeMatch.index < 0) {
      const html = text.slice(openEnd).trim();
      if (artifactType === "html" && html) {
        segments.push({
          type: "artifact",
          artifact: {
            type: "html",
            title,
            html,
            isPartial: true,
          },
        });
      } else {
        segments.push({ type: "pending-artifact", title });
      }
      break;
    }

    const closeStart = openEnd + closeMatch.index;
    const closeEnd = closeStart + closeMatch[0].length;
    const html = text.slice(openEnd, closeStart).trim();
    if (artifactType === "html") {
      segments.push({
        type: "artifact",
        artifact: {
          type: "html",
          title,
          html,
        },
      });
    } else {
      segments.push({ type: "text", value: text.slice(openStart, closeEnd) });
    }
    cursor = closeEnd;
  }

  return segments;
}

function buildArtifactSrcDoc(html: string, frameId: string) {
  const csp = [
    "default-src https: data: blob:",
    "img-src https: data: blob:",
    "style-src https: 'unsafe-inline'",
    "script-src https: 'unsafe-inline'",
    "font-src https: data:",
    "connect-src https:",
    "frame-ancestors 'none'",
  ].join("; ");
  const meta = `<meta http-equiv="Content-Security-Policy" content="${escapeHtmlAttribute(csp)}">`;
  const baseStyle = [
    "<style data-supercode-artifact-base>",
    "html,body{margin:0;background:transparent;}",
    "body{min-height:auto;color:inherit;overflow:hidden;}",
    "</style>",
  ].join("");
  const resizeScript = [
    "<script data-supercode-artifact-resize>",
    "(()=>{",
    `const id=${JSON.stringify(frameId)};`,
    "const send=()=>{",
    "const b=document.body,d=document.documentElement;",
    "const h=Math.ceil(Math.max(b?b.scrollHeight:0,d?d.scrollHeight:0,b?b.offsetHeight:0,d?d.offsetHeight:0));",
    "parent.postMessage({type:'supercode-artifact-size',id,height:h},'*');",
    "};",
    "new ResizeObserver(send).observe(document.documentElement);",
    "window.addEventListener('load',send);",
    "setTimeout(send,0);setTimeout(send,120);setTimeout(send,600);",
    "})();",
    "</script>",
  ].join("");
  const trimmed = html.trim();
  if (/<head[\s>]/i.test(trimmed)) {
    return trimmed.replace(/<head([^>]*)>/i, `<head$1>${meta}${baseStyle}${resizeScript}`);
  }
  if (/<html[\s>]/i.test(trimmed)) {
    return trimmed.replace(/<html([^>]*)>/i, `<html$1><head>${meta}${baseStyle}${resizeScript}</head>`);
  }
  return `<!doctype html><html><head>${meta}${baseStyle}${resizeScript}</head><body>${trimmed}</body></html>`;
}

function buildArtifactLiveSrcDoc(frameId: string) {
  const csp = [
    "default-src https: data: blob:",
    "img-src https: data: blob:",
    "style-src https: 'unsafe-inline'",
    "script-src https: 'unsafe-inline'",
    "font-src https: data:",
    "connect-src https:",
    "frame-ancestors 'none'",
  ].join("; ");
  const meta = `<meta http-equiv="Content-Security-Policy" content="${escapeHtmlAttribute(csp)}">`;
  const baseStyle = [
    "<style data-supercode-artifact-base>",
    "html,body{margin:0;background:transparent;}",
    "body{min-height:auto;color:inherit;overflow:hidden;}",
    "*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important;}",
    "</style>",
  ].join("");
  const liveScript = [
    "<script data-supercode-artifact-live>",
    "(()=>{",
    `const id=${JSON.stringify(frameId)};`,
    "let latestHtml='';",
    "let scheduled=false;",
    "const parser=new DOMParser();",
    "const ensureBaseStyle=()=>{",
    "let style=document.querySelector('style[data-supercode-artifact-base]');",
    "if(!style){style=document.createElement('style');style.setAttribute('data-supercode-artifact-base','');document.head.prepend(style);}",
    "style.textContent='html,body{margin:0;background:transparent;}body{min-height:auto;color:inherit;overflow:hidden;}*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important;}';",
    "};",
    "const send=()=>{",
    "const b=document.body,d=document.documentElement;",
    "const h=Math.ceil(Math.max(b?b.scrollHeight:0,d?d.scrollHeight:0,b?b.offsetHeight:0,d?d.offsetHeight:0));",
    "parent.postMessage({type:'supercode-artifact-size',id,height:h},'*');",
    "};",
    "const stripScripts=(root)=>{root.querySelectorAll?.('script').forEach((script)=>script.remove());};",
    "const sameNode=(current,next)=>{",
    "if(current.nodeType!==next.nodeType)return false;",
    "if(current.nodeType===Node.ELEMENT_NODE)return current.tagName===next.tagName;",
    "return true;",
    "};",
    "const syncAttrs=(current,next)=>{",
    "if(current.nodeType!==Node.ELEMENT_NODE||next.nodeType!==Node.ELEMENT_NODE)return;",
    "for(const attr of Array.from(current.attributes)){if(!next.hasAttribute(attr.name))current.removeAttribute(attr.name);}",
    "for(const attr of Array.from(next.attributes)){if(current.getAttribute(attr.name)!==attr.value)current.setAttribute(attr.name,attr.value);}",
    "};",
    "const morphNode=(current,next)=>{",
    "if(!sameNode(current,next)){current.replaceWith(document.importNode(next,true));return;}",
    "if(current.nodeType===Node.TEXT_NODE||current.nodeType===Node.COMMENT_NODE){if(current.nodeValue!==next.nodeValue)current.nodeValue=next.nodeValue;return;}",
    "syncAttrs(current,next);",
    "morphChildren(current,next);",
    "};",
    "const morphChildren=(current,next)=>{",
    "const currentChildren=Array.from(current.childNodes);",
    "const nextChildren=Array.from(next.childNodes);",
    "const max=Math.max(currentChildren.length,nextChildren.length);",
    "for(let i=0;i<max;i++){",
    "const currentChild=currentChildren[i];",
    "const nextChild=nextChildren[i];",
    "if(!nextChild){currentChild?.remove();continue;}",
    "if(!currentChild){current.appendChild(document.importNode(nextChild,true));continue;}",
    "morphNode(currentChild,nextChild);",
    "}",
    "};",
    "const apply=()=>{",
    "scheduled=false;",
    "const html=latestHtml.trim();",
    "try{",
    "const hasHtml=/<html[\\s>]/i.test(html);",
    "const source=hasHtml?html:'<!doctype html><html><head></head><body>'+html+'</body></html>';",
    "const doc=parser.parseFromString(source,'text/html');",
    "stripScripts(doc);",
    "document.documentElement.lang=doc.documentElement.lang||document.documentElement.lang;",
    "document.head.innerHTML=doc.head?doc.head.innerHTML:'';",
    "ensureBaseStyle();",
    "if(doc.body)morphChildren(document.body,doc.body);",
    "}catch{document.body.textContent='';}",
    "send();requestAnimationFrame(send);setTimeout(send,80);",
    "};",
    "const schedule=()=>{if(scheduled)return;scheduled=true;requestAnimationFrame(apply);};",
    "window.addEventListener('message',(event)=>{",
    "const data=event.data;",
    "if(!data||typeof data!=='object'||data.type!=='supercode-artifact-html'||data.id!==id)return;",
    "latestHtml=String(data.html||'');",
    "schedule();",
    "});",
    "ensureBaseStyle();",
    "new ResizeObserver(send).observe(document.documentElement);",
    "window.addEventListener('load',send);",
    "setTimeout(send,0);",
    "})();",
    "</script>",
  ].join("");

  return `<!doctype html><html><head>${meta}${baseStyle}${liveScript}</head><body></body></html>`;
}

function HtmlArtifactPreview({
  artifact,
  isGenerating,
}: {
  artifact: HtmlArtifact;
  isGenerating?: boolean;
}) {
  const frameId = useId();
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState(240);
  const usesLivePreview = Boolean(artifact.isPartial && isGenerating);
  const latestLiveHtmlRef = useRef(artifact.html);
  const liveSendTimerRef = useRef<number | null>(null);
  const lastLiveSentAtRef = useRef(0);
  const liveSrcDoc = useMemo(() => buildArtifactLiveSrcDoc(frameId), [frameId]);
  const finalSrcDoc = useMemo(
    () => (usesLivePreview ? "" : buildArtifactSrcDoc(artifact.html, frameId)),
    [artifact.html, frameId, usesLivePreview],
  );
  const srcDoc = usesLivePreview ? liveSrcDoc : finalSrcDoc;

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const data = event.data;
      if (!data || typeof data !== "object") return;
      if (data.type !== "supercode-artifact-size" || data.id !== frameId) return;
      const nextHeight = Number(data.height);
      if (!Number.isFinite(nextHeight) || nextHeight <= 0) return;
      setHeight(Math.min(Math.max(Math.ceil(nextHeight), 40), 6000));
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [frameId]);

  const postLiveHtml = useCallback(() => {
    liveSendTimerRef.current = null;
    lastLiveSentAtRef.current = Date.now();
    iframeRef.current?.contentWindow?.postMessage(
      {
        type: "supercode-artifact-html",
        id: frameId,
        html: latestLiveHtmlRef.current,
      },
      "*",
    );
  }, [frameId]);

  const scheduleLiveHtmlPost = useCallback(
    (immediate = false) => {
      if (!usesLivePreview) return;
      const elapsed = Date.now() - lastLiveSentAtRef.current;
      if (immediate || elapsed >= LIVE_ARTIFACT_UPDATE_INTERVAL_MS) {
        if (liveSendTimerRef.current !== null) {
          window.clearTimeout(liveSendTimerRef.current);
          liveSendTimerRef.current = null;
        }
        postLiveHtml();
        return;
      }
      if (liveSendTimerRef.current === null) {
        liveSendTimerRef.current = window.setTimeout(
          postLiveHtml,
          LIVE_ARTIFACT_UPDATE_INTERVAL_MS - elapsed,
        );
      }
    },
    [postLiveHtml, usesLivePreview],
  );

  useEffect(() => {
    if (!usesLivePreview) return;
    latestLiveHtmlRef.current = artifact.html;
    scheduleLiveHtmlPost();
  }, [artifact.html, scheduleLiveHtmlPost, usesLivePreview]);

  useEffect(() => {
    return () => {
      if (liveSendTimerRef.current !== null) {
        window.clearTimeout(liveSendTimerRef.current);
        liveSendTimerRef.current = null;
      }
    };
  }, []);

  return (
    <div className="my-3 w-full relative">
      <iframe
        ref={iframeRef}
        className="block w-full border-0"
        sandbox="allow-scripts"
        scrolling="no"
        srcDoc={srcDoc}
        style={{ height }}
        title={artifact.title}
        onLoad={() => {
          if (!usesLivePreview) return;
          latestLiveHtmlRef.current = artifact.html;
          scheduleLiveHtmlPost(true);
        }}
      />
      {usesLivePreview && (
        <div
          aria-hidden="true"
          className="artifact-live-preview-lock absolute inset-0 z-10"
        />
      )}
    </div>
  );
}

function PendingHtmlArtifact({ title }: { title: string }) {
  return (
    <div className="my-3 flex items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" />
      <span className="truncate">{title || "HTML Artifact"} 正在接收内容</span>
    </div>
  );
}

function renderFinalAnswerContent(
  text: string,
  citations: Map<string, CitationInfo>,
  options?: {
    className?: string;
    isAnimating?: boolean;
    key?: string;
    finalAnswerRendering?: "markdown" | "html";
  },
) {
  const hasExplicitArtifact = ARTIFACT_OPEN_TAG_RE.test(text);
  if (options?.finalAnswerRendering !== "html" && !hasExplicitArtifact) {
    return renderCitationMessage(text, citations, options);
  }

  const segments = parseFinalAnswerSegments(text, {
    allowAutoHtml: options?.finalAnswerRendering === "html",
  });
  const isAnimating = options?.isAnimating ?? false;
  return (
    <div key={options?.key} className="space-y-2">
      {segments.map((segment, index) => {
        if (segment.type === "text") {
          return segment.value.trim()
            ? renderCitationMessage(segment.value, citations, {
                className: options?.className,
                isAnimating,
                key: `text-${index}`,
              })
            : null;
        }
        if (segment.type === "pending-artifact") {
          return <PendingHtmlArtifact key={`pending-${index}`} title={segment.title} />;
        }
        return (
          <HtmlArtifactPreview
            key={`artifact-${index}`}
            artifact={segment.artifact}
            isGenerating={isAnimating}
          />
        );
      })}
    </div>
  );
}

function getCitationDisplayTitle(
  url: string,
  citations: Map<string, CitationInfo>,
) {
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

function renderCitationBadge(
  sources: string[],
  citations: Map<string, CitationInfo>,
) {
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

function useStreamingCodeBlocks(
  containerRef: React.RefObject<HTMLDivElement | null>,
  isAnimating: boolean,
) {
  useEffect(() => {
    if (!isAnimating) return;
    const container = containerRef.current;
    if (!container) return;

    const scrollStates = new WeakMap<HTMLElement, boolean>();
    const badgeMap = new WeakMap<HTMLElement, HTMLElement>();

    const setBadgeState = (badge: HTMLElement, state: "loading" | "arrow") => {
      const iconSlot = badge.querySelector("[data-icon-slot]");
      const labelSlot = badge.querySelector("[data-label-slot]");
      if (!iconSlot || !labelSlot) return;

      if (state === "loading") {
        iconSlot.innerHTML = "";
        const dots = document.createElement("span");
        dots.className = "inline-flex items-center gap-[3px]";
        for (let i = 0; i < 3; i++) {
          const dot = document.createElement("span");
          dot.className = "stagger-dot size-1 rounded-full bg-current";
          dot.style.animationDelay = `${i * 0.15}s`;
          dots.appendChild(dot);
        }
        iconSlot.appendChild(dots);
        labelSlot.textContent = "加载中";
        badge.classList.remove("cursor-pointer");
        badge.removeAttribute("data-badge-arrow");
      } else {
        iconSlot.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>`;
        labelSlot.textContent = "回到底部";
        badge.classList.add("cursor-pointer");
        badge.setAttribute("data-badge-arrow", "");
      }

      badge.setAttribute("data-badge-state", state);
      badge.classList.add("badge-state-enter");
      requestAnimationFrame(() => {
        badge.classList.remove("badge-state-enter");
      });
    };

    const createBadge = (pre: HTMLElement) => {
      const el = document.createElement("div");
      el.className =
        "streaming-code-badge pointer-events-none absolute bottom-1 left-1/2 -translate-x-1/2 z-20 inline-flex items-center gap-1.5 rounded-full bg-muted/90 px-2.5 py-1 text-muted-foreground text-xs backdrop-blur-sm border border-border/50 transition-colors duration-150";
      el.style.display = isAnimating ? "" : "none";

      const iconSlot = document.createElement("span");
      iconSlot.setAttribute("data-icon-slot", "");
      iconSlot.className =
        "inline-flex items-center transition-opacity duration-150";
      el.appendChild(iconSlot);

      const labelSlot = document.createElement("span");
      labelSlot.setAttribute("data-label-slot", "");
      labelSlot.className = "transition-opacity duration-150";
      el.appendChild(labelSlot);

      el.addEventListener("click", () => {
        if (el.getAttribute("data-badge-state") === "arrow") {
          pre.scrollTop = pre.scrollHeight;
          scrollStates.set(pre, true);
          updateOverlay(pre);
        }
      });

      setBadgeState(el, "loading");
      return el;
    };

    const updateOverlay = (pre: HTMLElement) => {
      const block = pre.closest(
        '[data-streamdown="code-block"]',
      ) as HTMLElement;
      if (!block) return;

      const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 20;
      const wasAtBottom = scrollStates.get(pre) ?? true;
      scrollStates.set(pre, atBottom);

      const badge = badgeMap.get(pre);
      if (badge) {
        badge.style.display = isAnimating ? "" : "none";
        if (isAnimating) {
          const currentState = badge.getAttribute("data-badge-state");
          const nextState = atBottom ? "loading" : "arrow";
          if (currentState !== nextState) {
            setBadgeState(badge, nextState as "loading" | "arrow");
          }
        }
      }

      if (atBottom && wasAtBottom !== false) {
        requestAnimationFrame(() => {
          pre.scrollTop = pre.scrollHeight;
        });
      }
    };

    const onScroll = (e: Event) => {
      const pre = e.target as HTMLElement;
      updateOverlay(pre);
    };

    const scanBlocks = () => {
      const blocks = container.querySelectorAll<HTMLDivElement>(
        '[data-streamdown="code-block"]',
      );
      blocks.forEach((block) => {
        const pre = block.querySelector("pre");
        if (!pre) return;

        block.style.position = "relative";

        if (!badgeMap.has(pre)) {
          const badge = createBadge(pre);
          block.appendChild(badge);
          badgeMap.set(pre, badge);
        }

        if (!scrollStates.has(pre)) {
          scrollStates.set(pre, true);
          pre.addEventListener("scroll", onScroll, { passive: true });
        }

        updateOverlay(pre);
      });
    };

    scanBlocks();

    const mo = new MutationObserver(() => {
      scanBlocks();
      requestAnimationFrame(() => {
        container
          .querySelectorAll<HTMLPreElement>(
            '[data-streamdown="code-block"] pre',
          )
          .forEach((pre) => {
            const atBottom = scrollStates.get(pre) ?? true;
            if (atBottom) {
              pre.scrollTop = pre.scrollHeight;
            }
          });
      });
    });
    mo.observe(container, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    return () => {
      mo.disconnect();
      container
        .querySelectorAll<HTMLPreElement>('[data-streamdown="code-block"] pre')
        .forEach((pre) => {
          pre.removeEventListener("scroll", onScroll);
          const badge = badgeMap.get(pre);
          if (badge) badge.remove();
        });
    };
  }, [isAnimating, containerRef]);
}

const StreamingMessageWrapper = memo(function StreamingMessageWrapper({
  isAnimating,
  children,
}: {
  isAnimating: boolean;
  children: React.ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  useStreamingCodeBlocks(containerRef, isAnimating);
  return <div ref={containerRef}>{children}</div>;
});

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
  const isAnimating = options?.isAnimating ?? false;

  return (
    <StreamingMessageWrapper isAnimating={isAnimating} key={options?.key}>
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
        isAnimating={isAnimating}
        literalTagContent={["citation"]}
      >
        {markdown}
      </MessageResponse>
    </StreamingMessageWrapper>
  );
}

function normalizeThoughtText(value?: string | null) {
  const trimmed = dedupeAdjacentThoughtText(value?.trim() ?? "");
  if (!trimmed || trimmed === "模型未提供思路。") {
    return "";
  }
  return trimmed;
}

type ErrorSegment = {
  errors: string[];
  retryCount?: number;
  maxRetries?: number;
  retrying: boolean;
  resolved?: boolean;
};

type ThoughtSegment =
  | { type: "text"; value: string }
  | { type: "error"; value: ErrorSegment };

const ERROR_LINE_RE = /^请求出错[：:]\s*(.+)$/;
const RETRY_LINE_RE = /^正在重试[（(](\d+)[/／](\d+)[)）]，等待/;
const EXHAUSTED_LINE_RE = /^已重试\s*(\d+)\s*次仍未成功/;

function parseThoughtErrorSegments(text: string): ThoughtSegment[] {
  const segments: ThoughtSegment[] = [];
  const lines = text.split("\n");
  let textBuffer: string[] = [];
  let currentError: ErrorSegment | null = null;

  const flushText = () => {
    const joined = textBuffer.join("\n").trim();
    if (joined) {
      segments.push({ type: "text", value: joined });
    }
    textBuffer = [];
  };

  const flushError = () => {
    if (currentError) {
      segments.push({ type: "error", value: currentError });
      currentError = null;
    }
  };

  for (const line of lines) {
    const errorMatch = ERROR_LINE_RE.exec(line.trim());
    const retryMatch = RETRY_LINE_RE.exec(line.trim());
    const exhaustedMatch = EXHAUSTED_LINE_RE.exec(line.trim());

    if (errorMatch) {
      flushText();
      if (currentError) {
        currentError.errors.push(errorMatch[1].trim());
      } else {
        currentError = { errors: [errorMatch[1].trim()], retrying: false };
      }
      continue;
    }

    if (retryMatch && currentError) {
      currentError.retryCount = Number(retryMatch[1]);
      currentError.maxRetries = Number(retryMatch[2]);
      currentError.retrying = true;
      continue;
    }

    if (exhaustedMatch && currentError) {
      currentError.retryCount = Number(exhaustedMatch[1]);
      currentError.maxRetries = Number(exhaustedMatch[1]);
      currentError.retrying = false;
      const rest = line.trim().slice(exhaustedMatch[0].length).replace(/^[，,\s]+/, "").replace(/^最后错误[：:]\s*/, "").trim();
      if (rest) {
        currentError.errors.push(rest);
      }
      flushError();
      continue;
    }

    if (currentError && line.trim().startsWith("自动停止")) {
      currentError.retrying = false;
      flushError();
      continue;
    }

    if (currentError && !retryMatch && !errorMatch && !exhaustedMatch && line.trim()) {
      flushError();
      textBuffer.push(line);
      continue;
    }

    textBuffer.push(line);
  }

  flushText();
  flushError();

  for (let si = 0; si < segments.length; si++) {
    const segment = segments[si];
    if (segment.type !== "error") {
      continue;
    }

    segment.value.resolved = segments
      .slice(si + 1)
      .some((nextSegment) => nextSegment.type === "text");
  }

  return segments;
}

function getThoughtTextKey(value: string) {
  return value.trim().replace(/\s+/g, " ");
}

function dedupeAdjacentThoughtText(value: string) {
  if (!value) {
    return "";
  }

  const paragraphs = value.replace(/\r\n/g, "\n").split(/\n{2,}/);
  const dedupedParagraphs: string[] = [];
  let previousParagraphKey = "";

  for (const paragraph of paragraphs) {
    const dedupedLines: string[] = [];
    let previousLineKey = "";

    for (const line of paragraph.split("\n")) {
      const lineKey = getThoughtTextKey(line);
      if (lineKey && lineKey === previousLineKey) {
        continue;
      }
      dedupedLines.push(line);
      previousLineKey = lineKey;
    }

    const dedupedParagraph = dedupedLines.join("\n").trimEnd();
    const paragraphKey = getThoughtTextKey(dedupedParagraph);
    if (paragraphKey && paragraphKey === previousParagraphKey) {
      continue;
    }
    dedupedParagraphs.push(dedupedParagraph);
    previousParagraphKey = paragraphKey;
  }

  return dedupeAdjacentMarkdownListItems(dedupedParagraphs.join("\n\n")).trim();
}

function dedupeAdjacentMarkdownListItems(value: string) {
  const lines = value.replace(/\r\n/g, "\n").split("\n");
  const blocks: string[][] = [];
  let currentBlock: string[] = [];

  for (const line of lines) {
    const startsListItem = /^\s*[-*]\s+/.test(line);
    if (startsListItem && currentBlock.length > 0) {
      blocks.push(currentBlock);
      currentBlock = [line];
    } else {
      currentBlock.push(line);
    }
  }

  if (currentBlock.length > 0) {
    blocks.push(currentBlock);
  }

  const dedupedBlocks: string[][] = [];
  let previousBlockKey = "";
  for (const block of blocks) {
    const blockText = block.join("\n").trimEnd();
    const blockKey = getThoughtTextKey(blockText);
    if (blockKey && blockKey === previousBlockKey) {
      continue;
    }
    dedupedBlocks.push(block);
    previousBlockKey = blockKey;
  }

  return dedupedBlocks.map((block) => block.join("\n")).join("\n");
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
    void apiFetch(`/api/sessions/${sessionId}/git/status`)
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
                  const fileIcon = getFileIcon(
                    parsed.path.split(/[\\/]/).pop() ?? "",
                  );
                  return (
                    <CommitFile key={`${rawFile}-${i}`}>
                      <CommitFileInfo>
                        <CommitFileStatus status={parsed.status} />
                        {fileIcon ? (
                          <span style={{ color: fileIcon.color }}>
                            {fileIcon.icon}
                          </span>
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

function snapshotFromSubagentToolOutput(output: unknown): SubagentSnapshot | null {
  if (!output || typeof output !== "object" || Array.isArray(output)) {
    return null;
  }
  const payload = output as Record<string, unknown>;
  const dataPart = payload.data_part;
  if (
    dataPart &&
    typeof dataPart === "object" &&
    !Array.isArray(dataPart) &&
    (dataPart as Record<string, unknown>).type === "data-subagent-task"
  ) {
    const data = (dataPart as Record<string, unknown>).data;
    if (data && typeof data === "object" && !Array.isArray(data)) {
      return data as SubagentSnapshot;
    }
  }
  return null;
}

function SubagentToolSummary({
  toolCall,
  subagentMessages,
  onOpenLog,
}: {
  toolCall: ToolCallRecord;
  subagentMessages: ChatMessage[];
  onOpenLog?: (parentToolCallId: string) => void;
}) {
  const relatedMessages = getSubagentMessagesForParent(subagentMessages, toolCall.id);
  const outputSnapshot = snapshotFromSubagentToolOutput(toolCall.output);
  const snapshot = latestSubagentSnapshot(relatedMessages) ?? outputSnapshot;
  const isRunning =
    toolCall.state === "running" ||
    relatedMessages.some(isSubagentMessageRunning) ||
    snapshot?.status === "running";
  const isError = toolCall.state === "error" || snapshot?.status === "error";
  const statusLabel = isError ? "失败" : isRunning ? "探索中" : "已完成";
  const task = String(toolCall.arguments?.task || snapshot?.task || "代码探索");
  const latestMessage = relatedMessages[relatedMessages.length - 1];
  const detail = (
    snapshot?.currentThought ||
    latestMessage?.thoughts ||
    snapshot?.finalOutput ||
    (typeof toolCall.output === "object" && toolCall.output !== null && !Array.isArray(toolCall.output)
      ? String((toolCall.output as Record<string, unknown>).final_output || "")
      : "")
  ).trim();
  const stepCount = snapshot?.stepCount ?? snapshot?.steps?.length ?? 0;
  const fileCount = snapshot?.filesRead?.length ?? 0;

  return (
    <button
      type="button"
      onClick={() => onOpenLog?.(toolCall.id)}
      className={cn(
        "group flex w-full items-center gap-3 rounded-md border bg-background px-3 py-2 text-left transition-colors",
        "hover:border-foreground/20 hover:bg-muted/30",
      )}
    >
      <span
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-md border text-muted-foreground",
          isRunning && "text-primary",
          isError && "text-destructive",
        )}
      >
        {isRunning ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : isError ? (
          <XIcon className="size-3.5" />
        ) : (
          <Check className="size-3.5" />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">
            {task}
          </span>
          <span className="shrink-0 text-[11px] text-muted-foreground">
            {statusLabel}
          </span>
        </span>
        <span className="mt-0.5 flex min-w-0 items-center gap-2 text-[11px] text-muted-foreground">
          {stepCount > 0 ? <span>{stepCount} 步</span> : null}
          {fileCount > 0 ? <span>{fileCount} 文件</span> : null}
          {detail ? <span className="truncate">{detail}</span> : null}
        </span>
      </span>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
    </button>
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
  subagentMessages = [],
  onOpenSubagentLog,
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
  onResolveConnectInput?: (
    toolCallId: string,
    values: Record<string, string>,
  ) => void;
  onResolvePlanQuestionsInput?: (
    toolCallId: string,
    answers: QuizSubmission,
  ) => void | Promise<void>;
  onViewPlan?: (title: string, markdown: string) => void;
  subagentMessages?: ChatMessage[];
  onOpenSubagentLog?: (parentToolCallId: string) => void;
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
  const applyPatchPreview = (
    toolCall.name === "apply_patch" && isStreaming
      ? args.new_content || toolCall.streamedInput
      : undefined
  ) as string | undefined;
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
  ):
    | {
        title?: string;
        summary?: string;
        steps?: Array<Record<string, unknown>>;
      }
    | undefined =>
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as {
          title?: string;
          summary?: string;
          steps?: Array<Record<string, unknown>>;
        })
      : undefined;
  const normalizeQueueStatus = (
    status: unknown,
  ): "pending" | "running" | "completed" | "error" => {
    if (status === "completed") return "completed";
    if (status === "error") return "error";
    if (status === "running") return "running";
    return "pending";
  };
  const renderStepQueue = (
    steps: Array<Record<string, unknown>> | undefined,
  ) => {
    if (!steps || steps.length === 0) return null;
    return (
      <Queue isStreaming={isStreaming}>
        {steps.map((step, index) => (
          <QueueItem
            key={String(step.id ?? index)}
            status={normalizeQueueStatus(step.status)}
          >
            <QueueItemTitle>
              {String(step.title ?? `Step ${index + 1}`)}
            </QueueItemTitle>
            <QueueItemDescription>
              {String(step.summary ?? step.description ?? "")}
            </QueueItemDescription>
          </QueueItem>
        ))}
      </Queue>
    );
  };

  if (toolCall.name === "delegate_code_exploration") {
    return (
      <SubagentToolSummary
        toolCall={toolCall}
        subagentMessages={subagentMessages}
        onOpenLog={onOpenSubagentLog}
      />
    );
  }

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
    const message =
      typeof connectOutput?.message === "string"
        ? connectOutput.message
        : undefined;
    const sessionIdOut =
      typeof connectOutput?.session_id === "string"
        ? connectOutput.session_id
        : undefined;
    const rootPath =
      typeof connectOutput?.root_path === "string"
        ? connectOutput.root_path
        : undefined;
    const displayName =
      typeof connectOutput?.display_name === "string"
        ? connectOutput.display_name
        : undefined;
    const hostOut =
      typeof connectOutput?.host === "string" ? connectOutput.host : undefined;
    const usernameOut =
      typeof connectOutput?.username === "string"
        ? connectOutput.username
        : undefined;
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
              {hostOut
                ? `${usernameOut ? `${usernameOut}@` : ""}${hostOut}`
                : displayName || rootPath || sessionIdOut}
            </span>
          </div>
        )}
      </div>
    );
  }

  const streamingPlanPreview = parseStreamingPlanQuestions(
    toolCall.streamedInput,
  );
  const questions =
    normalizePlanQuestions(toolCall.inputRequest?.questions) ??
    normalizePlanQuestions(args.questions) ??
    streamingPlanPreview?.questions;
  const isPlanQuestionsTool =
    toolCall.inputRequest?.kind === "plan_questions" ||
    toolCall.name === "ask_plan_questions" ||
    Array.isArray(args.questions) ||
    Boolean(
      streamingPlanPreview?.title ||
      streamingPlanPreview?.message ||
      streamingPlanPreview?.questions?.length,
    );

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
    const stepIds = Array.isArray(taskPayload?.step_ids)
      ? taskPayload.step_ids
      : [];

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
          <p className="text-muted-foreground">
            已创建 {stepIds.length} 个 steps。
          </p>
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
        {activeTask?.steps
          ? renderStepQueue(activeTask.steps)
          : renderStepQueue(planSteps)}
        {toolCall.name === "finish_task" ? (
          <p className="text-muted-foreground">
            {nextStepId
              ? `已推进到下一步：${nextStepId}`
              : "当前 task 已完成。"}
          </p>
        ) : null}
      </div>
    );
  }

  if (toolCall.name === "remember_preference") {
    const memoryPayload =
      output && typeof output === "object" && !Array.isArray(output)
        ? (output as Record<string, unknown>)
        : undefined;
    const memoryItem =
      memoryPayload?.item &&
      typeof memoryPayload.item === "object" &&
      !Array.isArray(memoryPayload.item)
        ? (memoryPayload.item as Record<string, unknown>)
        : undefined;
    const rememberedContent =
      typeof memoryItem?.content === "string"
        ? memoryItem.content
        : typeof args.content === "string"
          ? args.content
          : "";
    const scope =
      typeof memoryPayload?.scope === "string"
        ? memoryPayload.scope
        : typeof args.scope === "string"
          ? args.scope
          : "global";
    const saved = memoryPayload?.saved !== false && toolCall.state !== "error";
    const created = memoryPayload?.created === true;
    const disabledMessage =
      memoryPayload?.message && typeof memoryPayload.message === "string"
        ? memoryPayload.message
        : undefined;
    const statusText = errorText
      ? "记录失败"
      : isStreaming
        ? "准备记录"
        : saved
          ? created
            ? "已添加"
            : "已更新"
          : "未记录";
    const scopeText = scope === "workspace" ? "当前工作区" : "全局";

    return (
      <div className="space-y-2 rounded-md border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 font-medium text-emerald-700 dark:text-emerald-300">
            <MemoryStick className="size-3.5" />
            <span>{statusText}长期记忆</span>
          </div>
          <span className="shrink-0 rounded-full bg-background/80 px-2 py-0.5 text-[11px] text-muted-foreground">
            {scopeText}
          </span>
        </div>
        {rememberedContent ? (
          <div className="rounded-md bg-background/70 px-3 py-2 leading-relaxed text-foreground">
            {rememberedContent}
          </div>
        ) : null}
        {disabledMessage || errorText ? (
          <p className={cn("text-muted-foreground", errorText && "text-destructive")}>
            {errorText || disabledMessage}
          </p>
        ) : (
          <p className="text-muted-foreground">
            以后对话会优先参考这条偏好；当前消息仍然拥有最高优先级。
          </p>
        )}
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
          isStreaming={isStreaming}
          language={filename ? (getShikiLanguage(filename) as never) : "text"}
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
          isStreaming={isStreaming}
          language={filename ? (getShikiLanguage(filename) as never) : "text"}
        />
      </div>
    );
  }

  if (toolCall.name === "apply_patch" && applyPatchPreview) {
    return (
      <div className="space-y-2">
        {filename && (
          <TaskItemFile>
            <FileCodeIcon className="size-3" />
            {filename}
          </TaskItemFile>
        )}
        <CodeBlock
          code={applyPatchPreview}
          enableHighlighting={!isStreaming}
          isStreaming={isStreaming}
          language={filename ? (getShikiLanguage(filename) as never) : "text"}
        />
      </div>
    );
  }

  if (toolCall.name === "apply_patch" && !isStreaming) {
    const patchOutput =
      output && typeof output === "object" && !Array.isArray(output)
        ? (output as Record<string, unknown>)
        : undefined;
    const summary =
      typeof patchOutput?.summary === "string"
        ? patchOutput.summary
        : typeof output === "string"
          ? output
          : null;
    const startLine =
      typeof args.start_line === "number" ? args.start_line : undefined;
    const endLine =
      typeof args.end_line === "number" ? args.end_line : undefined;
    const editCount = Array.isArray(args.edits) ? args.edits.length : undefined;
    const fileIcon = filename
      ? getFileIcon(filename.split(/[\\/]/).pop() ?? "")
      : null;
    return (
      <span className="inline-flex flex-wrap items-center gap-1 text-muted-foreground text-sm">
        <span>{summary || "已编辑"}</span>
        {filename && (
          <TaskItemFile>
            {fileIcon ? (
              <span style={{ color: fileIcon.color }}>{fileIcon.icon}</span>
            ) : (
              <FileCodeIcon className="size-3" />
            )}
            <span>{filename.split(/[\\/]/).pop()}</span>
            {startLine != null && endLine != null && (
              <span className="text-muted-foreground">
                :{startLine}-{endLine}
              </span>
            )}
            {editCount != null && editCount > 1 && (
              <span className="text-muted-foreground">:{editCount} 处编辑</span>
            )}
          </TaskItemFile>
        )}
      </span>
    );
  }

  if (
    toolCall.name === "replace_file" &&
    !(oldContent && newContent) &&
    !isStreaming
  ) {
    const fileIcon = filename
      ? getFileIcon(filename.split(/[\\/]/).pop() ?? "")
      : null;
    const replaceOutput =
      typeof output === "string"
        ? output
        : output && typeof output === "object" && !Array.isArray(output)
          ? (output as Record<string, unknown>)
          : undefined;
    const summary =
      typeof replaceOutput === "string"
        ? replaceOutput
        : typeof (replaceOutput as Record<string, unknown>)?.summary ===
            "string"
          ? (replaceOutput as Record<string, unknown>).summary
          : null;
    return (
      <span className="inline-flex flex-wrap items-center gap-1 text-muted-foreground text-sm">
        <span>{summary || "已更新"}</span>
        {filename && (
          <TaskItemFile>
            {fileIcon ? (
              <span style={{ color: fileIcon.color }}>{fileIcon.icon}</span>
            ) : (
              <FileCodeIcon className="size-3" />
            )}
            <span>{filename.split(/[\\/]/).pop()}</span>
          </TaskItemFile>
        )}
      </span>
    );
  }

  if (toolCall.name === "write_file" && !content && !isStreaming) {
    const fileIcon = filename
      ? getFileIcon(filename.split(/[\\/]/).pop() ?? "")
      : null;
    const writeOutput =
      output && typeof output === "object" && !Array.isArray(output)
        ? (output as Record<string, unknown>)
        : undefined;
    const summary =
      typeof writeOutput?.summary === "string"
        ? writeOutput.summary
        : typeof output === "string"
          ? output
          : null;
    return (
      <span className="inline-flex flex-wrap items-center gap-1 text-muted-foreground text-sm">
        <span>{summary || "已创建"}</span>
        {filename && (
          <TaskItemFile>
            {fileIcon ? (
              <span style={{ color: fileIcon.color }}>{fileIcon.icon}</span>
            ) : (
              <FileCodeIcon className="size-3" />
            )}
            <span>{filename.split(/[\\/]/).pop()}</span>
          </TaskItemFile>
        )}
      </span>
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
    const results =
      output && typeof output === "object"
        ? ((output as Record<string, unknown>)?.results as
            | Array<{
                rank?: number;
                title?: string;
                url?: string;
                snippet?: string;
                source?: string;
                publishedAt?: string;
              }>
            | undefined)
        : undefined;
    if (results && results.length > 0) {
      return (
        <Sources title="搜索的内容">
          {results.map((r, i) => (
            <SourceTag
              key={i}
              href={r.url ?? "#"}
              title={r.title || r.source}
            />
          ))}
        </Sources>
      );
    }
    return <p className="text-xs text-muted-foreground">无搜索结果</p>;
  }

  if (toolCall.name === "fetch_url_content") {
    const documents =
      output && typeof output === "object"
        ? ((output as Record<string, unknown>)?.documents as
            | Array<{ url?: string; title?: string; content?: string }>
            | undefined)
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
  onViewPlan,
}: {
  part: Extract<ContentBlock, { type: "data" }>;
  onViewPlan?: (title: string, markdown: string) => void;
}) {
  const data = part.data;

  if (
    part.dataType === "data-subagent-task" &&
    data &&
    typeof data === "object" &&
    !Array.isArray(data)
  ) {
    return <SubagentTaskCard snapshot={data as SubagentSnapshot} />;
  }

  if (part.dataType === "data-session-state") {
    const agentType = data?.agentType as string | undefined;
    if (!agentType) return null;

    const modeConfig: Record<
      string,
      { label: string; icon: React.ReactNode; color: string }
    > = {
      plan: {
        label: "计划",
        icon: <LightbulbIcon className="size-3.5" />,
        color: "text-amber-600",
      },
      chat: {
        label: "聊天",
        icon: <MessageSquareIcon className="size-3.5" />,
        color: "text-violet-600",
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
        <span className="font-medium text-foreground">
          开始 {config.label} 环节
        </span>
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
      : ([] as string[]);
    const draftMarkdown =
      typeof draft.markdown === "string" ? draft.markdown : "";

    const detailMd =
      draftMarkdown ||
      [
        `# ${draftTitle}`,
        "",
        draftSummary,
        "",
        typeof draft.overview === "string"
          ? `## 概览\n\n${draft.overview}\n`
          : "",
        draftKeySteps.length > 0
          ? [
              "## 关键步骤",
              "",
              ...draftKeySteps.map((s, i) => `${i + 1}. ${s}`),
            ].join("\n")
          : "",
      ].join("\n");

    return (
      <PlanDraftCard
        title={draftTitle}
        summary={draftSummary}
        keySteps={draftKeySteps}
        detailMarkdown={detailMd}
        onViewPlan={onViewPlan}
      />
    );
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
const CONTEXT_COMPRESSION_USAGE_THRESHOLD = 0.8;

const PersonaShell = memo(function PersonaShell({
  state,
  onClick,
}: {
  state: PersonaState;
  onClick?: () => void;
}) {
  return (
    <motion.div
      layout
      layoutId={PERSONA_LAYOUT_ID}
      transition={{ type: "spring", stiffness: 320, damping: 30 }}
      aria-label={`AI status: ${personaLabels[state]}`}
      className={
        onClick
          ? "inline-flex items-center justify-start cursor-pointer"
          : "pointer-events-none inline-flex items-center justify-start"
      }
      onClick={onClick}
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

const DEFAULT_DISABLED_COMPLETION_ACTIONS: Record<
  CompletionActionKey,
  boolean
> = {
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
                  DEFAULT_DISABLED_COMPLETION_ACTIONS[action.key] ||
                    disabledActions?.[action.key] ||
                    !onAction
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
  onCompletionAction?: (
    action: CompletionActionKey,
    message: ChatMessage,
  ) => void;
  disabledActions?: Partial<Record<CompletionActionKey, boolean>>;
}) {
  const [isHovered, setIsHovered] = useState(false);
  const [easterEggState, setEasterEggState] = useState<PersonaState | null>(
    null,
  );

  const activeState: PersonaState =
    easterEggState ?? (isCompleted && isHovered ? "asleep" : state);

  const handlePersonaClick = useCallback(() => {
    if (!isCompleted || state !== "idle" || easterEggState) return;
    const candidates: PersonaState[] = ["listening", "thinking", "speaking"];
    const pick = candidates[Math.floor(Math.random() * candidates.length)];
    setEasterEggState(pick);
    setTimeout(() => setEasterEggState(null), 1000);
  }, [isCompleted, state, easterEggState]);

  return (
    <motion.div
      layout
      className="flex items-center gap-2 py-2"
      onMouseEnter={() => isCompleted && setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <PersonaShell
        state={activeState}
        onClick={
          isCompleted && state === "idle" ? handlePersonaClick : undefined
        }
      />
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

const TextMorph = memo(function TextMorph({
  text,
  className,
  characterClassName,
}: {
  text: string;
  className?: string;
  characterClassName?: string;
}) {
  const uniqueId = useId();
  const previousCharactersRef = useRef<
    Map<string, Array<{ id: string; used: boolean }>>
  >(new Map());

  const characters = useMemo(() => {
    const segmenter =
      typeof Intl !== "undefined" && "Segmenter" in Intl
        ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
        : null;
    const textCharacters = segmenter
      ? Array.from(segmenter.segment(text), ({ segment }) => segment)
      : Array.from(text);
    const previousCharacters = previousCharactersRef.current;
    const nextCharacters = new Map<
      string,
      Array<{ id: string; used: boolean }>
    >();
    const characterCounts = new Map<string, number>();
    const resolvedCharacters = textCharacters.map((character) => {
      const characterKey = character.toLocaleLowerCase();
      const previousMatch = previousCharacters
        .get(characterKey)
        ?.find((item) => !item.used);

      if (previousMatch) {
        previousMatch.used = true;
      }

      const occurrence = (characterCounts.get(characterKey) ?? 0) + 1;
      characterCounts.set(characterKey, occurrence);
      const id =
        previousMatch?.id ?? `${uniqueId}-${characterKey}-${occurrence}`;

      const nextBucket = nextCharacters.get(characterKey) ?? [];
      nextBucket.push({ id, used: false });
      nextCharacters.set(characterKey, nextBucket);

      return {
        id,
        label: character === " " ? "\u00A0" : character,
      };
    });

    previousCharactersRef.current = nextCharacters;
    return resolvedCharacters;
  }, [text, uniqueId]);

  return (
    <div
      className={cn(
        "flex max-w-full flex-wrap items-baseline justify-center text-center leading-tight select-none",
        className,
      )}
    >
      <AnimatePresence initial={false} mode="popLayout">
        {characters.map((character, index) => (
          <motion.span
            key={character.id}
            layoutId={character.id}
            className={cn(
              "inline-block whitespace-pre font-extrabold tracking-normal",
              characterClassName,
            )}
            style={{
              backgroundImage:
                "linear-gradient(135deg, #a855f7 0%, #6366f1 50%, #ec4899 100%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
            initial={{ opacity: 0, y: 14, filter: "blur(8px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, y: -14, filter: "blur(8px)" }}
            transition={{
              delay: Math.min(index * 0.018, 0.22),
              duration: 0.32,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            {character.label}
          </motion.span>
        ))}
      </AnimatePresence>
    </div>
  );
});

const CanvasEdgeGlow = memo(function CanvasEdgeGlow({
  active,
}: {
  active: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [isDarkTheme, setIsDarkTheme] = useState(() =>
    typeof document !== "undefined"
      ? document.documentElement.classList.contains("dark")
      : false,
  );

  useEffect(() => {
    if (typeof document === "undefined") return;

    const root = document.documentElement;
    const updateTheme = () => {
      setIsDarkTheme(root.classList.contains("dark"));
    };
    const observer = new MutationObserver(updateTheme);
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    updateTheme();

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let hue = 0;
    let raf: number;
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.ceil(window.innerWidth * dpr);
      canvas.height = Math.ceil(window.innerHeight * dpr);
      canvas.style.width = `${window.innerWidth}px`;
      canvas.style.height = `${window.innerHeight}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      ctx.clearRect(0, 0, w, h);
      hue = (hue + (isDarkTheme ? 0.5 : 0.16)) % 360;

      const edgeSize = isDarkTheme ? 120 : 88;
      const alpha = isDarkTheme ? 0.6 : 0.16;
      const saturation = isDarkTheme ? 80 : 54;
      const lightness = isDarkTheme ? 60 : 68;

      const topGrad = ctx.createLinearGradient(0, 0, 0, edgeSize);
      topGrad.addColorStop(
        0,
        `hsla(${hue}, ${saturation}%, ${lightness}%, ${alpha})`,
      );
      topGrad.addColorStop(
        0.48,
        `hsla(${hue}, ${saturation}%, ${lightness}%, ${alpha * 0.35})`,
      );
      topGrad.addColorStop(1, "transparent");
      ctx.fillStyle = topGrad;
      ctx.fillRect(0, 0, w, edgeSize);

      const bottomGrad = ctx.createLinearGradient(0, h, 0, h - edgeSize);
      bottomGrad.addColorStop(
        0,
        `hsla(${(hue + 56) % 360}, ${saturation}%, ${lightness}%, ${alpha})`,
      );
      bottomGrad.addColorStop(
        0.48,
        `hsla(${(hue + 56) % 360}, ${saturation}%, ${lightness}%, ${alpha * 0.35})`,
      );
      bottomGrad.addColorStop(1, "transparent");
      ctx.fillStyle = bottomGrad;
      ctx.fillRect(0, h - edgeSize, w, edgeSize);

      const leftGrad = ctx.createLinearGradient(0, 0, edgeSize, 0);
      leftGrad.addColorStop(
        0,
        `hsla(${(hue + 112) % 360}, ${saturation}%, ${lightness}%, ${alpha})`,
      );
      leftGrad.addColorStop(
        0.48,
        `hsla(${(hue + 112) % 360}, ${saturation}%, ${lightness}%, ${alpha * 0.35})`,
      );
      leftGrad.addColorStop(1, "transparent");
      ctx.fillStyle = leftGrad;
      ctx.fillRect(0, 0, edgeSize, h);

      const rightGrad = ctx.createLinearGradient(w, 0, w - edgeSize, 0);
      rightGrad.addColorStop(
        0,
        `hsla(${(hue + 168) % 360}, ${saturation}%, ${lightness}%, ${alpha})`,
      );
      rightGrad.addColorStop(
        0.48,
        `hsla(${(hue + 168) % 360}, ${saturation}%, ${lightness}%, ${alpha * 0.35})`,
      );
      rightGrad.addColorStop(1, "transparent");
      ctx.fillStyle = rightGrad;
      ctx.fillRect(w - edgeSize, 0, edgeSize, h);

      raf = requestAnimationFrame(draw);
    };

    resize();
    window.addEventListener("resize", resize);
    draw();
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, [isDarkTheme]);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 pointer-events-none z-[60] transition-opacity duration-500"
      style={{
        mixBlendMode: isDarkTheme ? "screen" : "multiply",
        opacity: active ? 1 : 0,
      }}
    />
  );
});

const SuperCodeTitle = memo(function SuperCodeTitle({
  morphText,
}: {
  morphText?: string;
}) {
  return (
    <TextMorph
      text={morphText ?? "SuperCode"}
      characterClassName={
        morphText ? "text-4xl sm:text-5xl" : "text-6xl sm:text-7xl"
      }
    />
  );
});

const EmptyHeroState = memo(function EmptyHeroState({
  state,
  isHandling,
  children,
}: {
  state: PersonaState;
  isHandling?: boolean;
  children: React.ReactNode;
}) {
  const [idleMorphText, setIdleMorphText] = useState<string | null>(null);

  useEffect(() => {
    if (isHandling) {
      setIdleMorphText(null);
      return;
    }

    const morphTimer = setTimeout(() => {
      setIdleMorphText("Hi, How can SC Help you?");
    }, 5000);

    const revertTimer = setTimeout(() => {
      setIdleMorphText(null);
    }, 15000);

    return () => {
      clearTimeout(morphTimer);
      clearTimeout(revertTimer);
    };
  }, [isHandling]);

  const effectiveMorphText = isHandling
    ? "SC is Handling your request~"
    : (idleMorphText ?? undefined);

  return (
    <motion.div
      key="empty-hero"
      className="h-full flex flex-col min-w-0 border-r relative overflow-hidden"
      initial={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.35, ease: [0.4, 0, 0.2, 1] }}
    >
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse at 50% 35%, rgba(168,85,247,0.06) 0%, transparent 65%)",
        }}
      />
      <div className="flex-1 flex items-center justify-center relative px-4">
        <motion.div
          className="flex w-full flex-col items-center gap-5"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        >
          <motion.div>
            <Persona
              variant="glint"
              state={state}
              className="size-24 drop-shadow-[0_0_28px_rgba(168,85,247,0.2)]"
            />
          </motion.div>
          <div className={cn("flex min-h-[9rem] w-full flex-col items-center justify-start", CHAT_HERO_MAX_WIDTH)}>
            <SuperCodeTitle morphText={effectiveMorphText} />
            {!effectiveMorphText && (
              <motion.p
                className="text-muted-foreground text-sm tracking-wide"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.7, duration: 0.5 }}
              >
                让 AI 将想法转化为代码
              </motion.p>
            )}
          </div>
          <div className={cn("mt-3 w-full", CHAT_CONTENT_MAX_WIDTH)}>{children}</div>
        </motion.div>
      </div>
    </motion.div>
  );
});

const normalizeThinkingStartTime = (startTime?: number) => {
  if (typeof startTime !== "number" || !Number.isFinite(startTime) || startTime <= 0) {
    return undefined;
  }
  return startTime < 1_000_000_000_000 ? startTime * 1000 : startTime;
};

const formatThinkingDuration = (seconds: number) => {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  if (totalSeconds < 60) {
    return `${totalSeconds}秒`;
  }
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  return `${minutes}分${remainingSeconds.toString().padStart(2, "0")}秒`;
};

const ThinkingTimeHeader = memo(function ThinkingTimeHeader({
  thinkingTime,
  startTime,
  isActive,
}: {
  thinkingTime?: number;
  startTime?: number;
  isActive: boolean;
}) {
  const normalizedStartTime = normalizeThinkingStartTime(startTime);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!isActive || normalizedStartTime === undefined) {
      return;
    }
    setNow(Date.now());
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isActive, normalizedStartTime]);

  const displaySeconds =
    isActive && normalizedStartTime !== undefined
      ? (now - normalizedStartTime) / 1000
      : thinkingTime ?? 0;

  return (
    <div className="mb-3 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>已思考 {formatThinkingDuration(displaySeconds)}</span>
      </div>
      <div className="h-px bg-border" />
    </div>
  );
});

const UserMessageActions = memo(function UserMessageActions({
  msg,
  onEditMessage,
}: {
  msg: ChatMessage;
  onEditMessage?: (content: string) => void;
}) {
  if (!msg.content) return null;
  return (
    <motion.div
      className="absolute bottom-1.5 right-1.5 z-10 flex items-center gap-0.5 rounded-md bg-background/80 backdrop-blur-sm px-0.5 py-0.5 shadow-sm border border-border/40"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
    >
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
              onClick={() => navigator.clipboard.writeText(msg.content)}
            >
              <Copy className="h-2.5 w-2.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="bottom"><p>复制</p></TooltipContent>
        </Tooltip>
      </TooltipProvider>
      {onEditMessage && (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
                onClick={() => onEditMessage(msg.content)}
              >
                <Pencil className="h-2.5 w-2.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom"><p>编辑并重新发送</p></TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}
    </motion.div>
  );
});

const MessageList = memo(function MessageList({
  sessionId,
  isLoading,
  messages,
  codeChanges,
  onResolveDeleteConfirmation,
  onResolveGitConfirmation,
  onResolveConnectInput,
  onResolvePlanQuestionsInput,
  onViewPlan,
  onCompletionAction,
  activeCompletionAction,
  compressedMessageIds,
  canCompress,
  onEditMessage,
  subagentMessages = [],
  onOpenSubagentLog,
  thinkingRendering = "text",
  finalAnswerRendering = "markdown",
}: {
  sessionId: string | null;
  isLoading: boolean;
  messages: ChatMessage[];
  codeChanges: CodeChangeRecord[];
  onResolveDeleteConfirmation: (toolCallId: string, approved: boolean) => void;
  onResolveGitConfirmation: (
    toolCallId: string,
    type: "commit" | "tag",
    approved: boolean,
  ) => void;
  onResolveConnectInput?: (
    toolCallId: string,
    values: Record<string, string>,
  ) => void;
  onResolvePlanQuestionsInput?: (
    toolCallId: string,
    answers: QuizSubmission,
  ) => void | Promise<void>;
  onViewPlan?: (title: string, markdown: string) => void;
  onCompletionAction?: (
    action: CompletionActionKey,
    message: ChatMessage,
  ) => void;
  activeCompletionAction?: {
    messageId: string;
    action: CompletionActionKey;
  } | null;
  compressedMessageIds: Set<string>;
  canCompress: boolean;
  onEditMessage?: (content: string) => void;
  subagentMessages?: ChatMessage[];
  onOpenSubagentLog?: (parentToolCallId: string) => void;
  thinkingRendering?: "text" | "markdown";
  finalAnswerRendering?: "markdown" | "html";
}) {
  const [taskOpenState, setTaskOpenState] = useState<Record<string, boolean>>(
    {},
  );
  const [hoveredMsgId, setHoveredMsgId] = useState<string | null>(null);

  const getMessageToolCalls = useCallback((message: ChatMessage) => {
    const partToolCalls =
      message.parts
        ?.filter(
          (part): part is Extract<ContentBlock, { type: "tool_call" }> =>
            part.type === "tool_call",
        )
        .map((part) => part.toolCall) ?? [];
    return message.toolCalls?.length ? message.toolCalls : partToolCalls;
  }, []);

  const buildAssistantDisplayMessage = useCallback(
    (message: ChatMessage): ChatMessage => {
      if (message.role !== "assistant") {
        return message;
      }
      if (Array.isArray(message.parts) && message.parts.length > 0) {
        return message;
      }

      const thoughtText = normalizeThoughtText(message.thoughts);
      const toolCalls = getMessageToolCalls(message);
      if (!thoughtText && toolCalls.length === 0) {
        return message;
      }

      const parts: ContentBlock[] = [];
      if (thoughtText) {
        parts.push({ type: "thinking", text: thoughtText });
      }
      for (const toolCall of toolCalls) {
        parts.push({ type: "tool_call", toolCall });
      }
      if (message.content) {
        parts.push({ type: "text", text: message.content });
      }

      return {
        ...message,
        thoughts: thoughtText,
        toolCalls,
        parts,
      };
    },
    [getMessageToolCalls],
  );

  const latestRunningToolId = useMemo(() => {
    for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
      const toolCalls = getMessageToolCalls(messages[messageIndex]);
      for (let toolIndex = toolCalls.length - 1; toolIndex >= 0; toolIndex -= 1) {
        if (toolCalls[toolIndex].state === "running") {
          return toolCalls[toolIndex].id;
        }
      }
    }
    return null;
  }, [getMessageToolCalls, messages]);

  useEffect(() => {
    setTaskOpenState((prev) => {
      let changed = false;
      const next = { ...prev };

      for (const message of messages) {
        for (const toolCall of getMessageToolCalls(message)) {
          if (latestRunningToolId && toolCall.id === latestRunningToolId) {
            if (next[toolCall.id] !== true) {
              next[toolCall.id] = true;
              changed = true;
            }
            continue;
          }

          const shouldCollapseBeforeNextTool =
            latestRunningToolId !== null &&
            (toolCall.state === "completed" ||
              toolCall.state === "output-available" ||
              toolCall.state === "output-denied" ||
              toolCall.state === "error");
          const shouldAutoCollapse =
            shouldCollapseBeforeNextTool ||
            (toolCall.name === "save_plan" &&
              (toolCall.state === "completed" ||
                toolCall.state === "output-available"));
          if (shouldAutoCollapse && next[toolCall.id] !== false) {
            next[toolCall.id] = false;
            changed = true;
          }
        }
      }

      return changed ? next : prev;
    });
  }, [getMessageToolCalls, latestRunningToolId, messages]);

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
      tc.name === "delegate_code_exploration" ||
      tc.inputRequest?.kind === "plan_questions";
    const toolTitle = `${getToolTitle(tc.name, tc.arguments ?? {})} · ${statusLabel}`;
    const hasControlledOpen =
      latestRunningToolId !== null ||
      Object.prototype.hasOwnProperty.call(taskOpenState, tc.id);
    const controlledOpen =
      latestRunningToolId !== null && tc.id !== latestRunningToolId
        ? false
        : (taskOpenState[tc.id] ?? shouldOpen);

    return (
      <Task
        key={tc.id}
        defaultOpen={shouldOpen}
        {...(hasControlledOpen
          ? {
              open: controlledOpen,
              onOpenChange: (open: boolean) =>
                setTaskOpenState((prev) => ({ ...prev, [tc.id]: open })),
            }
          : {})}
      >
        <TaskTrigger
          title={
            tc.state === "running" && isLastRunning ? (
              <Shimmer duration={1}>{toolTitle}</Shimmer>
            ) : (
              toolTitle
            )
          }
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
              subagentMessages={subagentMessages}
              onOpenSubagentLog={onOpenSubagentLog}
              replaceCompletedPlanQuestionsWithLoading={
                options?.replaceCompletedPlanQuestionsWithLoading
              }
            />
          </TaskItem>
        </TaskContent>
      </Task>
    );
  };

  const renderParallelGroupedToolCalls = (
    toolCalls: ToolCallRecord[],
    lastRunningIdx: number,
  ) => {
    const items: React.ReactNode[] = [];
    let i = 0;
    while (i < toolCalls.length) {
      const tc = toolCalls[i];
      if (tc.name === "read_file") {
        const readFiles: { tc: ToolCallRecord; idx: number }[] = [];
        let j = i;
        while (j < toolCalls.length && toolCalls[j].name === "read_file") {
          readFiles.push({ tc: toolCalls[j], idx: j });
          j++;
        }
        if (readFiles.length === 1) {
          const rf = readFiles[0];
          items.push(renderToolCall(rf.tc, rf.idx === lastRunningIdx));
        } else {
          const anyRunning = readFiles.some((rf) => rf.tc.state === "running");
          const allCompleted = readFiles.every(
            (rf) =>
              rf.tc.state === "completed" || rf.tc.state === "output-available",
          );
          items.push(
            <Task key={`read-file-group-${i}`} defaultOpen={anyRunning}>
              <TaskTrigger
                title={
                  anyRunning ? (
                    <Shimmer duration={1}>
                      {`正在阅读 ${readFiles.length} 个文件 · 执行中`}
                    </Shimmer>
                  ) : (
                    `已阅读 ${readFiles.length} 个文件 · ${allCompleted ? "已完成" : "执行中"}`
                  )
                }
                icon={<FileSearchIcon className="size-4" />}
              />
              <TaskContent>
                <TaskItem>
                  <span className="inline-flex flex-wrap items-center gap-1">
                    <span>{anyRunning ? "正在阅读" : "已阅读"}</span>
                    {readFiles.map((rf, rfi) => {
                      const rfArgs = rf.tc.arguments || {};
                      const rfFilename = (rfArgs.filename ||
                        rfArgs.path ||
                        rfArgs.file_path) as string | undefined;
                      const leaf = rfFilename?.split(/[\\/]/).pop();
                      const fileIcon = leaf ? getFileIcon(leaf) : null;
                      return (
                        <TaskItemFile key={rfi}>
                          {fileIcon ? (
                            <span style={{ color: fileIcon.color }}>
                              {fileIcon.icon}
                            </span>
                          ) : (
                            <FileCodeIcon className="size-3" />
                          )}
                          <span>{leaf || (rfFilename ?? "...")}</span>
                        </TaskItemFile>
                      );
                    })}
                  </span>
                </TaskItem>
              </TaskContent>
            </Task>,
          );
        }
        i = j;
      } else {
        items.push(renderToolCall(tc, i === lastRunningIdx));
        i++;
      }
    }
    return items;
  };

  const renderLegacyAssistant = (msg: ChatMessage, isLast: boolean) => {
    if (isLast) {
      const thoughtText = normalizeThoughtText(msg.thoughts);
      const hasThoughts = Boolean(thoughtText);
      const hasToolCalls = (msg.toolCalls?.length ?? 0) > 0;

      const hasErrorInThoughts = isLoading && hasThoughts && ERROR_LINE_RE.test(thoughtText);

      return (
        <>
          {hasThoughts ? (
            <ChainOfThought defaultOpen={isLoading || hasErrorInThoughts}>
              <ChainOfThoughtHeader>
                <span className={hasErrorInThoughts ? "text-destructive" : ""}>
                  {hasErrorInThoughts ? "请求出错" : "思考过程"}
                </span>
              </ChainOfThoughtHeader>
              <ChainOfThoughtContent>
                {(() => {
                  const segments = parseThoughtErrorSegments(thoughtText);
                  const hasError = segments.some((s) => s.type === "error");
                  if (hasError) {
                    return (
                      <AnimatePresence>
                        {segments.map((seg, si) => {
                          if (seg.type === "error") {
                            return (
                              <ErrorChainBlock
                                key={`legacy-error-block`}
                                errors={seg.value.errors}
                                retryCount={seg.value.retryCount}
                                maxRetries={seg.value.maxRetries}
                                retrying={seg.value.retrying}
                                resolved={
                                  seg.value.resolved ||
                                  (!isLoading && seg.value.retrying)
                                }
                              />
                            );
                          }
                          return (
                            <ChainOfThoughtStep
                              key={`legacy-thinking-${si}`}
                              label={<MessageResponse>{seg.value}</MessageResponse>}
                              status={isLoading ? "active" : "complete"}
                            />
                          );
                        })}
                      </AnimatePresence>
                    );
                  }
                  return (
                    <ChainOfThoughtStep
                      label={<MessageResponse>{thoughtText}</MessageResponse>}
                      status={isLoading ? "active" : "complete"}
                    />
                  );
                })()}
                {hasToolCalls ? (
                  <div className="space-y-2">
                    {(() => {
                      const lastRunningIdx = [
                        ...(msg.toolCalls ?? []),
                      ].findLastIndex((tc) => tc.state === "running");
                      return renderParallelGroupedToolCalls(
                        msg.toolCalls ?? [],
                        lastRunningIdx,
                      );
                    })()}
                  </div>
                ) : null}
              </ChainOfThoughtContent>
            </ChainOfThought>
          ) : hasToolCalls ? (
            <div className="space-y-2">
              {(() => {
                const lastRunningIdx = [...(msg.toolCalls ?? [])].findLastIndex(
                  (tc) => tc.state === "running",
                );
                return renderParallelGroupedToolCalls(
                  msg.toolCalls ?? [],
                  lastRunningIdx,
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
          const lastRunningIdx = [...(msg.toolCalls ?? [])].findLastIndex(
            (tc) => tc.state === "running",
          );
          return renderParallelGroupedToolCalls(
            msg.toolCalls ?? [],
            lastRunningIdx,
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
          const agentType = (part.data as Record<string, unknown> | undefined)
            ?.agentType as string | undefined;
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

    const thinkingBeforeText = (g: (typeof groups)[number]) =>
      g.type === "cot" || g.type === "tools";
    for (let gi = groups.length - 1; gi > 0; gi--) {
      const group = groups[gi];
      if (!thinkingBeforeText(group)) continue;
      let targetIdx = -1;
      for (let j = gi - 1; j >= 0; j--) {
        if (thinkingBeforeText(groups[j])) {
          targetIdx = j;
          break;
        }
      }
      if (targetIdx === -1) continue;
      const target = groups[targetIdx];
      const merged = [...target.blocks, ...group.blocks];
      const hasThinking = merged.some(
        (b) => b.type === "thinking" && b.text.trim(),
      );
      groups[targetIdx] = hasThinking
        ? { type: "cot", blocks: merged, hasThinking: true }
        : { type: "tools", blocks: merged };
      groups.splice(gi, 1);
    }

    for (const group of groups) {
      if (group.type !== "cot") {
        continue;
      }
      const seenThinkingKeys = new Set<string>();
      group.blocks = group.blocks.filter((block) => {
        if (block.type !== "thinking") {
          return true;
        }
        const thoughtKey = getThoughtTextKey(normalizeThoughtText(block.text));
        if (!thoughtKey) {
          return false;
        }
        if (seenThinkingKeys.has(thoughtKey)) {
          return false;
        }
        seenThinkingKeys.add(thoughtKey);
        return true;
      });
    }

    const activeCotGroupIdx =
      isLast && isLoading && groups[groups.length - 1]?.type === "cot"
        ? groups.length - 1
        : -1;

    return groups.map((group, gi) => {
      if (group.type === "text") {
        const isStreamingText = isLast && isLoading && gi === groups.length - 1;
        return group.block.text
          ? renderFinalAnswerContent(group.block.text, citations, {
              className: isStreamingText ? "streaming-tail-fade" : undefined,
              isAnimating: isStreamingText,
              key: `text-${gi}`,
              finalAnswerRendering,
            })
          : null;
      }

      if (group.type === "data") {
        return (
          <DataPartView
            key={`data-${gi}`}
            part={group.block}
            onViewPlan={onViewPlan}
          />
        );
      }

      if (group.type === "tools") {
        const lastRunningIdx = group.blocks.findLastIndex(
          (b) => b.type === "tool_call" && b.toolCall.state === "running",
        );
        const toolItems: React.ReactNode[] = [];
        let ti = 0;
        while (ti < group.blocks.length) {
          const block = group.blocks[ti];
          if (
            block.type === "tool_call" &&
            block.toolCall.name === "read_file"
          ) {
            const readFiles: {
              block: Extract<ContentBlock, { type: "tool_call" }>;
              idx: number;
            }[] = [];
            let tj = ti;
            while (
              tj < group.blocks.length &&
              group.blocks[tj].type === "tool_call" &&
              (group.blocks[tj] as Extract<ContentBlock, { type: "tool_call" }>)
                .toolCall.name === "read_file"
            ) {
              readFiles.push({
                block: group.blocks[tj] as Extract<
                  ContentBlock,
                  { type: "tool_call" }
                >,
                idx: tj,
              });
              tj++;
            }
            if (readFiles.length === 1) {
              const rf = readFiles[0];
              toolItems.push(
                renderToolCall(rf.block.toolCall, rf.idx === lastRunningIdx),
              );
            } else {
              const anyRunning = readFiles.some(
                (rf) => rf.block.toolCall.state === "running",
              );
              const allCompleted = readFiles.every(
                (rf) =>
                  rf.block.toolCall.state === "completed" ||
                  rf.block.toolCall.state === "output-available",
              );
              toolItems.push(
                <Task
                  key={`read-file-group-${gi}-${ti}`}
                  defaultOpen={anyRunning}
                >
                  <TaskTrigger
                    title={
                      anyRunning ? (
                        <Shimmer duration={1}>
                          {`正在阅读 ${readFiles.length} 个文件 · 执行中`}
                        </Shimmer>
                      ) : (
                        `已阅读 ${readFiles.length} 个文件 · ${allCompleted ? "已完成" : "执行中"}`
                      )
                    }
                    icon={<FileSearchIcon className="size-4" />}
                  />
                  <TaskContent>
                    <TaskItem>
                      <span className="inline-flex flex-wrap items-center gap-1">
                        <span>{anyRunning ? "正在阅读" : "已阅读"}</span>
                        {readFiles.map((rf, rfi) => {
                          const rfArgs = rf.block.toolCall.arguments || {};
                          const rfFilename = (rfArgs.filename ||
                            rfArgs.path ||
                            rfArgs.file_path) as string | undefined;
                          const leaf = rfFilename?.split(/[\\/]/).pop();
                          const fileIcon = leaf ? getFileIcon(leaf) : null;
                          return (
                            <TaskItemFile key={rfi}>
                              {fileIcon ? (
                                <span style={{ color: fileIcon.color }}>
                                  {fileIcon.icon}
                                </span>
                              ) : (
                                <FileCodeIcon className="size-3" />
                              )}
                              <span>{leaf || (rfFilename ?? "...")}</span>
                            </TaskItemFile>
                          );
                        })}
                      </span>
                    </TaskItem>
                  </TaskContent>
                </Task>,
              );
            }
            ti = tj;
          } else if (block.type === "tool_call") {
            toolItems.push(
              renderToolCall(block.toolCall, ti === lastRunningIdx),
            );
            ti++;
          } else {
            ti++;
          }
        }
        return (
          <div key={`tools-${gi}`} className="space-y-2">
            {toolItems}
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
              (b) => b.type === "tool_call" && b.toolCall.state === "running",
            )
        : undefined;
      const isDraftingPlan = group.blocks.some(
        (block) =>
          block.type === "tool_call" &&
          block.toolCall.name === "save_plan" &&
          block.toolCall.state === "running",
      );
      const hasErrorThinking = isActive && group.blocks.some(
        (block) =>
          block.type === "thinking" &&
          ERROR_LINE_RE.test(normalizeThoughtText(block.text)),
      );
      const activeLabel = lastRunningTool
        ? getToolTitle(
            lastRunningTool.toolCall.name,
            lastRunningTool.toolCall.arguments ?? {},
          )
        : hasErrorThinking
          ? "请求出错"
          : isActive
            ? "正在思考..."
            : "思考过程";
      return (
        <ChainOfThought
          key={`cot-${gi}`}
          defaultOpen={isActive || hasContent || hasErrorThinking}
          autoOpen={isActive || hasAutoOpenTool || hasErrorThinking}
          autoCloseDelay={autoCloseDelay}
        >
          <ChainOfThoughtHeader>
            {isActive && !hasErrorThinking ? (
              <Shimmer duration={1}>{activeLabel}</Shimmer>
            ) : (
              <span className={hasErrorThinking ? "text-destructive" : ""}>
                {activeLabel}
              </span>
            )}
          </ChainOfThoughtHeader>
          <ChainOfThoughtContent>
            {(() => {
              const lastRunningIdx = isActive
                ? group.blocks.findLastIndex(
                    (b) =>
                      (b.type === "tool_call" &&
                        b.toolCall.state === "running") ||
                      b.type === "thinking",
                  )
                : -1;
              const rendered: React.ReactNode[] = [];
              let lastRenderedThinkingKey = "";
              let i = 0;
              while (i < group.blocks.length) {
                const block = group.blocks[i];
                if (block.type === "thinking") {
                  const thoughtText = normalizeThoughtText(block.text);
                  const thoughtKey = getThoughtTextKey(thoughtText);
                  if (thoughtText && thoughtKey !== lastRenderedThinkingKey) {
                    lastRenderedThinkingKey = thoughtKey;
                    const segments = parseThoughtErrorSegments(thoughtText);
                    const hasError = segments.some((s) => s.type === "error");
                    if (hasError) {
                      for (let si = 0; si < segments.length; si++) {
                        const seg = segments[si];
                        if (seg.type === "error") {
                          const resolved =
                            seg.value.resolved ||
                            (!isActive && seg.value.retrying);
                          rendered.push(
                            <ErrorChainBlock
                              key={`error-wrapper-${gi}-${i}`}
                              errors={seg.value.errors}
                              retryCount={seg.value.retryCount}
                              maxRetries={seg.value.maxRetries}
                              retrying={seg.value.retrying}
                              resolved={resolved}
                            />,
                          );
                        } else {
                          rendered.push(
                            <ChainOfThoughtStep
                              key={`thinking-${gi}-${i}-${si}`}
                              label={
                                thinkingRendering === "markdown" ? (
                                  renderCitationMessage(seg.value, citations)
                                ) : (
                                  <span className="whitespace-pre-wrap break-words">
                                    {seg.value}
                                  </span>
                                )
                              }
                              status={i === lastRunningIdx && isActive ? "active" : "complete"}
                            />,
                          );
                        }
                      }
                    } else {
                      const thinkingLabel =
                        thinkingRendering === "markdown" ? (
                          renderCitationMessage(thoughtText, citations)
                        ) : (
                          <span className="whitespace-pre-wrap break-words">
                            {thoughtText}
                          </span>
                        );
                      rendered.push(
                        <ChainOfThoughtStep
                          key={`thinking-${gi}-${i}`}
                          label={thinkingLabel}
                          status={
                            i === lastRunningIdx && isActive
                              ? "active"
                              : "complete"
                          }
                        />,
                      );
                    }
                  }
                  i++;
                } else if (
                  block.type === "tool_call" &&
                  block.toolCall.name === "read_file"
                ) {
                  const readFiles: {
                    block: Extract<ContentBlock, { type: "tool_call" }>;
                    idx: number;
                  }[] = [];
                  let j = i;
                  while (
                    j < group.blocks.length &&
                    group.blocks[j].type === "tool_call" &&
                    (
                      group.blocks[j] as Extract<
                        ContentBlock,
                        { type: "tool_call" }
                      >
                    ).toolCall.name === "read_file"
                  ) {
                    readFiles.push({
                      block: group.blocks[j] as Extract<
                        ContentBlock,
                        { type: "tool_call" }
                      >,
                      idx: j,
                    });
                    j++;
                  }
                  if (readFiles.length === 1) {
                    const rf = readFiles[0];
                    rendered.push(
                      <div key={`tool-${gi}-${rf.idx}`}>
                        {renderToolCall(
                          rf.block.toolCall,
                          rf.idx === lastRunningIdx,
                          {
                            replaceCompletedPlanQuestionsWithLoading:
                              isDraftingPlan &&
                              (rf.block.toolCall.inputRequest?.kind ===
                                "plan_questions" ||
                                rf.block.toolCall.name ===
                                  "ask_plan_questions"),
                          },
                        )}
                      </div>,
                    );
                  } else {
                    const allCompleted = readFiles.every(
                      (rf) =>
                        rf.block.toolCall.state === "completed" ||
                        rf.block.toolCall.state === "output-available",
                    );
                    const anyRunning = readFiles.some(
                      (rf) => rf.block.toolCall.state === "running",
                    );
                    const isLastInGroup = readFiles.some(
                      (rf) => rf.idx === lastRunningIdx,
                    );
                    const status: "complete" | "active" | "pending" =
                      anyRunning && isLastInGroup && isActive
                        ? "active"
                        : allCompleted
                          ? "complete"
                          : "active";
                    rendered.push(
                      <ChainOfThoughtStep
                        key={`read-file-group-${gi}-${i}`}
                        icon={FileSearchIcon}
                        label={
                          <span className="inline-flex flex-wrap items-center gap-1">
                            <span>{anyRunning ? "正在阅读" : "已阅读"}</span>
                            {readFiles.map((rf, rfi) => {
                              const rfArgs = rf.block.toolCall.arguments || {};
                              const rfFilename = (rfArgs.filename ||
                                rfArgs.path ||
                                rfArgs.file_path) as string | undefined;
                              const leaf = rfFilename?.split(/[\\/]/).pop();
                              const fileIcon = leaf ? getFileIcon(leaf) : null;
                              return (
                                <TaskItemFile key={rfi}>
                                  {fileIcon ? (
                                    <span style={{ color: fileIcon.color }}>
                                      {fileIcon.icon}
                                    </span>
                                  ) : (
                                    <FileCodeIcon className="size-3" />
                                  )}
                                  <span>{leaf || (rfFilename ?? "...")}</span>
                                </TaskItemFile>
                              );
                            })}
                          </span>
                        }
                        status={status}
                      />,
                    );
                  }
                  i = j;
                } else if (block.type === "tool_call") {
                  rendered.push(
                    <div key={`tool-${gi}-${i}`}>
                      {renderToolCall(block.toolCall, i === lastRunningIdx, {
                        replaceCompletedPlanQuestionsWithLoading:
                          isDraftingPlan &&
                          (block.toolCall.inputRequest?.kind ===
                            "plan_questions" ||
                            block.toolCall.name === "ask_plan_questions"),
                      })}
                    </div>,
                  );
                  i++;
                } else if (
                  block.dataType === "data-session-state"
                ) {
                  rendered.push(
                    <div key={`session-state-${gi}-${i}`}>
                      <DataPartView part={block} />
                    </div>,
                  );
                  i++;
                } else {
                  i++;
                }
              }
              return <AnimatePresence>{rendered}</AnimatePresence>;
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
        const displayMessage = buildAssistantDisplayMessage(msg);
        const isLast = idx === messages.length - 1;
        const isLastAssistant = idx === lastAssistantIdx;
        const isActiveAssistant = isLastAssistant && isLoading;
        const showThinkingTime =
          msg.role === "assistant" &&
          (typeof msg.thinkingTime === "number" ||
            (isActiveAssistant && typeof msg.startTime === "number"));
        const showInlineActions =
          Boolean(onCompletionAction) &&
          msg.role === "assistant" &&
          !isLastAssistant;
        const isCompressing =
          activeCompletionAction?.action === "compress" &&
          activeCompletionAction.messageId === msg.id;
        const isCompressed = compressedMessageIds.has(msg.id ?? "");
        const compressStatus: "compressing" | "compressed" | null =
          isCompressing ? "compressing" : isCompressed ? "compressed" : null;
        const msgToolCallIds = new Set([
          ...(msg.toolCalls?.map((tc) => tc.id) ?? []),
          ...(msg.parts
            ?.filter((p) => p.type === "tool_call")
            .map(
              (p) =>
                (p as { type: "tool_call"; toolCall: { id: string } }).toolCall
                  .id,
            ) ?? []),
        ]);
        const msgCodeChanges = codeChanges.filter(
          (c) => c.toolCallId && msgToolCallIds.has(c.toolCallId),
        );
        return (
          <Message
            key={msg.id || idx}
            from={msg.role}
            data-message-id={msg.id}
            onMouseEnter={() => msg.id && setHoveredMsgId(msg.id)}
            onMouseLeave={() => setHoveredMsgId(null)}
          >
            <MessageContent>
              {showThinkingTime && (
                <ThinkingTimeHeader
                  thinkingTime={msg.thinkingTime}
                  startTime={msg.startTime}
                  isActive={isActiveAssistant}
                />
              )}
              {msg.role === "assistant" &&
                (displayMessage.parts?.length
                  ? renderPartsAssistant(displayMessage, isLast)
                  : renderLegacyAssistant(displayMessage, isLast))}
              {msg.role === "user" && msg.content
                ? renderFinalAnswerContent(msg.content, new Map(), {
                    finalAnswerRendering: "markdown",
                  })
                : null}
              {msg.role === "assistant" && !displayMessage.parts?.length && msg.content
                ? renderFinalAnswerContent(msg.content, new Map(), {
                    className:
                      isLast && isLoading ? "streaming-tail-fade" : undefined,
                    isAnimating: isLast && isLoading,
                    finalAnswerRendering,
                  })
                : null}
            </MessageContent>
            {msg.role === "user" && (
              <AnimatePresence>
                {hoveredMsgId === msg.id && (
                  <UserMessageActions key="actions" msg={msg} onEditMessage={onEditMessage} />
                )}
              </AnimatePresence>
            )}
            {msg.role === "assistant" &&
              msgCodeChanges.length > 0 &&
              !(isLastAssistant && isLoading) && (
                <TurnFileChangeList changes={msgCodeChanges} />
              )}
            {msg.role === "assistant" && compressStatus && (
              <CompressStatusLine status={compressStatus} />
            )}
            {showInlineActions && (
              <CompletionActionToolbar
                disabledActions={{
                  copy: !msg.content.trim(),
                  compress:
                    isLoading ||
                    Boolean(activeCompletionAction) ||
                    isCompressed ||
                    !canCompress,
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
  codeChanges,
  onResolveDeleteConfirmation,
  onResolveGitConfirmation,
  onResolveConnectInput,
  onResolvePlanQuestionsInput,
  onViewPlan,
  personaState,
  onCompletionAction,
  activeCompletionAction,
  canCompress,
  onEditMessage,
  subagentMessages = [],
  onOpenSubagentLog,
  thinkingRendering = "text",
  finalAnswerRendering = "markdown",
}: {
  sessionId: string | null;
  isLoading: boolean;
  messages: ChatMessage[];
  codeChanges: CodeChangeRecord[];
  onResolveDeleteConfirmation: (toolCallId: string, approved: boolean) => void;
  onResolveGitConfirmation: (
    toolCallId: string,
    type: "commit" | "tag",
    approved: boolean,
  ) => void;
  onResolveConnectInput?: (
    toolCallId: string,
    values: Record<string, string>,
  ) => void;
  onResolvePlanQuestionsInput?: (
    toolCallId: string,
    answers: QuizSubmission,
  ) => void | Promise<void>;
  onViewPlan?: (title: string, markdown: string) => void;
  personaState: PersonaState;
  onCompletionAction?: (
    action: CompletionActionKey,
    message: ChatMessage,
  ) => void;
  activeCompletionAction?: {
    messageId: string;
    action: CompletionActionKey;
  } | null;
  canCompress: boolean;
  onEditMessage?: (content: string) => void;
  subagentMessages?: ChatMessage[];
  onOpenSubagentLog?: (parentToolCallId: string) => void;
  thinkingRendering?: "text" | "markdown";
  finalAnswerRendering?: "markdown" | "html";
}) {
  const [compressedMessageIds, setCompressedMessageIds] = useState<Set<string>>(
    new Set(),
  );

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

  const lastAssistantMessage =
    [...messages].reverse().find((message) => message.role === "assistant") ??
    null;

  const lastCompressStatus: "compressing" | "compressed" | null =
    activeCompletionAction?.action === "compress" &&
    activeCompletionAction.messageId === lastAssistantMessage?.id
      ? "compressing"
      : lastAssistantMessage?.id &&
          compressedMessageIds.has(lastAssistantMessage.id)
        ? "compressed"
        : null;

  return (
    <>
      <MessageList
        sessionId={sessionId}
        isLoading={isLoading}
        messages={messages}
        codeChanges={codeChanges}
        onResolveDeleteConfirmation={onResolveDeleteConfirmation}
        onResolveGitConfirmation={onResolveGitConfirmation}
        onResolveConnectInput={onResolveConnectInput}
        onResolvePlanQuestionsInput={onResolvePlanQuestionsInput}
        onViewPlan={onViewPlan}
        onCompletionAction={onCompletionAction}
        activeCompletionAction={activeCompletionAction}
        compressedMessageIds={compressedMessageIds}
        canCompress={canCompress}
        onEditMessage={onEditMessage}
        subagentMessages={subagentMessages}
        onOpenSubagentLog={onOpenSubagentLog}
        thinkingRendering={thinkingRendering}
        finalAnswerRendering={finalAnswerRendering}
      />
      <PersonaRail
        state={personaState}
        isCompleted={!isLoading && messages.length > 0}
        message={lastAssistantMessage}
        onCompletionAction={onCompletionAction}
        disabledActions={{
          copy: !lastAssistantMessage?.content?.trim(),
          compress:
            isLoading ||
            Boolean(activeCompletionAction) ||
            Boolean(lastCompressStatus) ||
            !canCompress,
          fork: isLoading || Boolean(activeCompletionAction),
          restore: true,
        }}
      />
    </>
  );
});

const SubagentLogDrawer = memo(function SubagentLogDrawer({
  sessionId,
  messages,
  isOpen,
  isLoading,
  onOpenChange,
  onResolveDeleteConfirmation,
  onResolveGitConfirmation,
  onResolveConnectInput,
  onResolvePlanQuestionsInput,
  onViewPlan,
  thinkingRendering = "text",
  finalAnswerRendering = "markdown",
}: {
  sessionId: string | null;
  messages: ChatMessage[];
  isOpen: boolean;
  isLoading: boolean;
  onOpenChange: (open: boolean) => void;
  onResolveDeleteConfirmation: (toolCallId: string, approved: boolean) => void;
  onResolveGitConfirmation: (
    toolCallId: string,
    type: "commit" | "tag",
    approved: boolean,
  ) => void;
  onResolveConnectInput?: (
    toolCallId: string,
    values: Record<string, string>,
  ) => void;
  onResolvePlanQuestionsInput?: (
    toolCallId: string,
    answers: QuizSubmission,
  ) => void | Promise<void>;
  onViewPlan?: (title: string, markdown: string) => void;
  thinkingRendering?: "text" | "markdown";
  finalAnswerRendering?: "markdown" | "html";
}) {
  const emptyCompressedMessageIds = useMemo(() => new Set<string>(), []);
  const displayMessages = useMemo(
    () => stripSubagentSnapshotParts(messages),
    [messages],
  );
  const hasRenderableMessages = displayMessages.some(
    (message) =>
      message.content.trim() ||
      message.thoughts?.trim() ||
      (message.toolCalls?.length ?? 0) > 0 ||
      (message.parts?.length ?? 0) > 0,
  );

  if (!isOpen) {
    return null;
  }

  return (
    <motion.aside
      key="subagent-log-drawer"
      initial={{ opacity: 0, x: 28 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 28 }}
      transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
      className="absolute inset-y-0 right-0 z-30 flex w-[min(390px,calc(100vw-32px))] flex-col border-l bg-background shadow-2xl"
    >
      <div className="flex h-10 shrink-0 items-center justify-end border-b px-2">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => onOpenChange(false)}
                aria-label="收起子智能体日志"
              >
                <XIcon className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="left">
              <p>收起</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
      <div className="relative min-h-0 flex-1">
        {hasRenderableMessages ? (
          <Conversation className="absolute inset-0">
            <ConversationContent className="gap-3 p-3">
              <MessageList
                sessionId={sessionId}
                isLoading={isLoading}
                messages={displayMessages}
                codeChanges={[]}
                onResolveDeleteConfirmation={onResolveDeleteConfirmation}
                onResolveGitConfirmation={onResolveGitConfirmation}
                onResolveConnectInput={onResolveConnectInput}
                onResolvePlanQuestionsInput={onResolvePlanQuestionsInput}
                onViewPlan={onViewPlan}
                compressedMessageIds={emptyCompressedMessageIds}
                canCompress={false}
                thinkingRendering={thinkingRendering}
                finalAnswerRendering={finalAnswerRendering}
              />
            </ConversationContent>
            <ConversationScrollButton className="bottom-3" />
          </Conversation>
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
          </div>
        )}
      </div>
    </motion.aside>
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
      if (
        typeof Notification !== "undefined" &&
        Notification.permission === "granted"
      ) {
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
  const [tooltipRect, setTooltipRect] = useState<{
    top: number;
    right: number;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const getPreview = useCallback((msg: ChatMessage): string => {
    const raw =
      msg.parts
        ?.filter((p) => p.type === "text")
        .map((p) => (p as { type: "text"; text: string }).text)
        .join("") ??
      msg.content ??
      "";
    const clean = raw
      .replace(/[#*`\n]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    return clean.length > 28
      ? clean.slice(0, 28) + "…"
      : clean || (msg.role === "user" ? "用户消息" : "AI 回复");
  }, []);

  const scrollToMessage = useCallback((msgId: string) => {
    const el = document.querySelector(`[data-message-id="${msgId}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, []);

  const handleHover = useCallback((idx: number) => {
    setHoveredIdx(idx);
    const bar = containerRef.current?.querySelector(
      `[data-outline-idx="${idx}"]`,
    );
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
      const textLen = (
        msg.parts
          ?.filter((p) => p.type === "text")
          .map((p) => (p as { type: "text"; text: string }).text)
          .join("") ??
        msg.content ??
        ""
      ).length;
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
                transition={
                  isStreaming
                    ? { duration: 2, repeat: Infinity, ease: "easeInOut" }
                    : { duration: 0.15 }
                }
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
                  background:
                    messages[hoveredIdx].role === "user"
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
  if (
    mentionToken &&
    safeCaret > mentionToken.start &&
    safeCaret <= mentionToken.end
  ) {
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

function getComposerPointOffset(
  root: HTMLElement,
  container: Node,
  offset: number,
): number {
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

      return (
        total + getComposerPointOffset(child as HTMLElement, container, offset)
      );
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
  if (
    !root.contains(range.startContainer) ||
    !root.contains(range.endContainer)
  ) {
    return null;
  }

  return {
    start: getComposerPointOffset(
      root,
      range.startContainer,
      range.startOffset,
    ),
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
  workspace:
    "text-amber-600 bg-amber-50 dark:text-amber-400 dark:bg-amber-950/60",
  file: "text-blue-600 bg-blue-50 dark:text-blue-400 dark:bg-blue-950/60",
  change:
    "text-emerald-600 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-950/60",
  element:
    "text-violet-600 bg-violet-50 dark:text-violet-400 dark:bg-violet-950/60",
};

const MENTION_KIND_BADGE_STYLES: Record<MentionSuggestion["kind"], string> = {
  workspace:
    "border-amber-200/80 bg-amber-50/95 text-amber-950 dark:border-amber-900/80 dark:bg-amber-950/70 dark:text-amber-100",
  file: "border-blue-200/80 bg-blue-50/95 text-blue-950 dark:border-blue-900/80 dark:bg-blue-950/70 dark:text-blue-100",
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
  composerFocusRevision,
  isLoading,
  model,
  reasoningEffort,
  executionMode,
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
  onExecutionModeChange,
  onCompletionAction,
  activeCompletionAction,
  elementAttachments = [],
  onRemoveElementAttachment,
  onEditMessage,
  thinkingRendering = "text",
  finalAnswerRendering = "markdown",
}: ChatPanelProps) {
  const planSteps = contextData?.planSteps ?? [];
  const mainMessages = useMemo(
    () => messages.filter((message) => !isSubagentMessage(message)),
    [messages],
  );
  const subagentMessages = useMemo(
    () => messages.filter(isSubagentMessage),
    [messages],
  );
  const composerRef = useRef<HTMLDivElement>(null);
  const [isFocused, setIsFocused] = useState(false);
  const [attachmentFiles, setAttachmentFiles] = useState<AttachmentData[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerInputRef = useRef<HTMLDivElement>(null);
  const composerInputId = useId();
  const [isModelSelectorOpen, setIsModelSelectorOpen] = useState(false);
  const [isHandling, setIsHandling] = useState(false);
  const [isSubagentDrawerOpen, setIsSubagentDrawerOpen] = useState(false);
  const [activeSubagentParentToolCallId, setActiveSubagentParentToolCallId] =
    useState<string | null>(null);
  const [autoCloseSubagentDrawer, setAutoCloseSubagentDrawer] = useState(false);

  const handleEmptySend = useCallback(() => {
    if (isHandling) return;
    setIsHandling(true);
    onSendMessage();
  }, [isHandling, onSendMessage]);

  const handleEditMessage = useCallback(
    (content: string) => {
      onInputChange(content);
      composerInputRef.current?.focus();
    },
    [onInputChange],
  );

  useEffect(() => {
    if (!isHandling || isLoading) return;
    setIsHandling(false);
  }, [isHandling, isLoading]);

  const [edgeGlowActive, setEdgeGlowActive] = useState(false);

  useEffect(() => {
    if (!isHandling) {
      setEdgeGlowActive(false);
      return;
    }

    setEdgeGlowActive(true);
    const timer = setTimeout(() => {
      setEdgeGlowActive(false);
    }, 3000);

    return () => clearTimeout(timer);
  }, [isHandling]);

  const [composerSelection, setComposerSelection] =
    useState<ComposerSelectionOffsets>({
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
  const [dismissedMentionKey, setDismissedMentionKey] = useState<string | null>(
    null,
  );

  useCompletionNotification(isLoading, mainMessages.length > 0);

  const activeSubagentMessages = useMemo(
    () =>
      activeSubagentParentToolCallId
        ? getSubagentMessagesForParent(
            subagentMessages,
            activeSubagentParentToolCallId,
          )
        : [],
    [activeSubagentParentToolCallId, subagentMessages],
  );
  const activeSubagentToolCall = useMemo(
    () =>
      activeSubagentParentToolCallId
        ? findToolCallById(mainMessages, activeSubagentParentToolCallId)
        : null,
    [activeSubagentParentToolCallId, mainMessages],
  );
  const isActiveSubagentRunning =
    activeSubagentToolCall?.state === "running" ||
    activeSubagentMessages.some(isSubagentMessageRunning);

  const handleOpenSubagentLog = useCallback(
    (parentToolCallId: string) => {
      const relatedMessages = getSubagentMessagesForParent(
        subagentMessages,
        parentToolCallId,
      );
      const toolCall = findToolCallById(mainMessages, parentToolCallId);
      setActiveSubagentParentToolCallId(parentToolCallId);
      setIsSubagentDrawerOpen(true);
      setAutoCloseSubagentDrawer(
        toolCall?.state === "running" ||
          relatedMessages.some(isSubagentMessageRunning),
      );
    },
    [mainMessages, subagentMessages],
  );

  const handleSubagentDrawerOpenChange = useCallback((open: boolean) => {
    setIsSubagentDrawerOpen(open);
    if (!open) {
      setAutoCloseSubagentDrawer(false);
    }
  }, []);

  useEffect(() => {
    if (subagentMessages.length > 0) {
      return;
    }
    setIsSubagentDrawerOpen(false);
    setActiveSubagentParentToolCallId(null);
    setAutoCloseSubagentDrawer(false);
  }, [subagentMessages.length]);

  useEffect(() => {
    if (
      !isSubagentDrawerOpen ||
      !autoCloseSubagentDrawer ||
      isActiveSubagentRunning ||
      activeSubagentMessages.length === 0
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      setIsSubagentDrawerOpen(false);
      setAutoCloseSubagentDrawer(false);
    }, 700);
    return () => window.clearTimeout(timer);
  }, [
    activeSubagentMessages.length,
    autoCloseSubagentDrawer,
    isActiveSubagentRunning,
    isSubagentDrawerOpen,
  ]);

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

  const formatModelContextWindow = (tokens: number | null | undefined) => {
    if (!tokens) return "未知";
    if (tokens >= 1_000_000) {
      const value = tokens / 1_000_000;
      return `${Number.isInteger(value) ? value : value.toFixed(1)}M`;
    }
    const value = tokens / 1_000;
    return `${Number.isInteger(value) ? value : value.toFixed(0)}K`;
  };
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
        filePath,
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
            filePath: node.path,
          });
        }
        if (node.type === "folder") {
          pushSuggestion({
            id: `workspace:${node.path}`,
            kind: "workspace",
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
        filePath: path,
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
      [suggestion.label, suggestion.description, suggestion.insertValue].some(
        (value) => value.toLowerCase().includes(normalizedQuery),
      ),
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
    for (let i = mainMessages.length - 1; i >= 0; i--) {
      if (mainMessages[i].role === "assistant") {
        return mainMessages[i];
      }
    }
    return null;
  }, [mainMessages]);
  const canCompress =
    (contextData?.estimatedTokens ?? 0) /
      Math.max(contextData?.maxTokens ?? 1, 1) >=
    CONTEXT_COMPRESSION_USAGE_THRESHOLD;

  const hasDraftInput = isFocused && input.trim().length > 0;
  const hasStreamingResponse =
    isLoading && Boolean(lastAssistantMessage?.content?.trim());
  const hasCompletedConversation = mainMessages.length > 0 && !isLoading;

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

  const syncComposerSelection = useCallback(
    (target: HTMLElement) => {
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
    },
    [input],
  );

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
        start: normalizeMentionCaret(
          nextValue,
          selection?.start ?? nextValue.length,
        ),
        end: normalizeMentionCaret(
          nextValue,
          selection?.end ?? nextValue.length,
        ),
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
    [
      composerInputId,
      composerSelection.end,
      composerSelection.start,
      input,
      onInputChange,
    ],
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
        const nextValue =
          input.slice(0, caretStart) + "\n" + input.slice(caretEnd);
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

  const composer = (
    <div className="shrink-0 border-t bg-background">
      <div className={cn("mx-auto w-full", CHAT_CONTENT_MAX_WIDTH)}>
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
                focusRevision={composerFocusRevision}
                onChange={onInputChange}
                onSubmit={
                  mainMessages.length === 0 ? handleEmptySend : onSendMessage
                }
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
                        model={selectedModel?.name}
                      />
                      <ModelSelectorName>
                        {selectedModel?.label ??
                          selectedModel?.name ??
                          "选择模型"}
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
                            className="min-h-12 gap-2 py-2"
                          >
                            <ModelSelectorLogo
                              provider={m.provider}
                              model={m.name}
                              className="mt-0.5"
                            />
                            <div className="min-w-0 flex-1 text-left">
                              <ModelSelectorName className="block">
                                {m.label ?? m.name}
                              </ModelSelectorName>
                              <span className="block truncate text-[11px] leading-4 text-muted-foreground">
                                上下文长度：{formatModelContextWindow(m.contextWindow)}
                              </span>
                            </div>
                          </ModelSelectorItem>
                        ))}
                      </ModelSelectorGroup>
                    </ModelSelectorList>
                  </ModelSelectorContent>
                </ModelSelector>

                <Select
                  value={agentMode}
                  onValueChange={(value) =>
                    onAgentModeChange(value as AgentMode)
                  }
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
                    <SelectItem value="chat">聊天</SelectItem>
                    <SelectItem value="plan">计划</SelectItem>
                    <SelectItem value="coding">编码</SelectItem>
                    <SelectItem value="deploy">部署</SelectItem>
                  </SelectContent>
                </Select>

                <Select
                  value={executionMode}
                  onValueChange={(value) =>
                    onExecutionModeChange(value as SessionExecutionMode)
                  }
                >
                  <SelectTrigger
                    size="sm"
                    className="h-7 min-w-[104px] max-w-full gap-1.5 border-0 px-2 text-xs text-muted-foreground shadow-none"
                    aria-label="选择运行位置"
                  >
                    {executionMode === "worktree" ? (
                      <GitBranch className="size-3.5" />
                    ) : (
                      <FolderOpenIcon className="size-3.5" />
                    )}
                    <SelectValue placeholder="运行位置" />
                  </SelectTrigger>
                  <SelectContent align="start">
                    <SelectItem value="local">本地</SelectItem>
                    <SelectItem value="worktree">工作树</SelectItem>
                  </SelectContent>
                </Select>

                <Select
                  value={selectedReasoningEffort}
                  onValueChange={onReasoningEffortChange}
                >
                  <SelectTrigger
                    size="sm"
                    className="hidden h-7 min-w-[108px] max-w-full gap-1.5 border-0 px-2 text-xs text-muted-foreground shadow-none"
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
                  onClick={
                    mainMessages.length === 0 ? handleEmptySend : onSendMessage
                  }
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
  );

  return (
    <>
      <CanvasEdgeGlow active={edgeGlowActive} />
      <AnimatePresence>
        {mainMessages.length === 0 && (
          <EmptyHeroState state={personaState} isHandling={isHandling}>
            <motion.div
              key="empty-composer"
              exit={{ opacity: 0, y: 24 }}
              transition={{ duration: 0.18, ease: [0.4, 0, 0.2, 1] }}
            >
              {composer}
            </motion.div>
          </EmptyHeroState>
        )}
        {mainMessages.length > 0 && (
          <motion.div
            key="normal"
            className="relative h-full flex min-w-0 border-r"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
          >
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex-1 relative min-h-0">
                <Conversation className="absolute inset-0">
                  <ConversationContent className={cn("mx-auto w-full gap-4 pb-4", CHAT_CONTENT_MAX_WIDTH)}>
                    <ChatStreamBody
                      sessionId={sessionId}
                      isLoading={isLoading}
                      messages={mainMessages}
                      codeChanges={codeChanges}
                      onResolveDeleteConfirmation={onResolveDeleteConfirmation}
                      onResolveGitConfirmation={onResolveGitConfirmation}
                      onResolveConnectInput={onResolveConnectInput}
                      onResolvePlanQuestionsInput={onResolvePlanQuestionsInput}
                      onViewPlan={onViewPlan}
                      personaState={personaState}
                      onCompletionAction={onCompletionAction}
                      activeCompletionAction={activeCompletionAction}
                      canCompress={canCompress}
                      onEditMessage={onEditMessage}
                      subagentMessages={subagentMessages}
                      onOpenSubagentLog={handleOpenSubagentLog}
                      thinkingRendering={thinkingRendering}
                      finalAnswerRendering={finalAnswerRendering}
                    />
                  </ConversationContent>
                  <ConversationScrollButton className="bottom-16" />
                </Conversation>
                <div className="absolute right-2 top-0 bottom-0 flex items-center pointer-events-none z-10">
                  <div className="pointer-events-auto">
                    <MessageOutline messages={mainMessages} isLoading={isLoading} />
                  </div>
                </div>
              </div>
              <motion.div
                initial={{ opacity: 1, y: "-32vh" }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
              >
                {composer}
              </motion.div>
            </div>
            <AnimatePresence>
              {isSubagentDrawerOpen && (
                <SubagentLogDrawer
                  sessionId={sessionId}
                  messages={activeSubagentMessages}
                  isOpen={isSubagentDrawerOpen}
                  isLoading={isLoading}
                  onOpenChange={handleSubagentDrawerOpenChange}
                  onResolveDeleteConfirmation={onResolveDeleteConfirmation}
                  onResolveGitConfirmation={onResolveGitConfirmation}
                  onResolveConnectInput={onResolveConnectInput}
                  onResolvePlanQuestionsInput={onResolvePlanQuestionsInput}
                  onViewPlan={onViewPlan}
                  thinkingRendering={thinkingRendering}
                  finalAnswerRendering={finalAnswerRendering}
                />
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
