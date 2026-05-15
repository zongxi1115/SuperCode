import type { ChatMessage, SessionContextPayload, ToolCallRecord } from '@/lib/app-types';
import { contextHealth, nextTurnBudget, resolveModel, tokensRemaining } from 'tokenlens';

const DEFAULT_MAX_TOKENS = 32_000;
const MESSAGE_FRAME_TOKENS = 6;
const TOOL_FRAME_TOKENS = 14;
const OPEN_FILE_FRAME_TOKENS = 3;

export type ContextBudgetStatus = 'ok' | 'warn' | 'compact';

export type ContextBudgetSnapshot = {
  modelId?: string;
  usedTokens: number;
  maxTokens: number;
  remainingTokens: number;
  nextTurnBudgetTokens: number;
  reserveOutputTokens: number;
  percentUsed: number;
  status: ContextBudgetStatus;
  inputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  conversationTokens: number;
  toolTokens: number;
  workspaceTokens: number;
  draftTokens: number;
};

type BuildContextBudgetArgs = {
  contextData: SessionContextPayload | null;
  messages: ChatMessage[];
  draftInput: string;
};

export function buildContextBudget({
  contextData,
  messages,
  draftInput,
}: BuildContextBudgetArgs): ContextBudgetSnapshot {
  const maxTokens = Math.max(contextData?.maxTokens ?? DEFAULT_MAX_TOKENS, 1);
  const reserveOutputTokens = getReserveOutputTokens(maxTokens);
  const workspaceTokens = estimateWorkspaceTokens(contextData);
  const draftTokens = estimateTextTokens(draftInput);
  const messageTotals = accumulateMessageBudget(messages);

  const inputTokens = workspaceTokens + draftTokens + messageTotals.inputTokens;
  const outputTokens = messageTotals.outputTokens;
  const reasoningTokens = messageTotals.reasoningTokens;
  const conversationTokens = messageTotals.conversationTokens;
  const toolTokens = messageTotals.toolTokens;

  const usedTokens = inputTokens + outputTokens + reasoningTokens;
  const modelId = resolveBudgetModelId(contextData?.model);
  const usage = { inputTokens, outputTokens, reasoningTokens };
  const fallbackRemaining = Math.max(maxTokens - usedTokens - reserveOutputTokens, 0);

  const health = modelId
    ? contextHealth({
        modelId,
        usage,
        reserveOutput: reserveOutputTokens,
      })
    : {
        percentUsed: clampPercent(usedTokens / maxTokens),
        remaining: fallbackRemaining,
        status: fallbackStatus(usedTokens / maxTokens),
      };

  const remainingTokens = modelId
    ? Math.max(
        tokensRemaining({
          id: modelId,
          usage,
          reserveOutput: reserveOutputTokens,
        }) ?? fallbackRemaining,
        0
      )
    : fallbackRemaining;

  const nextTurnBudgetTokens = modelId
    ? Math.max(
        nextTurnBudget({
          modelId,
          usage,
          reserveOutput: reserveOutputTokens,
        }) ?? fallbackRemaining,
        0
      )
    : fallbackRemaining;

  return {
    modelId,
    usedTokens,
    maxTokens,
    remainingTokens,
    nextTurnBudgetTokens,
    reserveOutputTokens,
    percentUsed: clampPercent(health.percentUsed),
    status: health.status,
    inputTokens,
    outputTokens,
    reasoningTokens,
    conversationTokens,
    toolTokens,
    workspaceTokens,
    draftTokens,
  };
}

export function estimateConversationSliceTokens(messages: ChatMessage[]): number {
  const totals = accumulateMessageBudget(messages);
  return totals.inputTokens + totals.outputTokens + totals.reasoningTokens;
}

export function estimateTextTokens(value: string): number {
  if (!value.trim()) {
    return 0;
  }

  const cjkChars = countMatches(value, /[\u3400-\u9fff\uf900-\ufaff]/g);
  const asciiChars = countAsciiChars(value);
  const newlineChars = countMatches(value, /\n/g);
  const otherChars = Math.max(value.length - cjkChars - asciiChars, 0);

  return Math.max(
    1,
    Math.ceil(
      cjkChars * 1.08 +
        asciiChars / 3.7 +
        otherChars / 2.2 +
        newlineChars * 0.35 +
        1
    )
  );
}

export function formatCompactTokens(value: number): string {
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits: value >= 100_000 ? 0 : 1,
  }).format(value);
}

export function formatExactTokens(value: number): string {
  return new Intl.NumberFormat('en-US').format(value);
}

export function formatBudgetPercent(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'percent',
    maximumFractionDigits: value >= 0.1 ? 0 : 1,
  }).format(clampPercent(value));
}

function estimateWorkspaceTokens(contextData: SessionContextPayload | null): number {
  if (!contextData) {
    return 0;
  }

  let total =
    estimateTextTokens(contextData.workspace) +
    estimateTextTokens(contextData.selectedFilePath ?? '');

  for (const filePath of contextData.openFiles) {
    total += estimateTextTokens(filePath) + OPEN_FILE_FRAME_TOKENS;
  }

  return total;
}

function accumulateMessageBudget(messages: ChatMessage[]): {
  inputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  conversationTokens: number;
  toolTokens: number;
} {
  let inputTokens = 0;
  let outputTokens = 0;
  let reasoningTokens = 0;
  let conversationTokens = 0;
  let toolTokens = 0;

  for (const message of messages) {
    const messageTokens = estimateTextTokens(message.content) + MESSAGE_FRAME_TOKENS;
    conversationTokens += messageTokens;

    if (message.role === 'user') {
      inputTokens += messageTokens;
    } else {
      outputTokens += messageTokens;
    }

    reasoningTokens += estimateTextTokens(message.thoughts ?? '');

    for (const toolCall of message.toolCalls ?? []) {
      const toolBudget = estimateToolCallTokens(toolCall);
      inputTokens += toolBudget.inputTokens;
      outputTokens += toolBudget.outputTokens;
      toolTokens += toolBudget.inputTokens + toolBudget.outputTokens;
    }
  }

  return {
    inputTokens,
    outputTokens,
    reasoningTokens,
    conversationTokens,
    toolTokens,
  };
}

function estimateToolCallTokens(toolCall: ToolCallRecord): {
  inputTokens: number;
  outputTokens: number;
} {
  const inputTokens =
    estimateTextTokens(toolCall.name) +
    estimateUnknownTokens(toolCall.arguments) +
    TOOL_FRAME_TOKENS;

  const outputTokens =
    estimateUnknownTokens(toolCall.output) +
    estimateTextTokens(toolCall.errorMessage ?? toolCall.error_message ?? '');

  return {
    inputTokens,
    outputTokens,
  };
}

function estimateUnknownTokens(value: unknown): number {
  if (value == null) {
    return 0;
  }

  if (typeof value === 'string') {
    return estimateTextTokens(value);
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return estimateTextTokens(String(value));
  }

  try {
    return estimateTextTokens(JSON.stringify(value, null, 2));
  } catch {
    return estimateTextTokens(String(value));
  }
}

function resolveBudgetModelId(modelName?: string | null): string | undefined {
  if (!modelName) {
    return undefined;
  }

  const trimmed = modelName.trim();
  if (!trimmed) {
    return undefined;
  }

  const candidates = new Set<string>();
  const normalized = trimmed
    .toLowerCase()
    .replace(/[·/]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  candidates.add(trimmed);
  candidates.add(normalized);
  candidates.add(normalized.replace(/\s+/g, '-'));
  candidates.add(normalized.replace(/\s+/g, ''));

  if (normalized.includes('claude 3.5 sonnet')) {
    candidates.add('claude-3-5-sonnet');
    candidates.add('anthropic:claude-3-5-sonnet-20240620');
  }

  if (normalized.includes('claude 3.7 sonnet')) {
    candidates.add('claude-3-7-sonnet');
  }

  if (normalized.includes('gpt 4.1')) {
    candidates.add('gpt-4.1');
    candidates.add('openai:gpt-4.1');
  }

  if (normalized.includes('gpt 4o mini')) {
    candidates.add('gpt-4o-mini');
    candidates.add('openai:gpt-4o-mini');
  }

  if (normalized.includes('gpt 4o')) {
    candidates.add('gpt-4o');
    candidates.add('openai:gpt-4o');
  }

  if (normalized.includes('deepseek')) {
    candidates.add('deepseek-chat');
    candidates.add('deepseek:deepseek-chat');
  }

  const providerPrefixes = ['', 'anthropic:', 'openai:', 'deepseek:', 'google:', 'xai:', 'openrouter:'];

  for (const candidate of candidates) {
    for (const prefix of providerPrefixes) {
      const resolved = resolveModel(`${prefix}${candidate}`);
      if (resolved?.id) {
        return resolved.id;
      }
    }
  }

  return undefined;
}

function fallbackStatus(percentUsed: number): ContextBudgetStatus {
  if (percentUsed >= 0.85) {
    return 'compact';
  }
  if (percentUsed >= 0.7) {
    return 'warn';
  }
  return 'ok';
}

function getReserveOutputTokens(maxTokens: number): number {
  if (maxTokens >= 200_000) {
    return 8_192;
  }
  if (maxTokens >= 128_000) {
    return 4_096;
  }
  if (maxTokens >= 64_000) {
    return 2_048;
  }
  return 1_024;
}

function countMatches(value: string, pattern: RegExp): number {
  return value.match(pattern)?.length ?? 0;
}

function countAsciiChars(value: string): number {
  let total = 0;
  for (const char of value) {
    if (char.charCodeAt(0) <= 0x7f) {
      total += 1;
    }
  }
  return total;
}

function clampPercent(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}
