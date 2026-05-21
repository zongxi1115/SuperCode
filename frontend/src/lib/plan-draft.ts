export type PlanDraftPreview = {
  title?: string;
  summary?: string;
  overview?: string;
  keySteps?: string[];
  markdown?: string;
};

function decodeLooseJsonString(raw: string) {
  let candidate = raw;
  if (candidate.endsWith("\\")) {
    candidate = candidate.slice(0, -1);
  }

  try {
    return JSON.parse(`"${candidate}"`) as string;
  } catch {
    return candidate
      .replace(/\\"/g, '"')
      .replace(/\\n/g, "\n")
      .replace(/\\r/g, "\r")
      .replace(/\\t/g, "\t")
      .replace(/\\\\/g, "\\");
  }
}

function extractPartialJsonStringField(input: string, field: string) {
  const fieldIndex = input.indexOf(`"${field}"`);
  if (fieldIndex < 0) return undefined;

  const colonIndex = input.indexOf(":", fieldIndex + field.length + 2);
  if (colonIndex < 0) return undefined;

  let valueStart = colonIndex + 1;
  while (valueStart < input.length && /\s/.test(input[valueStart] ?? "")) {
    valueStart += 1;
  }
  if (input[valueStart] !== '"') return undefined;

  let raw = "";
  let escaping = false;
  for (let index = valueStart + 1; index < input.length; index += 1) {
    const char = input[index] ?? "";
    if (escaping) {
      raw += char;
      escaping = false;
      continue;
    }
    if (char === "\\") {
      raw += char;
      escaping = true;
      continue;
    }
    if (char === '"') {
      return decodeLooseJsonString(raw);
    }
    raw += char;
  }

  return decodeLooseJsonString(raw);
}

function extractPartialJsonStringArrayField(input: string, field: string) {
  const fieldIndex = input.indexOf(`"${field}"`);
  if (fieldIndex < 0) return undefined;

  const arrayStart = input.indexOf("[", fieldIndex + field.length + 2);
  if (arrayStart < 0) return undefined;

  const values: string[] = [];
  let current = "";
  let inString = false;
  let escaping = false;

  for (let index = arrayStart + 1; index < input.length; index += 1) {
    const char = input[index] ?? "";
    if (!inString) {
      if (char === '"') {
        current = "";
        inString = true;
      } else if (char === "]") {
        return values;
      }
      continue;
    }

    if (escaping) {
      current += char;
      escaping = false;
      continue;
    }
    if (char === "\\") {
      current += char;
      escaping = true;
      continue;
    }
    if (char === '"') {
      values.push(decodeLooseJsonString(current));
      current = "";
      inString = false;
      continue;
    }
    current += char;
  }

  return values.length > 0 ? values : undefined;
}

function normalizeStringArray(value: unknown) {
  if (!Array.isArray(value)) return undefined;
  const items = value.filter((item): item is string => typeof item === "string");
  return items.length > 0 ? items : undefined;
}

export function normalizePlanDraft(value: unknown): PlanDraftPreview | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }

  const record = value as Record<string, unknown>;
  const preview: PlanDraftPreview = {
    title: typeof record.title === "string" ? record.title : undefined,
    summary: typeof record.summary === "string" ? record.summary : undefined,
    overview: typeof record.overview === "string" ? record.overview : undefined,
    keySteps:
      normalizeStringArray(record.keySteps) ??
      normalizeStringArray(record.key_steps),
    markdown: typeof record.markdown === "string" ? record.markdown : undefined,
  };

  return Object.values(preview).some((item) =>
    Array.isArray(item) ? item.length > 0 : Boolean(item),
  )
    ? preview
    : undefined;
}

export function parseStreamingPlanDraft(
  streamedInput?: string,
): PlanDraftPreview | undefined {
  if (!streamedInput?.trim()) return undefined;

  try {
    return normalizePlanDraft(JSON.parse(streamedInput));
  } catch {
    const preview: PlanDraftPreview = {
      title: extractPartialJsonStringField(streamedInput, "title"),
      summary: extractPartialJsonStringField(streamedInput, "summary"),
      overview: extractPartialJsonStringField(streamedInput, "overview"),
      keySteps:
        extractPartialJsonStringArrayField(streamedInput, "key_steps") ??
        extractPartialJsonStringArrayField(streamedInput, "keySteps"),
      markdown: extractPartialJsonStringField(streamedInput, "markdown"),
    };

    return Object.values(preview).some((item) =>
      Array.isArray(item) ? item.length > 0 : Boolean(item),
    )
      ? preview
      : undefined;
  }
}

export function resolvePlanDraftTitle(
  preview?: PlanDraftPreview,
  fallback = "计划草案",
) {
  return preview?.title?.trim() || fallback;
}

export function buildPlanDraftMarkdown(
  preview?: PlanDraftPreview,
  fallbackTitle = "计划草案",
) {
  const title = resolvePlanDraftTitle(preview, fallbackTitle);
  const markdown = preview?.markdown?.trimEnd();
  if (markdown) {
    return markdown;
  }

  const sections = [`# ${title}`];
  if (preview?.summary?.trim()) {
    sections.push("", preview.summary.trim());
  }
  if (preview?.overview?.trim()) {
    sections.push("", "## 概览", "", preview.overview.trim());
  }
  if ((preview?.keySteps?.length ?? 0) > 0) {
    sections.push(
      "",
      "## 关键步骤",
      "",
      ...(preview?.keySteps ?? []).map((step, index) => `${index + 1}. ${step}`),
    );
  }

  return sections.join("\n");
}
