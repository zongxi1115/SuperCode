"use client";

import { Node as TiptapNode, mergeAttributes } from "@tiptap/core";
import { EditorContent, NodeViewWrapper, ReactNodeViewRenderer, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { marked } from "marked";
import TurndownService from "turndown";
import {
  Bold,
  Code,
  FileCodeIcon,
  Heading2,
  Italic,
  List,
  ListOrdered,
  Quote,
  Strikethrough,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { FileTreeNode } from "@/lib/app-types";

type FileMentionSuggestion = {
  id: string;
  label: string;
  description: string;
  value: string;
  insertValue: string;
};

type MentionAttrs = {
  id: string;
  label: string;
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

type ToolbarButtonProps = {
  active?: boolean;
  label: string;
  onMouseDown: (event: React.MouseEvent<HTMLButtonElement>) => void;
  children: ReactNode;
};

type KanbanDescriptionEditorProps = {
  value: string;
  fileTree?: FileTreeNode[];
  isExpanded?: boolean;
  className?: string;
  onChange: (markdown: string) => void;
};

const turndown = new TurndownService({
  bulletListMarker: "-",
  codeBlockStyle: "fenced",
  headingStyle: "atx",
});

turndown.addRule("fileMention", {
  filter: (node) =>
    node instanceof HTMLElement &&
    node.tagName === "SPAN" &&
    node.hasAttribute("data-file-mention-id"),
  replacement: (_content, node) => {
    if (!(node instanceof HTMLElement)) return "";
    return formatMentionToken(node.getAttribute("data-file-mention-id") ?? "");
  },
});

turndown.addRule("strikethrough", {
  filter: ["del", "s", "strike"],
  replacement: (content) => `~~${content}~~`,
});

function normalizeMarkdown(value: string) {
  return value.replace(/\r\n/g, "\n").trimEnd();
}

function formatMentionToken(value: string) {
  return `@[${value.replaceAll("]", "\\]")}]`;
}

function decodeMentionTokenValue(value: string) {
  return value.replace(/\\\]/g, "]");
}

function getPathLeaf(input: string) {
  const normalized = input.replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).pop() ?? input;
}

function decorateMentionTokens(html: string) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, "text/html");
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  const textNodes: Text[] = [];

  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!(node instanceof Text)) continue;
    const parent = node.parentElement;
    if (parent?.closest("code, pre, span[data-file-mention-id]")) continue;
    textNodes.push(node);
  }

  for (const node of textNodes) {
    const text = node.nodeValue ?? "";
    const tokenRe = /@\[((?:\\.|[^\]])*)\]/g;
    if (!tokenRe.test(text)) continue;

    tokenRe.lastIndex = 0;
    const fragment = doc.createDocumentFragment();
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = tokenRe.exec(text)) !== null) {
      const prefix = text.slice(lastIndex, match.index);
      if (prefix) fragment.append(doc.createTextNode(prefix));

      const mentionValue = decodeMentionTokenValue(match[1] ?? "");
      const mention = doc.createElement("span");
      mention.setAttribute("data-file-mention-id", mentionValue);
      mention.setAttribute("data-file-mention-label", getPathLeaf(mentionValue));
      mention.textContent = getPathLeaf(mentionValue);
      fragment.append(mention);

      lastIndex = match.index + match[0].length;
    }

    const suffix = text.slice(lastIndex);
    if (suffix) fragment.append(doc.createTextNode(suffix));
    node.replaceWith(fragment);
  }

  return doc.body.innerHTML || "<p></p>";
}

function markdownToHtml(markdown: string) {
  const normalized = normalizeMarkdown(markdown).trim();
  if (!normalized) return "<p></p>";
  const html = marked.parse(normalized, {
    async: false,
    breaks: true,
    gfm: true,
  }) as string;
  return decorateMentionTokens(html);
}

function htmlToMarkdown(html: string) {
  return normalizeMarkdown(turndown.turndown(html));
}

function buildFileSuggestions(fileTree: FileTreeNode[]) {
  const suggestions: FileMentionSuggestion[] = [];
  const seen = new Set<string>();

  const visit = (nodes: FileTreeNode[]) => {
    for (const node of nodes) {
      if (node.type === "file" && node.path) {
        const key = node.path.toLowerCase();
        if (!seen.has(key)) {
          seen.add(key);
          suggestions.push({
            id: `file:${node.path}`,
            label: node.name || getPathLeaf(node.path),
            description: node.path,
            value: node.path,
            insertValue: formatMentionToken(node.path),
          });
        }
      }
      if (node.children) visit(node.children);
    }
  };

  visit(fileTree);
  return suggestions;
}

function getActiveMentionFromEditor(
  editor: NonNullable<ReturnType<typeof useEditor>>,
  anchor: HTMLDivElement | null,
): ActiveMention | null {
  if (editor.view.composing || !editor.state.selection.empty) return null;

  const { from } = editor.state.selection;
  const $from = editor.state.selection.$from;
  const textBefore = $from.parent.textBetween(0, $from.parentOffset, "\n", "\0");
  const mentionStart = textBefore.lastIndexOf("@");
  if (mentionStart < 0) return null;

  const previousChar = textBefore[mentionStart - 1];
  if (previousChar && !/[\s([{"'`]/.test(previousChar)) return null;

  const query = textBefore.slice(mentionStart + 1);
  if (/[\s@]/.test(query)) return null;

  const coords = editor.view.coordsAtPos(from);
  const anchorRect = anchor?.getBoundingClientRect();
  return {
    query,
    from: from - query.length - 1,
    to: from,
    left: coords.left - (anchorRect?.left ?? 0) + (anchor?.scrollLeft ?? 0),
    top: coords.top - (anchorRect?.top ?? 0) + (anchor?.scrollTop ?? 0),
    bottom: coords.bottom - (anchorRect?.top ?? 0) + (anchor?.scrollTop ?? 0),
    viewportLeft: coords.left,
    viewportTop: coords.top,
    viewportBottom: coords.bottom,
  };
}

function FileMentionBadgeView(props: { node: { attrs: MentionAttrs } }) {
  const attrs = props.node.attrs;
  return (
    <NodeViewWrapper
      as="span"
      className="mx-0.5 inline-flex max-w-[18rem] select-none items-center gap-1 rounded-md border border-blue-200/80 bg-blue-50/95 px-1.5 py-0.5 align-baseline text-blue-950 shadow-sm dark:border-blue-900/80 dark:bg-blue-950/70 dark:text-blue-100"
      contentEditable={false}
      data-file-mention-id={attrs.id}
      data-file-mention-label={attrs.label}
    >
      <span className="flex size-4 shrink-0 items-center justify-center rounded-sm bg-blue-100 text-blue-600 dark:bg-blue-950 dark:text-blue-300">
        <FileCodeIcon className="size-3.5" />
      </span>
      <span className="truncate">{attrs.label || getPathLeaf(attrs.id)}</span>
    </NodeViewWrapper>
  );
}

const FileMentionNode = TiptapNode.create({
  name: "fileMention",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      id: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-file-mention-id") ?? "",
        renderHTML: (attributes: Record<string, unknown>) => ({
          "data-file-mention-id": attributes.id,
        }),
      },
      label: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-file-mention-label") ?? "",
        renderHTML: (attributes: Record<string, unknown>) => ({
          "data-file-mention-label": attributes.label,
        }),
      },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-file-mention-id]" }];
  },

  renderHTML({ node, HTMLAttributes }) {
    const attrs = node.attrs as MentionAttrs;
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-file-mention-id": attrs.id,
        "data-file-mention-label": attrs.label,
      }),
      attrs.label || getPathLeaf(attrs.id),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(FileMentionBadgeView);
  },
});

function ToolbarButton({ active, label, onMouseDown, children }: ToolbarButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onMouseDown={onMouseDown}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors",
        active
          ? "bg-violet-100 text-violet-700 dark:bg-violet-950/60 dark:text-violet-300"
          : "hover:bg-muted hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function KanbanDescriptionEditor({
  value,
  fileTree = [],
  isExpanded = false,
  className,
  onChange,
}: KanbanDescriptionEditorProps) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const lastMarkdownRef = useRef(normalizeMarkdown(value));
  const isApplyingExternalValueRef = useRef(false);
  const onChangeRef = useRef(onChange);
  const suggestions = useMemo(() => buildFileSuggestions(fileTree), [fileTree]);
  const [activeMention, setActiveMention] = useState<ActiveMention | null>(null);
  const [mentionNavigation, setMentionNavigation] = useState<{
    key: string | null;
    index: number;
  }>({ key: null, index: 0 });

  const filteredSuggestions = useMemo(() => {
    if (!activeMention) return [];
    const query = activeMention.query.trim().toLowerCase();
    const items = query
      ? suggestions.filter((suggestion) =>
          [suggestion.label, suggestion.description, suggestion.insertValue].some((item) =>
            item.toLowerCase().includes(query),
          ),
        )
      : suggestions;
    return items.slice(0, 20);
  }, [activeMention, suggestions]);

  const activeMentionKey = activeMention ? `${activeMention.from}:${activeMention.query}` : null;
  const selectedIndex =
    activeMentionKey && mentionNavigation.key === activeMentionKey
      ? Math.min(mentionNavigation.index, Math.max(filteredSuggestions.length - 1, 0))
      : 0;

  const activeMentionRef = useRef(activeMention);
  const filteredSuggestionsRef = useRef(filteredSuggestions);
  const selectedIndexRef = useRef(selectedIndex);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    activeMentionRef.current = activeMention;
  }, [activeMention]);

  useEffect(() => {
    filteredSuggestionsRef.current = filteredSuggestions;
  }, [filteredSuggestions]);

  useEffect(() => {
    selectedIndexRef.current = selectedIndex;
  }, [selectedIndex]);

  const insertSuggestionDirectly = useCallback(
    (
      editorInstance: NonNullable<ReturnType<typeof useEditor>>,
      suggestion: FileMentionSuggestion,
      mention: ActiveMention,
    ) => {
      editorInstance
        .chain()
        .focus()
        .insertContentAt(
          { from: mention.from, to: mention.to },
          [
            {
              type: "fileMention",
              attrs: {
                id: suggestion.value,
                label: suggestion.label,
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
          hardBreak: true,
        }),
        FileMentionNode,
      ],
      content: markdownToHtml(value),
      editorProps: {
        attributes: {
          class:
            "min-h-[180px] whitespace-pre-wrap break-words px-3 py-3 text-sm leading-6 text-foreground outline-none [word-break:break-word]",
        },
        handleKeyDown: (_view, event) => {
          const mention = activeMentionRef.current;
          if (!mention) return false;

          if (event.key === "ArrowDown" && filteredSuggestionsRef.current.length > 0) {
            event.preventDefault();
            const key = `${mention.from}:${mention.query}`;
            setMentionNavigation((prev) => ({
              key,
              index: prev.key === key ? (prev.index + 1) % filteredSuggestionsRef.current.length : 0,
            }));
            return true;
          }

          if (event.key === "ArrowUp" && filteredSuggestionsRef.current.length > 0) {
            event.preventDefault();
            const key = `${mention.from}:${mention.query}`;
            setMentionNavigation((prev) => ({
              key,
              index:
                prev.key === key
                  ? (prev.index - 1 + filteredSuggestionsRef.current.length) %
                    filteredSuggestionsRef.current.length
                  : filteredSuggestionsRef.current.length - 1,
            }));
            return true;
          }

          if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
            const currentEditor = editor;
            const filtered = filteredSuggestionsRef.current;
            if (!currentEditor || filtered.length === 0) return false;
            event.preventDefault();
            insertSuggestionDirectly(
              currentEditor,
              filtered[Math.min(selectedIndexRef.current, filtered.length - 1)] ?? filtered[0],
              mention,
            );
            return true;
          }

          if (event.key === "Escape" || event.key === "Tab") {
            event.preventDefault();
            setActiveMention(null);
            return true;
          }

          return false;
        },
      },
      onCreate({ editor: createdEditor }) {
        lastMarkdownRef.current = htmlToMarkdown(createdEditor.getHTML());
      },
      onUpdate({ editor: currentEditor }) {
        const markdown = htmlToMarkdown(currentEditor.getHTML());
        lastMarkdownRef.current = markdown;
        if (!isApplyingExternalValueRef.current) {
          onChangeRef.current(markdown);
        }
        setActiveMention(getActiveMentionFromEditor(currentEditor, anchorRef.current));
      },
      onSelectionUpdate({ editor: currentEditor }) {
        setActiveMention(getActiveMentionFromEditor(currentEditor, anchorRef.current));
      },
    },
    [],
  );

  useEffect(() => {
    if (!editor) return;
    const normalized = normalizeMarkdown(value);
    if (normalized === lastMarkdownRef.current) return;
    isApplyingExternalValueRef.current = true;
    editor.commands.setContent(markdownToHtml(normalized), false);
    lastMarkdownRef.current = normalized;
    setActiveMention(getActiveMentionFromEditor(editor, anchorRef.current));
    queueMicrotask(() => {
      isApplyingExternalValueRef.current = false;
    });
  }, [editor, value]);

  const insertSuggestion = useCallback(
    (suggestion: FileMentionSuggestion) => {
      if (!editor || !activeMention) return;
      insertSuggestionDirectly(editor, suggestion, activeMention);
    },
    [activeMention, editor, insertSuggestionDirectly],
  );

  const dropdownStyle = useMemo(() => {
    if (!activeMention) return null;
    const estimatedHeight = Math.min(filteredSuggestions.length || 1, 6) * 44 + 12;
    const estimatedWidth = Math.min(480, window.innerWidth - 32);
    const fitsBelow = activeMention.viewportBottom + estimatedHeight < window.innerHeight - 16;
    return {
      left: Math.min(
        Math.max(12, activeMention.viewportLeft),
        Math.max(12, window.innerWidth - estimatedWidth - 12),
      ),
      top: fitsBelow
        ? activeMention.viewportBottom + 8
        : Math.max(12, activeMention.viewportTop - estimatedHeight - 8),
    };
  }, [activeMention, filteredSuggestions.length]);

  const characterCount = editor?.state.doc.textContent.length ?? normalizeMarkdown(value).length;

  return (
    <div
      className={cn(
        "kanban-description-editor flex min-h-0 flex-col overflow-hidden rounded-lg border border-violet-400/80 bg-background shadow-sm transition-colors focus-within:border-violet-500",
        className,
      )}
    >
      <div className="flex min-h-14 shrink-0 flex-wrap items-center gap-1 border-b border-border/55 bg-background px-4 py-2.5">
        <ToolbarButton
          label="加粗"
          active={editor?.isActive("bold")}
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().toggleBold().run();
          }}
        >
          <Bold className="size-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="斜体"
          active={editor?.isActive("italic")}
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().toggleItalic().run();
          }}
        >
          <Italic className="size-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="删除线"
          active={editor?.isActive("strike")}
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().toggleStrike().run();
          }}
        >
          <Strikethrough className="size-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="行内代码"
          active={editor?.isActive("code")}
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().toggleCode().run();
          }}
        >
          <Code className="size-3.5" />
        </ToolbarButton>
        <div className="mx-2 h-6 w-px bg-border/70" />
        <ToolbarButton
          label="二级标题"
          active={editor?.isActive("heading", { level: 2 })}
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().toggleHeading({ level: 2 }).run();
          }}
        >
          <Heading2 className="size-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="无序列表"
          active={editor?.isActive("bulletList")}
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().toggleBulletList().run();
          }}
        >
          <List className="size-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="有序列表"
          active={editor?.isActive("orderedList")}
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().toggleOrderedList().run();
          }}
        >
          <ListOrdered className="size-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="引用块"
          active={editor?.isActive("blockquote")}
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().toggleBlockquote().run();
          }}
        >
          <Quote className="size-3.5" />
        </ToolbarButton>
      </div>

      <div className={cn("relative min-h-0", isExpanded ? "flex-1" : "min-h-[180px]")}>
        <div
          ref={anchorRef}
          className={cn(
            "relative min-h-[180px] overflow-auto pb-12",
            isExpanded ? "h-full min-h-[420px]" : "max-h-[320px]",
          )}
        >
        {!value.trim() ? (
          <div className="pointer-events-none absolute left-5 top-5 text-sm leading-6 text-muted-foreground">
            写下卡片背景、决策和待办...
          </div>
        ) : null}
        <EditorContent editor={editor} />

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
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-600 dark:bg-blue-950/60 dark:text-blue-300">
                    <FileCodeIcon className="size-3.5" />
                  </span>
                  <span className="flex min-w-0 flex-col gap-px">
                    <span className="truncate text-[13px] font-medium">{suggestion.label}</span>
                    <span className="truncate text-[11px] text-muted-foreground/70">
                      {suggestion.description}
                    </span>
                  </span>
                </button>
              ))
            ) : (
              <div className="rounded-lg px-2.5 py-2 text-xs text-muted-foreground">
                没有匹配的文件
              </div>
            )}
          </div>,
          document.body,
        ) : null}
        </div>

        <div className="pointer-events-none absolute bottom-3 right-4 flex items-center gap-1.5 text-[11px] text-muted-foreground/60">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500/70" />
          <span>{characterCount}</span>
        </div>
      </div>

      <style>{`
        .kanban-description-editor .ProseMirror h1,
        .kanban-description-editor .ProseMirror h2,
        .kanban-description-editor .ProseMirror h3 {
          font-weight: 650;
          line-height: 1.3;
          margin: 0.35rem 0 0.2rem;
        }
        .kanban-description-editor .ProseMirror h1 {
          font-size: 1.25rem;
        }
        .kanban-description-editor .ProseMirror h2 {
          font-size: 1.1rem;
        }
        .kanban-description-editor .ProseMirror h3 {
          font-size: 1rem;
        }
        .kanban-description-editor .ProseMirror p {
          margin: 0.15rem 0;
        }
        .kanban-description-editor .ProseMirror ul,
        .kanban-description-editor .ProseMirror ol {
          margin: 0.35rem 0;
          padding-left: 1.25rem;
        }
        .kanban-description-editor .ProseMirror ul {
          list-style: disc;
        }
        .kanban-description-editor .ProseMirror ol {
          list-style: decimal;
        }
        .kanban-description-editor .ProseMirror blockquote {
          border-left: 3px solid var(--border);
          color: var(--muted-foreground);
          margin: 0.45rem 0;
          padding-left: 0.75rem;
        }
        .kanban-description-editor .ProseMirror pre {
          background: var(--muted);
          border-radius: 0.375rem;
          margin: 0.5rem 0;
          overflow-x: auto;
          padding: 0.65rem 0.75rem;
        }
        .kanban-description-editor .ProseMirror code {
          background: var(--muted);
          border-radius: 0.25rem;
          font-size: 0.88em;
          padding: 0.1rem 0.25rem;
        }
        .kanban-description-editor .ProseMirror pre code {
          background: transparent;
          border-radius: 0;
          padding: 0;
        }
      `}</style>
    </div>
  );
}
