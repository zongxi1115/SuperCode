"use client";

import { cn } from "@/lib/utils";
import { Node, mergeAttributes } from "@tiptap/core";
import { EditorContent, NodeViewWrapper, ReactNodeViewRenderer, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  FileIcon,
  FolderOpenIcon,
  GlobeIcon,
  LightbulbIcon,
  MessageSquareIcon,
} from "lucide-react";
import { getFileIcon } from "@/lib/file-icons";
import { motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

type MentionKind = "workspace" | "file" | "change" | "element" | "skill";

export type ComposerMentionSuggestion = {
  id: string;
  kind: MentionKind;
  label: string;
  description: string;
  insertValue: string;
  filePath?: string;
};

type ActiveMention = {
  query: string;
  from: number;
  to: number;
  left: number;
  top: number;
  bottom: number;
  viewportLeft: number;
  viewportTop: number;
  viewportBottom: number;
};

type ChatComposerEditorProps = {
  value: string;
  suggestions: ComposerMentionSuggestion[];
  focusRevision?: number;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onFiles?: (files: File[]) => void;
};

type MentionAttrs = {
  id: string;
  label: string;
  kind: MentionKind;
};

const COMPOSER_MIN_HEIGHT = 52;
const COMPOSER_MAX_HEIGHT = 220;

const MENTION_KIND_ICON_COLORS: Record<MentionKind, string> = {
  workspace: "text-amber-600 bg-amber-50 dark:text-amber-400 dark:bg-amber-950/60",
  file: "text-blue-600 bg-blue-50 dark:text-blue-400 dark:bg-blue-950/60",
  change: "text-emerald-600 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-950/60",
  element: "text-violet-600 bg-violet-50 dark:text-violet-400 dark:bg-violet-950/60",
  skill: "text-cyan-700 bg-cyan-50 dark:text-cyan-300 dark:bg-cyan-950/60",
};

const MENTION_KIND_BADGE_STYLES: Record<MentionKind, string> = {
  workspace:
    "border-amber-200/80 bg-amber-50/95 text-amber-950 dark:border-amber-900/80 dark:bg-amber-950/70 dark:text-amber-100",
  file:
    "border-blue-200/80 bg-blue-50/95 text-blue-950 dark:border-blue-900/80 dark:bg-blue-950/70 dark:text-blue-100",
  change:
    "border-emerald-200/80 bg-emerald-50/95 text-emerald-950 dark:border-emerald-900/80 dark:bg-emerald-950/70 dark:text-emerald-100",
  element:
    "border-violet-200/80 bg-violet-50/95 text-violet-950 dark:border-violet-900/80 dark:bg-violet-950/70 dark:text-violet-100",
  skill:
    "border-cyan-200/80 bg-cyan-50/95 text-cyan-950 dark:border-cyan-900/80 dark:bg-cyan-950/70 dark:text-cyan-100",
};

const MENTION_KIND_LABELS: Record<MentionKind, string> = {
  skill: "技能",
  workspace: "工作区",
  file: "文件",
  change: "变更",
  element: "元素",
};

const MENTION_KIND_GROUP_ORDER: MentionKind[] = ["skill", "workspace", "file", "change", "element"];

function getPathLeaf(input: string) {
  const normalized = input.replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).pop() ?? input;
}

function FileExtIcon({ filename }: { filename: string }) {
  const entry = getFileIcon(filename);
  if (entry) {
    return <span style={{ color: entry.color }} className="flex shrink-0">{entry.icon}</span>;
  }
  return <FileIcon className="size-3.5 text-muted-foreground" />;
}

function getMentionSuggestionIcon(kind: MentionKind, filePath?: string) {
  switch (kind) {
    case "workspace":
      return <FolderOpenIcon className="size-3.5" />;
    case "file":
    case "change": {
      if (!filePath) return <FileIcon className="size-3.5" />;
      const filename = getPathLeaf(filePath);
      return <FileExtIcon filename={filename} />;
    }
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

function buildSuggestionMap(suggestions: ComposerMentionSuggestion[]) {
  const map = new Map<string, ComposerMentionSuggestion>();
  for (const suggestion of suggestions) {
    map.set(suggestion.insertValue, suggestion);
  }
  return map;
}

function parseInputToDoc(
  value: string,
  suggestionMap: Map<string, ComposerMentionSuggestion>,
) {
  const mentionTokenRe = /@\[((?:\\.|[^\]])*)\]/g;
  const paragraphContent: Array<Record<string, unknown>> = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  const pushText = (text: string) => {
    if (!text) return;
    const parts = text.split("\n");
    parts.forEach((part, index) => {
      if (part) {
        paragraphContent.push({ type: "text", text: part });
      }
      if (index < parts.length - 1) {
        paragraphContent.push({ type: "hardBreak" });
      }
    });
  };

  while ((match = mentionTokenRe.exec(value)) !== null) {
    pushText(value.slice(lastIndex, match.index));
    const token = match[0];
    const decoded = decodeMentionTokenValue(match[1] ?? "");
    const suggestion = suggestionMap.get(token);
    paragraphContent.push({
      type: "composerMention",
      attrs: {
        id: decoded,
        label: suggestion?.label ?? getPathLeaf(decoded),
        kind: suggestion?.kind ?? "file",
      },
    });
    lastIndex = match.index + token.length;
  }

  pushText(value.slice(lastIndex));

  return {
    type: "doc",
    content: [
      {
        type: "paragraph",
        content: paragraphContent,
      },
    ],
  };
}

function serializeNode(node: Record<string, unknown>): string {
  const type = node.type as string | undefined;
  if (type === "text") {
    return String(node.text ?? "");
  }
  if (type === "hardBreak") {
    return "\n";
  }
  if (type === "composerMention") {
    const attrs = (node.attrs ?? {}) as MentionAttrs;
    return formatMentionToken(attrs.id ?? "");
  }

  const content = Array.isArray(node.content)
    ? (node.content as Record<string, unknown>[]).map(serializeNode).join("")
    : "";

  if (type === "paragraph") {
    return content;
  }
  if (type === "doc") {
    return content;
  }
  return content;
}

function serializeEditor(editorJson: Record<string, unknown>) {
  return serializeNode(editorJson);
}

function getActiveMentionFromEditor(
  editor: NonNullable<ReturnType<typeof useEditor>>,
  anchorRef: React.RefObject<HTMLDivElement | null>,
): ActiveMention | null {
  if (editor.view.composing || !editor.state.selection.empty) return null;

  const { from } = editor.state.selection;
  const $from = editor.state.selection.$from;
  const textBefore = $from.parent.textBetween(0, $from.parentOffset, "\n", "\0");
  const mentionStart = textBefore.lastIndexOf("@");
  if (mentionStart < 0) return null;

  const previousChar = textBefore[mentionStart - 1];
  if (previousChar && !/[\s([{"'`]/.test(previousChar)) {
    return null;
  }

  const query = textBefore.slice(mentionStart + 1);
  if (/[\s@]/.test(query)) return null;

  const coords = editor.view.coordsAtPos(from);
  const anchorRect = anchorRef.current?.getBoundingClientRect();
  return {
    query,
    from: from - query.length - 1,
    to: from,
    left: coords.left - (anchorRect?.left ?? 0),
    top: coords.top - (anchorRect?.top ?? 0),
    bottom: coords.bottom - (anchorRect?.top ?? 0),
    viewportLeft: coords.left,
    viewportTop: coords.top,
    viewportBottom: coords.bottom,
  };
}

function MentionBadgeView(props: { node: { attrs: MentionAttrs } }) {
  const attrs = props.node.attrs;
  return (
    <NodeViewWrapper
      as="span"
      className={cn(
        "mx-0.5 inline-flex max-w-[16rem] select-none items-center gap-1 rounded-md border px-1.5 py-0.5 align-baseline shadow-sm",
        MENTION_KIND_BADGE_STYLES[attrs.kind],
      )}
      contentEditable={false}
      data-mention-token={formatMentionToken(attrs.id)}
    >
      <span
        className={cn(
          "flex size-4 shrink-0 items-center justify-center rounded-sm",
          MENTION_KIND_ICON_COLORS[attrs.kind],
        )}
      >
        {getMentionSuggestionIcon(attrs.kind, attrs.id)}
      </span>
      <span className="truncate">{attrs.label}</span>
    </NodeViewWrapper>
  );
}

const ComposerMentionNode = Node.create({
  name: "composerMention",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      id: { default: "" },
      label: { default: "" },
      kind: { default: "file" },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-mention-token]" }];
  },

  renderHTML({ node, HTMLAttributes }) {
    const attrs = node.attrs as MentionAttrs;
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-mention-token": formatMentionToken(attrs.id),
      }),
      attrs.label,
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(MentionBadgeView);
  },
});

export function ChatComposerEditor({
  value,
  suggestions,
  focusRevision,
  onChange,
  onSubmit,
  onFiles,
}: ChatComposerEditorProps) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const lastSerializedValueRef = useRef(value);
  const lastFocusRevisionRef = useRef(focusRevision);
  const shouldReduceMotion = useReducedMotion();
  const [activeMention, setActiveMention] = useState<ActiveMention | null>(null);
  const [editorHeight, setEditorHeight] = useState(COMPOSER_MIN_HEIGHT);
  const [scrollProgress, setScrollProgress] = useState(0);
  const [isEditorOverflowing, setIsEditorOverflowing] = useState(false);
  const [mentionNavigation, setMentionNavigation] = useState<{
    key: string | null;
    index: number;
  }>({
    key: null,
    index: 0,
  });
  const suggestionMap = useMemo(() => buildSuggestionMap(suggestions), [suggestions]);

  const filteredSuggestions = useMemo(() => {
    if (!activeMention) return [];
    const normalizedQuery = activeMention.query.trim().toLowerCase();
    if (!normalizedQuery) return suggestions.slice(0, 12);

    return suggestions.filter((suggestion) =>
      [
        suggestion.label,
        suggestion.description,
        suggestion.insertValue,
      ].some((item) => item.toLowerCase().includes(normalizedQuery)),
    ).slice(0, 20);
  }, [activeMention, suggestions]);
  const activeMentionKey = activeMention
    ? `${activeMention.from}:${activeMention.query}`
    : null;
  const selectedIndex =
    activeMentionKey && mentionNavigation.key === activeMentionKey
      ? Math.min(
          mentionNavigation.index,
          Math.max(filteredSuggestions.length - 1, 0),
        )
      : 0;

  const activeMentionRef = useRef(activeMention);
  const filteredSuggestionsRef = useRef(filteredSuggestions);
  const selectedIndexRef = useRef(selectedIndex);
  const onSubmitRef = useRef(onSubmit);

  useEffect(() => { activeMentionRef.current = activeMention; }, [activeMention]);
  useEffect(() => { filteredSuggestionsRef.current = filteredSuggestions; }, [filteredSuggestions]);
  useEffect(() => { selectedIndexRef.current = selectedIndex; }, [selectedIndex]);
  useEffect(() => { onSubmitRef.current = onSubmit; }, [onSubmit]);
  const onFilesRef = useRef(onFiles);
  useEffect(() => { onFilesRef.current = onFiles; }, [onFiles]);

  const refreshEditorMetrics = useCallback(() => {
    const scrollArea = scrollAreaRef.current;
    if (!scrollArea) return;

    const editorElement = scrollArea.querySelector<HTMLElement>(".ProseMirror");
    const contentHeight = Math.max(
      COMPOSER_MIN_HEIGHT,
      editorElement?.scrollHeight ?? scrollArea.scrollHeight,
    );
    const nextHeight = Math.min(COMPOSER_MAX_HEIGHT, contentHeight);
    setEditorHeight(nextHeight);

    const maxScroll = Math.max(scrollArea.scrollHeight - scrollArea.clientHeight, 0);
    setIsEditorOverflowing(maxScroll > 1);
    setScrollProgress(maxScroll > 0 ? scrollArea.scrollTop / maxScroll : 0);
  }, []);

  const insertSuggestionDirectly = useCallback(
    (editorInstance: NonNullable<ReturnType<typeof useEditor>>, suggestion: ComposerMentionSuggestion, mention: ActiveMention) => {
      editorInstance
        .chain()
        .focus()
        .insertContentAt(
          { from: mention.from, to: mention.to },
          [
            {
              type: "composerMention",
              attrs: {
                id: decodeMentionTokenValue(
                  suggestion.insertValue.slice(2, -1),
                ),
                label: suggestion.label,
                kind: suggestion.kind,
              },
            },
            { type: "text", text: " " },
          ],
        )
        .run();
      setActiveMention(null);
    },
    [],
  );

  const editor = useEditor(
    {
      immediatelyRender: false,
      extensions: [
        StarterKit.configure({
          blockquote: false,
          bulletList: false,
          codeBlock: false,
          heading: false,
          horizontalRule: false,
          listItem: false,
          orderedList: false,
          dropcursor: false,
          gapcursor: false,
        }),
        ComposerMentionNode,
      ],
      content: parseInputToDoc(value, suggestionMap),
      editorProps: {
        handleKeyDown: (view, event) => {
          const mention = activeMentionRef.current;
          if (mention) {
            if (event.key === "ArrowDown") {
              const filtered = filteredSuggestionsRef.current;
              if (filtered.length > 0) {
                event.preventDefault();
                const key = `${mention.from}:${mention.query}`;
                setMentionNavigation((prev) => ({
                  key,
                  index: prev.key === key ? (prev.index + 1) % filtered.length : 0,
                }));
                return true;
              }
            }
            if (event.key === "ArrowUp") {
              const filtered = filteredSuggestionsRef.current;
              if (filtered.length > 0) {
                event.preventDefault();
                const key = `${mention.from}:${mention.query}`;
                setMentionNavigation((prev) => ({
                  key,
                  index:
                    prev.key === key
                      ? (prev.index - 1 + filtered.length) % filtered.length
                      : filtered.length - 1,
                }));
                return true;
              }
            }
            if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
              event.preventDefault();
              const filtered = filteredSuggestionsRef.current;
              if (filtered.length > 0) {
                const idx = selectedIndexRef.current;
                insertSuggestionDirectly(
                  editor!,
                  filtered[Math.min(idx, filtered.length - 1)] ?? filtered[0],
                  mention,
                );
              }
              return true;
            }
            if (event.key === "Escape" || event.key === "Tab") {
              event.preventDefault();
              setActiveMention(null);
              return true;
            }
          }
          if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            onSubmitRef.current();
            return true;
          }
          if (event.key === "Enter" && event.shiftKey) {
            event.preventDefault();
            editor?.chain().focus().setHardBreak().run();
            return true;
          }
          return false;
        },
        handlePaste: (view, event) => {
          const files = Array.from(event.clipboardData?.files ?? []);
          if (files.length > 0 && onFilesRef.current) {
            event.preventDefault();
            onFilesRef.current(files);
            return true;
          }
          event.preventDefault();
          const pastedText = event.clipboardData?.getData("text/plain") ?? "";
          if (pastedText && editor) {
            editor.commands.insertContent(pastedText);
            requestAnimationFrame(refreshEditorMetrics);
          }
          return true;
        },
        attributes: {
          class:
            "min-h-[52px] whitespace-pre-wrap break-words bg-transparent px-1.5 py-1 text-[13.5px] leading-6 text-foreground outline-none [word-break:break-word]",
        },
      },
      onCreate({ editor: createdEditor }) {
        lastSerializedValueRef.current = serializeEditor(createdEditor.getJSON() as Record<string, unknown>);
      },
      onUpdate({ editor: currentEditor }) {
        const serialized = serializeEditor(currentEditor.getJSON() as Record<string, unknown>);
        lastSerializedValueRef.current = serialized;
        onChange(serialized);
        setActiveMention(getActiveMentionFromEditor(currentEditor, anchorRef));
        requestAnimationFrame(refreshEditorMetrics);
      },
      onSelectionUpdate({ editor: currentEditor }) {
        setActiveMention(getActiveMentionFromEditor(currentEditor, anchorRef));
      },
    },
    [],
  );

  useLayoutEffect(() => {
    if (!editor) return;

    refreshEditorMetrics();
    const observer = new ResizeObserver(refreshEditorMetrics);
    observer.observe(editor.view.dom);
    window.addEventListener("resize", refreshEditorMetrics);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", refreshEditorMetrics);
    };
  }, [editor, refreshEditorMetrics]);

  useEffect(() => {
    if (!editor) return;
    if (lastSerializedValueRef.current === value) return;
    editor.commands.setContent(parseInputToDoc(value, suggestionMap), false);
    lastSerializedValueRef.current = value;
    setActiveMention(getActiveMentionFromEditor(editor, anchorRef));
  }, [editor, suggestionMap, value]);

  useEffect(() => {
    if (!editor || focusRevision === undefined) return;
    if (lastFocusRevisionRef.current === focusRevision) return;

    lastFocusRevisionRef.current = focusRevision;
    requestAnimationFrame(() => {
      editor.commands.focus("end");
      refreshEditorMetrics();
    });
  }, [editor, focusRevision, refreshEditorMetrics]);

  const insertSuggestion = useCallback(
    (suggestion: ComposerMentionSuggestion) => {
      if (!editor || !activeMention) return;
      insertSuggestionDirectly(editor, suggestion, activeMention);
    },
    [activeMention, editor, insertSuggestionDirectly],
  );

  const handleEditorScroll = useCallback(() => {
    refreshEditorMetrics();
  }, [refreshEditorMetrics]);

  const dropdownStyle = useMemo(() => {
    if (!activeMention) return null;
    const PADDING = 12;
    const ITEM_H = 38;
    const HEADER_H = 28;
    const CONTENT_PADDINGS = 8;

    const groupCount = MENTION_KIND_GROUP_ORDER.filter((kind) =>
      filteredSuggestions.some((s) => s.kind === kind),
    ).length;

    const visibleItems = Math.min(filteredSuggestions.length || 1, 8);
    const maxHeightByItems = visibleItems * ITEM_H + Math.max(groupCount - 1, 0) * HEADER_H + CONTENT_PADDINGS;

    const spaceBelow = window.innerHeight - activeMention.viewportBottom - PADDING;
    const spaceAbove = activeMention.viewportTop - PADDING;
    const openDownward = spaceBelow >= Math.min(maxHeightByItems, 200) || spaceBelow >= spaceAbove;

    const availableSpace = openDownward ? spaceBelow : spaceAbove;
    const maxH = Math.max(120, Math.min(maxHeightByItems, availableSpace));

    const estimatedWidth = Math.min(480, window.innerWidth - PADDING * 2);
    const left = Math.min(
      Math.max(PADDING, activeMention.viewportLeft),
      Math.max(PADDING, window.innerWidth - estimatedWidth - PADDING),
    );

    const top = openDownward
      ? activeMention.viewportBottom + 8
      : Math.max(PADDING, activeMention.viewportTop - maxH - 8);

    return { left, top, maxHeight: maxH };
  }, [activeMention, filteredSuggestions.length]);

  return (
    <div ref={anchorRef} className="relative">
      {!value && (
        <div className="pointer-events-none absolute inset-x-1.5 top-1 select-none text-[13.5px] leading-6 text-muted-foreground/75 dark:text-zinc-400">
          Ask anything, @ to mention, / for actions...
        </div>
      )}

      <motion.div
        animate={{ height: editorHeight }}
        className="relative overflow-hidden"
        initial={false}
        transition={
          shouldReduceMotion
            ? { duration: 0 }
            : { duration: 0.24, ease: [0.22, 1, 0.36, 1] }
        }
      >
        <div
          ref={scrollAreaRef}
          onScroll={handleEditorScroll}
          className={cn(
            "h-full pr-2",
            isEditorOverflowing
              ? "overflow-y-auto [scrollbar-width:thin]"
              : "overflow-hidden",
          )}
        >
          <EditorContent editor={editor} />
        </div>

        {isEditorOverflowing ? (
          <div className="pointer-events-none absolute bottom-2 right-0 top-2 w-px overflow-hidden rounded-full bg-border/60">
            <motion.div
              className="absolute left-0 w-full rounded-full bg-muted-foreground/45"
              style={{
                height: "34%",
              }}
              animate={{
                top: `${Math.min(Math.max(scrollProgress, 0), 1) * 66}%`,
              }}
              transition={
                shouldReduceMotion
                  ? { duration: 0 }
                  : { duration: 0.16, ease: [0.22, 1, 0.36, 1] }
              }
            />
          </div>
        ) : null}
      </motion.div>

      {activeMention && dropdownStyle ? createPortal(
        <div
          className="fixed z-[100] w-fit min-w-[16rem] max-w-[min(30rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-border/40 bg-background/80 shadow-[0_12px_40px_-8px_rgba(0,0,0,0.18),0_2px_8px_-2px_rgba(0,0,0,0.08)] backdrop-blur-xl dark:shadow-[0_12px_40px_-8px_rgba(0,0,0,0.45),0_2px_8px_-2px_rgba(0,0,0,0.2)]"
          style={{
            ...dropdownStyle,
            maxHeight: dropdownStyle.maxHeight,
          }}
        >
          <div className="overflow-y-auto p-1 [scrollbar-width:thin]" style={{ maxHeight: dropdownStyle.maxHeight }}>
            {filteredSuggestions.length > 0 ? (() => {
              const grouped = MENTION_KIND_GROUP_ORDER
                .map((kind) => ({
                  kind,
                  items: filteredSuggestions.filter((s) => s.kind === kind),
                }))
                .filter((g) => g.items.length > 0);

              let flatIndex = 0;

              return grouped.map((group, gi) => (
                <div key={group.kind} className={gi > 0 ? "mt-1.5" : undefined}>
                  <div className="flex items-center gap-1.5 px-2.5 pb-0.5 pt-1.5">
                    <span
                      className={cn(
                        "flex size-4 shrink-0 items-center justify-center rounded",
                        MENTION_KIND_ICON_COLORS[group.kind],
                      )}
                    >
                      {getMentionSuggestionIcon(group.kind)}
                    </span>
                    <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground/45">
                      {MENTION_KIND_LABELS[group.kind]}
                    </span>
                  </div>
                  {group.items.map((suggestion) => {
                    const index = flatIndex++;
                    return (
                      <button
                        key={suggestion.id}
                        type="button"
                        data-selected={index === selectedIndex ? "true" : undefined}
                        ref={(el) => {
                          if (index === selectedIndex && el) {
                            el.scrollIntoView({ block: "nearest" });
                          }
                        }}
                        onMouseEnter={() =>
                          setMentionNavigation({
                            key: activeMentionKey,
                            index,
                          })
                        }
                        onMouseDown={(event) => {
                          event.preventDefault();
                          insertSuggestion(suggestion);
                        }}
                        className={cn(
                          "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left transition-colors duration-100",
                          index === selectedIndex
                            ? "bg-accent/70 text-accent-foreground"
                            : "hover:bg-muted/50",
                        )}
                      >
                        <span
                          className={cn(
                            "flex size-5 shrink-0 items-center justify-center rounded",
                            MENTION_KIND_ICON_COLORS[suggestion.kind],
                          )}
                        >
                          {getMentionSuggestionIcon(suggestion.kind, suggestion.filePath)}
                        </span>
                        <span className="flex min-w-0 flex-col gap-px">
                          <span className="truncate text-[13px] font-medium leading-snug">
                            {suggestion.label}
                          </span>
                          <span className="truncate text-[11px] leading-tight text-muted-foreground/50">
                            {suggestion.description}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              ));
            })() : (
              <div className="rounded-lg px-3 py-2.5 text-xs text-muted-foreground/60">
                没有匹配的上下文项
              </div>
            )}
          </div>
        </div>,
        document.body,
      ) : null}
    </div>
  );
}
