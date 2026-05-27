"use client";

import { cn } from "@/lib/utils";
import { Node, mergeAttributes } from "@tiptap/core";
import { EditorContent, NodeViewWrapper, ReactNodeViewRenderer, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  FileCodeIcon,
  FolderOpenIcon,
  GlobeIcon,
  LightbulbIcon,
  MessageSquareIcon,
  PencilIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

type MentionKind = "workspace" | "file" | "change" | "element" | "skill";

export type ComposerMentionSuggestion = {
  id: string;
  kind: MentionKind;
  label: string;
  description: string;
  insertValue: string;
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
  onChange: (value: string) => void;
  onSubmit: () => void;
};

type MentionAttrs = {
  id: string;
  label: string;
  kind: MentionKind;
};

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

function getPathLeaf(input: string) {
  const normalized = input.replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).pop() ?? input;
}

function getMentionSuggestionIcon(kind: MentionKind) {
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
        {getMentionSuggestionIcon(attrs.kind)}
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
  onChange,
  onSubmit,
}: ChatComposerEditorProps) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const lastSerializedValueRef = useRef(value);
  const [activeMention, setActiveMention] = useState<ActiveMention | null>(null);
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
        attributes: {
          class:
            "min-h-[80px] whitespace-pre-wrap break-words bg-transparent px-1 py-1.5 text-sm leading-6 text-foreground outline-none [word-break:break-word]",
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
      },
      onSelectionUpdate({ editor: currentEditor }) {
        setActiveMention(getActiveMentionFromEditor(currentEditor, anchorRef));
      },
    },
    [],
  );

  useEffect(() => {
    if (!editor) return;
    if (lastSerializedValueRef.current === value) return;
    editor.commands.setContent(parseInputToDoc(value, suggestionMap), false);
    lastSerializedValueRef.current = value;
    setActiveMention(getActiveMentionFromEditor(editor, anchorRef));
  }, [editor, suggestionMap, value]);

  const insertSuggestion = useCallback(
    (suggestion: ComposerMentionSuggestion) => {
      if (!editor || !activeMention) return;
      insertSuggestionDirectly(editor, suggestion, activeMention);
    },
    [activeMention, editor, insertSuggestionDirectly],
  );

  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLDivElement>) => {
      if (!editor) return;
      e.preventDefault();
      const pastedText = e.clipboardData.getData("text/plain");
      editor.chain().focus().insertContent(pastedText).run();
    },
    [editor],
  );

  const dropdownStyle = useMemo(() => {
    if (!activeMention) return null;
    const estimatedHeight = Math.min(filteredSuggestions.length || 1, 6) * 44 + 12;
    const estimatedWidth = Math.min(480, window.innerWidth - 32);
    const fitsBelow =
      activeMention.viewportBottom + estimatedHeight < window.innerHeight - 16;
    return {
      left: Math.min(
        Math.max(12, activeMention.viewportLeft),
        Math.max(12, window.innerWidth - estimatedWidth - 12),
      ),
      top: fitsBelow
        ? activeMention.viewportBottom + 10
        : Math.max(12, activeMention.viewportTop - estimatedHeight - 10),
    };
  }, [activeMention, filteredSuggestions.length]);

  return (
    <div ref={anchorRef} className="relative">
      {!value && (
        <div className="pointer-events-none absolute inset-x-1 top-1.5 text-sm leading-6 text-muted-foreground">
          告诉我想实现什么，输入 @ 可快速引用技能、工作区、文件或页面元素...
        </div>
      )}

      <div onPaste={handlePaste}>
        <EditorContent editor={editor} />
      </div>

      {activeMention && dropdownStyle ? createPortal(
        <div
          className="fixed z-[100] w-fit min-w-[16rem] max-w-[min(30rem,calc(100vw-2rem))] rounded-xl border border-border/50 bg-popover/98 p-1 shadow-xl backdrop-blur"
          style={dropdownStyle}
        >
          {filteredSuggestions.length > 0 ? (
            filteredSuggestions.map((suggestion, index) => (
              <button
                key={suggestion.id}
                type="button"
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
                  "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left",
                  index === selectedIndex && "bg-accent text-accent-foreground",
                )}
              >
                <span
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded-md",
                    MENTION_KIND_ICON_COLORS[suggestion.kind],
                  )}
                >
                  {getMentionSuggestionIcon(suggestion.kind)}
                </span>
                <span className="flex min-w-0 flex-col gap-px">
                  <span className="truncate text-[13px] font-medium">
                    {suggestion.label}
                  </span>
                  <span className="truncate text-[11px] text-muted-foreground/70">
                    {suggestion.description}
                  </span>
                </span>
              </button>
            ))
          ) : (
            <div className="rounded-lg px-2.5 py-2 text-xs text-muted-foreground">
              没有匹配的上下文项
            </div>
          )}
        </div>,
        document.body,
      ) : null}
    </div>
  );
}
