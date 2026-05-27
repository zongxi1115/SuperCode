"use client";

import { cn } from "@/lib/utils";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Mark, mergeAttributes } from "@tiptap/core";
import { Table } from "@tiptap/extension-table";
import { TableRow } from "@tiptap/extension-table-row";
import { TableCell } from "@tiptap/extension-table-cell";
import { TableHeader } from "@tiptap/extension-table-header";
import { marked } from "marked";
import TurndownService from "turndown";
import {
  Bold,
  Code,
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  Minus,
  Quote,
  Strikethrough,
  Italic,
  MessageSquarePlus,
  X,
  TableIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";

export type Annotation = {
  id: string;
  text: string;
  selectedText: string;
};

type SlashCommand = {
  id: string;
  label: string;
  description: string;
  keywords: string[];
  run: () => void;
};

type SlashMenuState = {
  from: number;
  to: number;
  query: string;
  left: number;
  top: number;
  bottom: number;
  viewportLeft: number;
  viewportTop: number;
  viewportBottom: number;
};

type PlanRichTextEditorProps = {
  value: string;
  onChange: (markdown: string) => void;
  autoFocus?: boolean;
  onAnnotationsChange?: (annotations: Annotation[]) => void;
};

const AnnotationMark = Mark.create({
  name: "annotation",

  addAttributes() {
    return {
      annotationId: {
        default: null,
        parseHTML: (el: HTMLElement) => el.getAttribute("data-annotation-id"),
        renderHTML: (attrs: Record<string, unknown>) => ({
          "data-annotation-id": attrs.annotationId,
        }),
      },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-annotation-id]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        class: "annotation-highlight",
      }),
      0,
    ];
  },

  addCommands() {
    return {
      setAnnotation:
        (annotationId: string) =>
        ({ commands }) => {
          return commands.setMark(this.name, { annotationId });
        },
      unsetAnnotation:
        () =>
        ({ commands }) => {
          return commands.unsetMark(this.name);
        },
    };
  },

  addKeyboardShortcuts() {
    return {};
  },
});

const turndown = new TurndownService({
  bulletListMarker: "-",
  codeBlockStyle: "fenced",
  headingStyle: "atx",
});

turndown.addRule("annotation", {
  filter: "span[data-annotation-id]",
  replacement: (content: string, node: HTMLElement) => {
    const id = node.getAttribute("data-annotation-id");
    return `{^${id}|${content}^}`;
  },
});

turndown.addRule("table", {
  filter: "table",
  replacement: (content: string) => content,
});

function normalizeMarkdown(value: string) {
  return value.replace(/\r\n/g, "\n").trimEnd();
}

function markdownToHtml(markdown: string) {
  const normalized = markdown.trim();
  if (!normalized) {
    return "<p></p>";
  }
  const html = marked.parse(normalized, { async: false }) as string;
  return html.replace(/\{\^([^}|]+)\|([^}]+)\^\}/g, (_match, id, content) => {
    return `<span data-annotation-id="${id}">${content}</span>`;
  });
}

function htmlToMarkdown(html: string) {
  return normalizeMarkdown(turndown.turndown(html));
}

function extractAnnotationIdsFromHtml(html: string): string[] {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, "text/html");
  const spans = doc.querySelectorAll("span[data-annotation-id]");
  const seen = new Set<string>();
  spans.forEach((span) => {
    const id = span.getAttribute("data-annotation-id");
    if (id) seen.add(id);
  });
  return Array.from(seen);
}

function getSlashMenuState(
  editor: NonNullable<ReturnType<typeof useEditor>>,
  anchorRect: DOMRect | null,
  scrollOffset: { x: number; y: number },
): SlashMenuState | null {
  if (editor.view.composing || !editor.state.selection.empty) return null;

  const { from } = editor.state.selection;
  const $from = editor.state.selection.$from;
  const textBefore = $from.parent.textBetween(0, $from.parentOffset, "\n", "\0");
  const slashIndex = textBefore.lastIndexOf("/");
  if (slashIndex < 0) return null;

  const previousChar = textBefore[slashIndex - 1];
  if (previousChar && !/\s/.test(previousChar)) {
    return null;
  }

  const query = textBefore.slice(slashIndex + 1);
  if (/\s/.test(query)) return null;

  const coords = editor.view.coordsAtPos(from);
  return {
    from: from - query.length - 1,
    to: from,
    query,
    left: coords.left - (anchorRect?.left ?? 0) + scrollOffset.x,
    top: coords.top - (anchorRect?.top ?? 0) + scrollOffset.y,
    bottom: coords.bottom - (anchorRect?.top ?? 0) + scrollOffset.y,
    viewportLeft: coords.left,
    viewportTop: coords.top,
    viewportBottom: coords.bottom,
  };
}

function ToolbarButton({
  active,
  label,
  onMouseDown,
  children,
}: {
  active?: boolean;
  label: string;
  onMouseDown: (event: React.MouseEvent<HTMLButtonElement>) => void;
  children: React.ReactNode;
}) {
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

type BubbleToolbarState = {
  left: number;
  top: number;
};

function BubbleToolbarButton({
  active,
  label,
  onMouseDown,
  children,
}: {
  active?: boolean;
  label: string;
  onMouseDown: (event: React.MouseEvent<HTMLButtonElement>) => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onMouseDown={onMouseDown}
      className={cn(
        "inline-flex h-7 items-center justify-center rounded px-1.5 text-muted-foreground transition-colors",
        active
          ? "bg-primary/15 text-primary"
          : "hover:bg-accent hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function PlanRichTextEditor({
  value,
  onChange,
  autoFocus = false,
  onAnnotationsChange,
}: PlanRichTextEditorProps) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const lastMarkdownRef = useRef(normalizeMarkdown(value));
  const isApplyingExternalValueRef = useRef(false);
  const [slashMenu, setSlashMenu] = useState<SlashMenuState | null>(null);
  const [slashNavigation, setSlashNavigation] = useState<{
    key: string | null;
    index: number;
  }>({
    key: null,
    index: 0,
  });
  const [bubbleToolbar, setBubbleToolbar] = useState<BubbleToolbarState | null>(null);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [annotationPopup, setAnnotationPopup] = useState<{
    left: number;
    top: number;
  } | null>(null);
  const annotationInputRef = useRef<HTMLInputElement>(null);
  const pendingAnnotationIdRef = useRef<string | null>(null);
  const pendingSelectedTextRef = useRef<string>("");

  const syncAnnotations = useCallback(
    (html: string) => {
      const idsInDom = extractAnnotationIdsFromHtml(html);
      setAnnotations((prev) => {
        const kept = prev.filter((a) => idsInDom.includes(a.id));
        return kept;
      });
    },
    [],
  );

  useEffect(() => {
    onAnnotationsChange?.(annotations);
  }, [annotations, onAnnotationsChange]);

  const updateBubbleToolbar = useCallback((currentEditor: NonNullable<ReturnType<typeof useEditor>>) => {
    const { from, to, empty } = currentEditor.state.selection;
    if (empty || from === to) {
      setBubbleToolbar(null);
      return;
    }
    const anchorRect = anchorRef.current?.getBoundingClientRect();
    if (!anchorRect) {
      setBubbleToolbar(null);
      return;
    }
    const scrollLeft = anchorRef.current?.scrollLeft ?? 0;
    const scrollTop = anchorRef.current?.scrollTop ?? 0;
    const fromCoords = currentEditor.view.coordsAtPos(from);
    const toCoords = currentEditor.view.coordsAtPos(to);
    const left = (fromCoords.left + toCoords.left) / 2 - anchorRect.left + scrollLeft;
    const top = fromCoords.top - anchorRect.top + scrollTop - 10;
    setBubbleToolbar({ left, top });
  }, []);

  const editor = useEditor(
    {
      immediatelyRender: false,
      extensions: [
        StarterKit.configure({
          hardBreak: true,
        }),
        AnnotationMark,
        Table.configure({
          resizable: false,
        }),
        TableRow,
        TableCell,
        TableHeader,
      ],
      content: markdownToHtml(value),
      autofocus: autoFocus ? "end" : false,
      editorProps: {
        attributes: {
          class:
            "min-h-[420px] whitespace-pre-wrap break-words px-8 py-8 text-[15px] leading-7 text-foreground outline-none [word-break:break-word]",
        },
      },
      onCreate({ editor: createdEditor }) {
        lastMarkdownRef.current = htmlToMarkdown(createdEditor.getHTML());
        syncAnnotations(createdEditor.getHTML());
      },
      onUpdate({ editor: currentEditor }) {
        const markdown = htmlToMarkdown(currentEditor.getHTML());
        lastMarkdownRef.current = markdown;
        if (!isApplyingExternalValueRef.current) {
          onChange(markdown);
        }
        setSlashMenu(getSlashMenuState(currentEditor, anchorRef.current?.getBoundingClientRect() ?? null, { x: anchorRef.current?.scrollLeft ?? 0, y: anchorRef.current?.scrollTop ?? 0 }));
        updateBubbleToolbar(currentEditor);
        syncAnnotations(currentEditor.getHTML());
      },
      onSelectionUpdate({ editor: currentEditor }) {
        setSlashMenu(getSlashMenuState(currentEditor, anchorRef.current?.getBoundingClientRect() ?? null, { x: anchorRef.current?.scrollLeft ?? 0, y: anchorRef.current?.scrollTop ?? 0 }));
        updateBubbleToolbar(currentEditor);
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
    syncAnnotations(editor.getHTML());
    queueMicrotask(() => {
      isApplyingExternalValueRef.current = false;
    });
  }, [editor, syncAnnotations, value]);

  const slashCommands = useMemo<SlashCommand[]>(() => {
    if (!editor) return [];
    return [
      {
        id: "heading-1",
        label: "一级标题",
        description: "大标题，适合章节起始",
        keywords: ["h1", "title", "heading 1"],
        run: () => editor.chain().focus().toggleHeading({ level: 1 }).run(),
      },
      {
        id: "heading-2",
        label: "二级标题",
        description: "适合主分节",
        keywords: ["h2", "heading 2", "section"],
        run: () => editor.chain().focus().toggleHeading({ level: 2 }).run(),
      },
      {
        id: "heading-3",
        label: "三级标题",
        description: "适合较细的层级",
        keywords: ["h3", "heading 3", "subsection"],
        run: () => editor.chain().focus().toggleHeading({ level: 3 }).run(),
      },
      {
        id: "bullet-list",
        label: "无序列表",
        description: "适合要点罗列",
        keywords: ["list", "bullet", "ul"],
        run: () => editor.chain().focus().toggleBulletList().run(),
      },
      {
        id: "ordered-list",
        label: "有序列表",
        description: "适合步骤和编号",
        keywords: ["ordered", "numbered", "ol"],
        run: () => editor.chain().focus().toggleOrderedList().run(),
      },
      {
        id: "blockquote",
        label: "引用块",
        description: "适合强调说明或备注",
        keywords: ["quote", "blockquote", "remark"],
        run: () => editor.chain().focus().toggleBlockquote().run(),
      },
      {
        id: "code-block",
        label: "代码块",
        description: "适合粘贴命令或代码",
        keywords: ["code", "snippet", "fence"],
        run: () => editor.chain().focus().toggleCodeBlock().run(),
      },
      {
        id: "table",
        label: "表格",
        description: "插入3x3表格",
        keywords: ["table", "grid", "biaoge"],
        run: () =>
          editor
            .chain()
            .focus()
            .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
            .run(),
      },
      {
        id: "divider",
        label: "分割线",
        description: "插入章节分隔",
        keywords: ["divider", "rule", "separator"],
        run: () => editor.chain().focus().setHorizontalRule().run(),
      },
    ];
  }, [editor]);

  const filteredSlashCommands = useMemo(() => {
    if (!slashMenu) return [];
    const query = slashMenu.query.trim().toLowerCase();
    if (!query) return slashCommands;

    return slashCommands.filter((command) =>
      [command.label, command.description, ...command.keywords].some((item) =>
        item.toLowerCase().includes(query),
      ),
    );
  }, [slashCommands, slashMenu]);

  const slashMenuKey = slashMenu ? `${slashMenu.from}:${slashMenu.query}` : null;
  const selectedSlashIndex =
    slashMenuKey && slashNavigation.key === slashMenuKey
      ? Math.min(slashNavigation.index, Math.max(filteredSlashCommands.length - 1, 0))
      : 0;

  const executeSlashCommand = useCallback(
    (command: SlashCommand) => {
      if (!editor || !slashMenu) return;
      editor.chain().focus().deleteRange({ from: slashMenu.from, to: slashMenu.to }).run();
      command.run();
      setSlashMenu(null);
    },
    [editor, slashMenu],
  );

  const openAnnotationPopup = useCallback(() => {
    if (!editor) return;
    const { from, to, empty } = editor.state.selection;
    if (empty || from === to) return;

    const selectedText = editor.state.doc.textBetween(from, to, "\n");
    const id = `ann-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    pendingAnnotationIdRef.current = id;
    pendingSelectedTextRef.current = selectedText;

    const anchorRect = anchorRef.current?.getBoundingClientRect();
    if (!anchorRect) return;
    const scrollLeft = anchorRef.current?.scrollLeft ?? 0;
    const scrollTop = anchorRef.current?.scrollTop ?? 0;
    const fromCoords = editor.view.coordsAtPos(from);
    const toCoords = editor.view.coordsAtPos(to);
    const left = (fromCoords.left + toCoords.left) / 2 - anchorRect.left + scrollLeft;
    const top = toCoords.bottom - anchorRect.top + scrollTop + 6;

    setBubbleToolbar(null);
    setAnnotationPopup({ left: Math.max(0, left - 140), top });
    setTimeout(() => annotationInputRef.current?.focus(), 50);
  }, [editor]);

  const confirmAnnotation = useCallback(() => {
    if (!editor || !pendingAnnotationIdRef.current) return;
    const id = pendingAnnotationIdRef.current;
    const note = annotationInputRef.current?.value ?? "";

    editor.chain().focus().setAnnotation(id).run();

    setAnnotations((prev) => [
      ...prev,
      { id, text: note, selectedText: pendingSelectedTextRef.current },
    ]);

    pendingAnnotationIdRef.current = null;
    pendingSelectedTextRef.current = "";
    setAnnotationPopup(null);
    if (annotationInputRef.current) annotationInputRef.current.value = "";
  }, [editor]);

  const removeAnnotation = useCallback(
    (id: string) => {
      setAnnotations((prev) => prev.filter((a) => a.id !== id));
      if (editor) {
        const { state, view } = editor;
        const { doc } = state;
        let tr = state.tr;
        let modified = false;
        doc.descendants((node, pos) => {
          if (node.marks) {
            const mark = node.marks.find(
              (m) => m.type.name === "annotation" && m.attrs.annotationId === id,
            );
            if (mark) {
              tr = tr.removeMark(pos, pos + node.nodeSize, mark);
              modified = true;
            }
          }
        });
        if (modified) view.dispatch(tr);
      }
    },
    [editor],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (!editor) return;

      if (annotationPopup) {
        if (event.key === "Escape") {
          setAnnotationPopup(null);
          pendingAnnotationIdRef.current = null;
          return;
        }
        return;
      }

      if (slashMenu) {
        if (event.key === "ArrowDown" && filteredSlashCommands.length > 0) {
          event.preventDefault();
          setSlashNavigation((prev) => ({
            key: slashMenuKey,
            index:
              prev.key === slashMenuKey
                ? (prev.index + 1) % filteredSlashCommands.length
                : 0,
          }));
          return;
        }

        if (event.key === "ArrowUp" && filteredSlashCommands.length > 0) {
          event.preventDefault();
          setSlashNavigation((prev) => ({
            key: slashMenuKey,
            index:
              prev.key === slashMenuKey
                ? (prev.index - 1 + filteredSlashCommands.length) %
                  filteredSlashCommands.length
                : filteredSlashCommands.length - 1,
          }));
          return;
        }

        if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
          event.preventDefault();
          if (filteredSlashCommands.length > 0) {
            executeSlashCommand(
              filteredSlashCommands[selectedSlashIndex] ?? filteredSlashCommands[0],
            );
          }
          return;
        }

        if (event.key === "Escape" || event.key === "Tab") {
          event.preventDefault();
          setSlashMenu(null);
          return;
        }
      }
    },
    [
      editor,
      executeSlashCommand,
      filteredSlashCommands,
      selectedSlashIndex,
      slashMenu,
      slashMenuKey,
      annotationPopup,
    ],
  );

  const dropdownStyle = useMemo(() => {
    if (!slashMenu) return null;
    const estimatedHeight = Math.min(filteredSlashCommands.length || 1, 6) * 52 + 12;
    const estimatedWidth = Math.min(512, window.innerWidth - 32);
    const fitsBelow = slashMenu.viewportBottom + estimatedHeight < window.innerHeight - 16;
    return {
      left: Math.min(
        Math.max(12, slashMenu.viewportLeft),
        Math.max(12, window.innerWidth - estimatedWidth - 12),
      ),
      top: fitsBelow
        ? slashMenu.viewportBottom + 10
        : Math.max(12, slashMenu.viewportTop - estimatedHeight - 10),
    };
  }, [filteredSlashCommands.length, slashMenu]);

  const characterCount = editor?.state.doc.textContent.length ?? normalizeMarkdown(value).length;

  return (
    <div className="flex h-full min-h-0 bg-background p-2">
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[1.35rem] border border-violet-400/80 bg-background shadow-[0_0_0_4px_rgba(139,92,246,0.13),0_18px_42px_rgba(15,23,42,0.08)] transition-colors focus-within:border-violet-500">
      <div className="flex min-h-14 shrink-0 flex-wrap items-center gap-1 border-b border-border/55 bg-background px-5 py-2.5">
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
          label="一级标题"
          active={editor?.isActive("heading", { level: 1 })}
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().toggleHeading({ level: 1 }).run();
          }}
        >
          <Heading1 className="size-3.5" />
        </ToolbarButton>
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
          label="三级标题"
          active={editor?.isActive("heading", { level: 3 })}
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().toggleHeading({ level: 3 }).run();
          }}
        >
          <Heading3 className="size-3.5" />
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
        <ToolbarButton
          label="表格"
          active={editor?.isActive("table")}
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
          }}
        >
          <TableIcon className="size-3.5" />
        </ToolbarButton>
        <ToolbarButton
          label="分割线"
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().setHorizontalRule().run();
          }}
        >
          <Minus className="size-3.5" />
        </ToolbarButton>
        <div className="mx-2 h-6 w-px bg-border/70" />
        <ToolbarButton
          label="批注"
          onMouseDown={(event) => {
            event.preventDefault();
            openAnnotationPopup();
          }}
        >
          <MessageSquarePlus className="size-3.5" />
        </ToolbarButton>
      </div>

      <div className="relative min-h-0 flex-1">
      <div ref={anchorRef} className="relative h-full min-h-0 overflow-auto pb-12">
        <EditorContent editor={editor} onKeyDown={handleKeyDown} />

        <AnimatePresence>
          {bubbleToolbar && !slashMenu && !annotationPopup && editor && (
            <motion.div
              initial={{ opacity: 0, y: 4, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 4, scale: 0.95 }}
              transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] }}
              className="absolute z-50 flex items-center gap-0.5 rounded-lg border border-border/60 bg-popover/98 px-1 py-0.5 shadow-lg backdrop-blur"
              style={{
                left: Math.max(0, Math.min(bubbleToolbar.left - 120, (anchorRef.current?.clientWidth ?? 400) - 280)),
                top: bubbleToolbar.top - 40,
                transformOrigin: "center bottom",
              }}
              onMouseDown={(e) => e.preventDefault()}
            >
              <BubbleToolbarButton
                label="加粗"
                active={editor.isActive("bold")}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleBold().run();
                }}
              >
                <Bold className="size-3.5" />
              </BubbleToolbarButton>
              <BubbleToolbarButton
                label="斜体"
                active={editor.isActive("italic")}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleItalic().run();
                }}
              >
                <Italic className="size-3.5" />
              </BubbleToolbarButton>
              <BubbleToolbarButton
                label="删除线"
                active={editor.isActive("strike")}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleStrike().run();
                }}
              >
                <Strikethrough className="size-3.5" />
              </BubbleToolbarButton>
              <BubbleToolbarButton
                label="行内代码"
                active={editor.isActive("code")}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleCode().run();
                }}
              >
                <Code className="size-3.5" />
              </BubbleToolbarButton>
              <div className="mx-0.5 h-4 w-px bg-border/60" />
              <BubbleToolbarButton
                label="一级标题"
                active={editor.isActive("heading", { level: 1 })}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleHeading({ level: 1 }).run();
                }}
              >
                <Heading1 className="size-3.5" />
              </BubbleToolbarButton>
              <BubbleToolbarButton
                label="二级标题"
                active={editor.isActive("heading", { level: 2 })}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleHeading({ level: 2 }).run();
                }}
              >
                <Heading2 className="size-3.5" />
              </BubbleToolbarButton>
              <BubbleToolbarButton
                label="三级标题"
                active={editor.isActive("heading", { level: 3 })}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleHeading({ level: 3 }).run();
                }}
              >
                <Heading3 className="size-3.5" />
              </BubbleToolbarButton>
              <div className="mx-0.5 h-4 w-px bg-border/60" />
              <BubbleToolbarButton
                label="无序列表"
                active={editor.isActive("bulletList")}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleBulletList().run();
                }}
              >
                <List className="size-3.5" />
              </BubbleToolbarButton>
              <BubbleToolbarButton
                label="有序列表"
                active={editor.isActive("orderedList")}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleOrderedList().run();
                }}
              >
                <ListOrdered className="size-3.5" />
              </BubbleToolbarButton>
              <BubbleToolbarButton
                label="引用块"
                active={editor.isActive("blockquote")}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleBlockquote().run();
                }}
              >
                <Quote className="size-3.5" />
              </BubbleToolbarButton>
              <div className="mx-0.5 h-4 w-px bg-border/60" />
              <BubbleToolbarButton
                label="添加批注"
                onMouseDown={(e) => {
                  e.preventDefault();
                  openAnnotationPopup();
                }}
              >
                <MessageSquarePlus className="size-3.5" />
              </BubbleToolbarButton>
            </motion.div>
          )}
        </AnimatePresence>

        <AnimatePresence>
          {annotationPopup && (
            <motion.div
              initial={{ opacity: 0, y: -4, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -4, scale: 0.95 }}
              transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] }}
              className="absolute z-50 flex items-center gap-2 rounded-lg border border-amber-300/50 bg-amber-50/98 px-3 py-2 shadow-lg backdrop-blur dark:border-amber-600/40 dark:bg-amber-950/90"
              style={{
                left: Math.max(0, annotationPopup.left),
                top: annotationPopup.top,
                minWidth: 280,
              }}
              onMouseDown={(e) => e.preventDefault()}
            >
              <MessageSquarePlus className="size-4 shrink-0 text-amber-600 dark:text-amber-400" />
              <input
                ref={annotationInputRef}
                type="text"
                placeholder="输入批注内容…"
                className="min-w-0 flex-1 bg-transparent text-sm text-amber-900 outline-none placeholder:text-amber-400/60 dark:text-amber-100 dark:placeholder:text-amber-500/50"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    confirmAnnotation();
                  }
                  if (e.key === "Escape") {
                    setAnnotationPopup(null);
                    pendingAnnotationIdRef.current = null;
                  }
                }}
              />
              <button
                type="button"
                onClick={confirmAnnotation}
                className="shrink-0 rounded-md bg-amber-500/20 px-2.5 py-0.5 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-500/30 dark:text-amber-300 dark:hover:bg-amber-500/20"
              >
                确认
              </button>
              <button
                type="button"
                onClick={() => {
                  setAnnotationPopup(null);
                  pendingAnnotationIdRef.current = null;
                }}
                className="shrink-0 rounded p-0.5 text-amber-400/60 transition-colors hover:text-amber-600"
              >
                <X className="size-3.5" />
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {slashMenu && dropdownStyle ? createPortal(
          <div
            className="fixed z-[100] w-fit min-w-[17rem] max-w-[min(32rem,calc(100vw-4rem))] rounded-xl border border-border/60 bg-popover/98 p-1.5 shadow-xl backdrop-blur"
            style={dropdownStyle}
          >
            {filteredSlashCommands.length > 0 ? (
              filteredSlashCommands.map((command, index) => (
                <button
                  key={command.id}
                  type="button"
                  onMouseEnter={() =>
                    setSlashNavigation({
                      key: slashMenuKey,
                      index,
                    })
                  }
                  onMouseDown={(event) => {
                    event.preventDefault();
                    executeSlashCommand(command);
                  }}
                  className={cn(
                    "flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left transition-colors",
                    index === selectedSlashIndex && "bg-accent text-accent-foreground",
                  )}
                >
                  <span className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-foreground">
                    {command.id === "heading-1" ? (
                      <Heading1 className="size-4" />
                    ) : command.id === "heading-2" ? (
                      <Heading2 className="size-4" />
                    ) : command.id === "heading-3" ? (
                      <Heading3 className="size-4" />
                    ) : command.id === "bullet-list" ? (
                      <List className="size-4" />
                    ) : command.id === "ordered-list" ? (
                      <ListOrdered className="size-4" />
                    ) : command.id === "blockquote" ? (
                      <Quote className="size-4" />
                    ) : command.id === "code-block" ? (
                      <Code className="size-4" />
                    ) : command.id === "table" ? (
                      <TableIcon className="size-4" />
                    ) : (
                      <Minus className="size-4" />
                    )}
                  </span>
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-sm font-medium">{command.label}</span>
                    <span className="text-xs text-muted-foreground/75">
                      {command.description}
                    </span>
                  </span>
                </button>
              ))
            ) : (
              <div className="rounded-lg px-3 py-2 text-xs text-muted-foreground">
                没有匹配的结构命令
              </div>
            )}
          </div>,
          document.body,
        ) : null}
      </div>

      <div className="pointer-events-none absolute bottom-4 right-6 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
        <span className="h-2 w-2 rounded-full bg-emerald-500" />
        <span>{characterCount}</span>
        <span>chars</span>
      </div>
      </div>

      <AnimatePresence>
        {annotations.length > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
            className="overflow-hidden border-t border-border/60"
          >
            <div className="bg-amber-50/50 px-4 py-2.5 dark:bg-amber-950/20">
              <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-amber-700 dark:text-amber-400">
                <MessageSquarePlus className="size-3.5" />
                批注 ({annotations.length})
              </div>
              <div className="flex flex-col gap-1.5">
                {annotations.map((ann, index) => (
                  <div
                    key={ann.id}
                    className="group flex items-start gap-2 rounded-md border border-amber-200/50 bg-white/60 px-2.5 py-1.5 text-xs dark:border-amber-800/30 dark:bg-amber-950/20"
                  >
                    <span className="mt-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded-full bg-amber-400/20 text-[10px] font-bold text-amber-600 dark:bg-amber-400/15 dark:text-amber-400">
                      {index + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <span className="text-amber-800/70 dark:text-amber-300/60">
                        &ldquo;{ann.selectedText}&rdquo;
                      </span>
                      {ann.text && (
                        <span className="ml-1 text-foreground/80">&mdash; {ann.text}</span>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => removeAnnotation(ann.id)}
                      className="shrink-0 rounded p-0.5 text-muted-foreground/40 transition-colors hover:text-destructive"
                      aria-label="删除批注"
                    >
                      <X className="size-3" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <style>{`
        .annotation-highlight {
          background-color: rgba(251, 191, 36, 0.25);
          border-bottom: 2px solid rgba(251, 191, 36, 0.5);
          border-radius: 2px;
          cursor: default;
        }
        .dark .annotation-highlight {
          background-color: rgba(251, 191, 36, 0.15);
          border-bottom-color: rgba(251, 191, 36, 0.35);
        }
        .ProseMirror table {
          border-collapse: collapse;
          table-layout: fixed;
          width: 100%;
          margin: 0;
          overflow: hidden;
        }
        .ProseMirror td,
        .ProseMirror th {
          border: 1px solid var(--border, #e2e8f0);
          min-width: 80px;
          padding: 6px 10px;
          position: relative;
          vertical-align: top;
          box-sizing: border-box;
        }
        .ProseMirror th {
          background-color: var(--muted, #f1f5f9);
          font-weight: 600;
        }
        .ProseMirror td > *,
        .ProseMirror th > * {
          margin: 0;
        }
        .dark .ProseMirror th {
          background-color: var(--muted, #1e293b);
        }
        .dark .ProseMirror td,
        .dark .ProseMirror th {
          border-color: var(--border, #334155);
        }
        .ProseMirror .selectedCell::after {
          content: "";
          position: absolute;
          inset: 0;
          background: rgba(59, 130, 246, 0.12);
          pointer-events: none;
        }
      `}</style>
      </div>
    </div>
  );
}
