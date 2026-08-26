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
import Editor from "@monaco-editor/react";
import {
  Bold,
  Check,
  CheckSquare,
  Code,
  Code2,
  Copy,
  CornerDownLeft,
  FileCode,
  FileText,
  Heading1,
  Heading2,
  Heading3,
  Italic,
  List,
  ListOrdered,
  LocateFixed,
  MessageSquarePlus,
  Minus,
  Quote,
  Redo2,
  Save,
  Sparkles,
  Strikethrough,
  Table as TableIcon,
  Trash2,
  Type,
  Undo2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";

export type Annotation = {
  id: string;
  text: string;
  selectedText: string;
};

type SlashCategory = "排版与层级" | "列表与待办" | "代码与引用" | "表格与结构";

type SlashCommand = {
  id: string;
  category: SlashCategory;
  label: string;
  description: string;
  shortcut?: string;
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

export type PlanRichTextEditorProps = {
  value: string;
  onChange: (markdown: string) => void;
  autoFocus?: boolean;
  onAnnotationsChange?: (annotations: Annotation[]) => void;
  title?: string;
  onSave?: () => void;
  onSubmit?: () => void;
  onClose?: () => void;
  isSaving?: boolean;
  isDarkMode?: boolean;
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
        class: "plan-annotation-highlight",
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
  replacement: (_content: string, node: HTMLElement) => {
    const table = node as HTMLTableElement;
    const rows = Array.from(table.rows);
    if (rows.length === 0) return "";

    const lines: string[] = [];
    const firstRow = rows[0];
    const headers = Array.from(firstRow.cells).map((cell) => cell.textContent?.trim() || " ");
    lines.push(`| ${headers.join(" | ")} |`);
    lines.push(`| ${headers.map(() => "---").join(" | ")} |`);

    for (let i = 1; i < rows.length; i++) {
      const cells = Array.from(rows[i].cells).map((cell) => cell.textContent?.trim() || " ");
      lines.push(`| ${cells.join(" | ")} |`);
    }
    return "\n\n" + lines.join("\n") + "\n\n";
  },
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

function ToolbarIconButton({
  active,
  disabled,
  label,
  shortcut,
  onMouseDown,
  children,
}: {
  active?: boolean;
  disabled?: boolean;
  label: string;
  shortcut?: string;
  onMouseDown: (event: React.MouseEvent<HTMLButtonElement>) => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-label={label}
      title={shortcut ? `${label} (${shortcut})` : label}
      onMouseDown={onMouseDown}
      className={cn(
        "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors",
        active
          ? "bg-primary/15 text-primary font-medium"
          : "hover:bg-muted hover:text-foreground active:scale-95",
        disabled && "opacity-35 cursor-not-allowed hover:bg-transparent hover:text-muted-foreground",
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

export function PlanRichTextEditor({
  value,
  onChange,
  autoFocus = false,
  onAnnotationsChange,
  title = "计划方案",
  onSave,
  onSubmit,
  onClose,
  isSaving = false,
  isDarkMode = false,
}: PlanRichTextEditorProps) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const lastMarkdownRef = useRef(normalizeMarkdown(value));
  const isApplyingExternalValueRef = useRef(false);

  const [editorMode, setEditorMode] = useState<"visual" | "markdown">("visual");
  const [copied, setCopied] = useState(false);
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
  const [isAnnotationsOpen, setIsAnnotationsOpen] = useState(true);
  const [activeAnnotationId, setActiveAnnotationId] = useState<string | null>(null);

  const annotationInputRef = useRef<HTMLInputElement>(null);
  const pendingAnnotationIdRef = useRef<string | null>(null);
  const pendingSelectedTextRef = useRef<string>("");

  const syncAnnotations = useCallback((html: string) => {
    const idsInDom = extractAnnotationIdsFromHtml(html);
    setAnnotations((prev) => prev.filter((a) => idsInDom.includes(a.id)));
  }, []);

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
            "plan-prose min-h-[460px] max-w-3xl mx-auto px-6 py-6 text-[14.5px] leading-relaxed text-foreground outline-none [word-break:break-word] selection:bg-primary/20",
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
        setSlashMenu(
          getSlashMenuState(
            currentEditor,
            anchorRef.current?.getBoundingClientRect() ?? null,
            { x: anchorRef.current?.scrollLeft ?? 0, y: anchorRef.current?.scrollTop ?? 0 },
          ),
        );
        updateBubbleToolbar(currentEditor);
        syncAnnotations(currentEditor.getHTML());
      },
      onSelectionUpdate({ editor: currentEditor }) {
        setSlashMenu(
          getSlashMenuState(
            currentEditor,
            anchorRef.current?.getBoundingClientRect() ?? null,
            { x: anchorRef.current?.scrollLeft ?? 0, y: anchorRef.current?.scrollTop ?? 0 },
          ),
        );
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
        category: "排版与层级",
        label: "一级标题 (H1)",
        description: "主标题，适合总体方案与模块总览",
        shortcut: "#",
        keywords: ["h1", "title", "heading 1", "yiji"],
        run: () => editor.chain().focus().toggleHeading({ level: 1 }).run(),
      },
      {
        id: "heading-2",
        category: "排版与层级",
        label: "二级标题 (H2)",
        description: "分段章节，适合步骤拆解与模块",
        shortcut: "##",
        keywords: ["h2", "heading 2", "section", "erji"],
        run: () => editor.chain().focus().toggleHeading({ level: 2 }).run(),
      },
      {
        id: "heading-3",
        category: "排版与层级",
        label: "三级标题 (H3)",
        description: "细分小节与具体实现细则",
        shortcut: "###",
        keywords: ["h3", "heading 3", "subsection", "sanji"],
        run: () => editor.chain().focus().toggleHeading({ level: 3 }).run(),
      },
      {
        id: "paragraph",
        category: "排版与层级",
        label: "正文段落",
        description: "标准正文排版说明",
        keywords: ["p", "text", "paragraph", "zhengwen"],
        run: () => editor.chain().focus().setParagraph().run(),
      },
      {
        id: "divider",
        category: "排版与层级",
        label: "分割线",
        description: "插入水平分割线分隔上下文",
        shortcut: "---",
        keywords: ["divider", "rule", "separator", "fengexian"],
        run: () => editor.chain().focus().setHorizontalRule().run(),
      },
      {
        id: "task-list",
        category: "列表与待办",
        label: "待办清单",
        description: "插入任务检查点与执行待办项",
        shortcut: "[]",
        keywords: ["task", "todo", "daiban", "checklist"],
        run: () => {
          editor.chain().focus().insertContent("- [ ] 待办任务项").run();
        },
      },
      {
        id: "bullet-list",
        category: "列表与待办",
        label: "无序列表",
        description: "要点清单与项目归纳",
        shortcut: "-",
        keywords: ["list", "bullet", "ul", "wuxu"],
        run: () => editor.chain().focus().toggleBulletList().run(),
      },
      {
        id: "ordered-list",
        category: "列表与待办",
        label: "有序列表",
        description: "按先后顺序执行的步骤编号",
        shortcut: "1.",
        keywords: ["ordered", "numbered", "ol", "youxu"],
        run: () => editor.chain().focus().toggleOrderedList().run(),
      },
      {
        id: "blockquote",
        category: "代码与引用",
        label: "引用提示",
        description: "重要说明、前置条件或风险提示",
        shortcut: ">",
        keywords: ["quote", "blockquote", "remark", "yinyong"],
        run: () => editor.chain().focus().toggleBlockquote().run(),
      },
      {
        id: "code-block",
        category: "代码与引用",
        label: "代码块",
        description: "插入命令、代码片段或配置文件",
        shortcut: "```",
        keywords: ["code", "snippet", "fence", "daima"],
        run: () => editor.chain().focus().toggleCodeBlock().run(),
      },
      {
        id: "table",
        category: "表格与结构",
        label: "结构表格",
        description: "插入 3x3 结构化数据对比表格",
        keywords: ["table", "grid", "biaoge"],
        run: () =>
          editor
            .chain()
            .focus()
            .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
            .run(),
      },
    ];
  }, [editor]);

  const filteredSlashCommands = useMemo(() => {
    if (!slashMenu) return [];
    const query = slashMenu.query.trim().toLowerCase();
    if (!query) return slashCommands;

    return slashCommands.filter((command) =>
      [command.label, command.description, command.shortcut ?? "", ...command.keywords].some((item) =>
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
    const top = toCoords.bottom - anchorRect.top + scrollTop + 8;

    setBubbleToolbar(null);
    setAnnotationPopup({ left: Math.max(12, left - 150), top });
    setTimeout(() => annotationInputRef.current?.focus(), 60);
  }, [editor]);

  const confirmAnnotation = useCallback(() => {
    if (!editor || !pendingAnnotationIdRef.current) return;
    const id = pendingAnnotationIdRef.current;
    const note = annotationInputRef.current?.value.trim() ?? "";

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

  const scrollToAnnotation = useCallback((id: string) => {
    setActiveAnnotationId(id);
    const el = document.querySelector(`span[data-annotation-id="${id}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("plan-annotation-flash");
      setTimeout(() => el.classList.remove("plan-annotation-flash"), 1500);
    }
  }, []);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        onSubmit?.();
        return;
      }

      if ((event.ctrlKey || event.metaKey) && event.key === "s") {
        event.preventDefault();
        onSave?.();
        return;
      }

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
      annotationPopup,
      editor,
      executeSlashCommand,
      filteredSlashCommands,
      onSave,
      onSubmit,
      selectedSlashIndex,
      slashMenu,
      slashMenuKey,
    ],
  );

  const dropdownStyle = useMemo(() => {
    if (!slashMenu) return null;
    const estimatedHeight = Math.min(filteredSlashCommands.length || 1, 7) * 44 + 48;
    const estimatedWidth = Math.min(320, window.innerWidth - 32);
    const fitsBelow = slashMenu.viewportBottom + estimatedHeight < window.innerHeight - 16;
    return {
      left: Math.min(
        Math.max(12, slashMenu.viewportLeft),
        Math.max(12, window.innerWidth - estimatedWidth - 16),
      ),
      top: fitsBelow
        ? slashMenu.viewportBottom + 8
        : Math.max(12, slashMenu.viewportTop - estimatedHeight - 8),
    };
  }, [filteredSlashCommands.length, slashMenu]);

  const handleCopyMarkdown = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  }, [value]);

  const characterCount = editor?.state.doc.textContent.length ?? normalizeMarkdown(value).length;
  const wordCount = useMemo(() => {
    const text = value.trim();
    if (!text) return 0;
    return text.split(/\s+/).length;
  }, [value]);
  const estimatedReadMinutes = Math.max(1, Math.ceil(characterCount / 350));

  return (
    <div
      ref={editorContainerRef}
      onKeyDown={handleKeyDown}
      className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-background text-foreground"
    >
      {/* 顶部现代化精简控制栏 */}
      <header className="flex h-11 shrink-0 items-center justify-between border-b border-border/60 bg-muted/20 px-3 gap-2">
        {/* 左侧：文档图标与计划标题 */}
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <FileText className="size-3.5" />
          </div>
          <span className="truncate text-xs font-semibold tracking-tight text-foreground max-w-[120px] sm:max-w-[200px]" title={title}>
            {title || "计划方案草案"}
          </span>
          <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.2 text-[10px] font-medium text-primary">
            计划
          </span>
          <span
            className={cn(
              "size-2 shrink-0 rounded-full",
              isSaving ? "bg-amber-500 animate-spin" : "bg-emerald-500",
            )}
            title={isSaving ? "正在同步草案..." : "已自动同步"}
          />
        </div>

        {/* 右侧：紧凑型操作按钮区（全部 shrink-0 whitespace-nowrap 绝不换行） */}
        <div className="flex shrink-0 items-center gap-1">
          {/* 模式切换胶囊 */}
          <div className="flex shrink-0 items-center rounded-md border border-border/60 bg-background/90 p-0.5 shadow-2xs">
            <button
              type="button"
              onClick={() => setEditorMode("visual")}
              title="所见即所得富文本编辑"
              className={cn(
                "flex shrink-0 items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition-all",
                editorMode === "visual"
                  ? "bg-muted text-foreground font-semibold shadow-2xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Type className="size-3" />
              <span>富文本</span>
            </button>
            <button
              type="button"
              onClick={() => setEditorMode("markdown")}
              title="Markdown 源码编辑"
              className={cn(
                "flex shrink-0 items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition-all",
                editorMode === "markdown"
                  ? "bg-muted text-foreground font-semibold shadow-2xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <FileCode className="size-3" />
              <span>源码</span>
            </button>
          </div>

          <Button
            size="icon"
            variant="ghost"
            className="size-7 shrink-0 text-muted-foreground hover:text-foreground"
            onClick={handleCopyMarkdown}
            title={copied ? "已复制到剪贴板" : "复制 Markdown"}
          >
            {copied ? <Check className="size-3.5 text-emerald-500" /> : <Copy className="size-3.5" />}
          </Button>

          {annotations.length > 0 && (
            <Button
              size="sm"
              variant={isAnnotationsOpen ? "secondary" : "outline"}
              className="h-7 shrink-0 gap-1 px-2 text-[11px] font-medium text-amber-600 dark:text-amber-400"
              onClick={() => setIsAnnotationsOpen((prev) => !prev)}
              title="查看批注列表"
            >
              <MessageSquarePlus className="size-3" />
              <span>{annotations.length}</span>
            </Button>
          )}

          {onSave && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 shrink-0 gap-1 px-2 text-xs"
              onClick={onSave}
              disabled={isSaving}
              title="保存草稿 (Ctrl+S)"
            >
              <Save className="size-3" />
              <span className="hidden sm:inline">{isSaving ? "保存中" : "保存"}</span>
            </Button>
          )}

          {onSubmit && (
            <Button
              size="sm"
              variant="default"
              className="h-7 shrink-0 gap-1.5 bg-primary px-2.5 text-xs font-medium text-primary-foreground shadow-xs hover:bg-primary/90 active:scale-98"
              onClick={onSubmit}
              title="交付 AI 编写代码 (Ctrl+Enter)"
            >
              <Sparkles className="size-3.5" />
              <span>交付 AI</span>
              <kbd className="hidden rounded bg-primary-foreground/20 px-1 text-[9px] text-primary-foreground sm:inline-block font-mono">
                ⌘↵
              </kbd>
            </Button>
          )}

          {onClose && (
            <Button
              size="icon"
              variant="ghost"
              className="size-7 shrink-0 text-muted-foreground hover:text-foreground"
              onClick={onClose}
              title="返回代码编辑器"
            >
              <X className="size-3.5" />
            </Button>
          )}
        </div>
      </header>

      {/* 富文本工具栏：单行无缝横向滚动，永不折行成两行 */}
      {editorMode === "visual" && (
        <div className="flex h-8.5 shrink-0 items-center gap-0.5 border-b border-border/50 bg-background/95 px-2.5 overflow-x-auto no-scrollbar whitespace-nowrap">
          {/* 撤销重做 */}
          <ToolbarIconButton
            label="撤销"
            shortcut="Ctrl+Z"
            disabled={!editor?.can().undo()}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().undo().run();
            }}
          >
            <Undo2 className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="重做"
            shortcut="Ctrl+Y"
            disabled={!editor?.can().redo()}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().redo().run();
            }}
          >
            <Redo2 className="size-3.5" />
          </ToolbarIconButton>

          <div className="mx-1 h-3.5 w-px shrink-0 bg-border/60" />

          {/* 标题层级 */}
          <ToolbarIconButton
            label="一级标题"
            shortcut="#"
            active={editor?.isActive("heading", { level: 1 })}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().toggleHeading({ level: 1 }).run();
            }}
          >
            <Heading1 className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="二级标题"
            shortcut="##"
            active={editor?.isActive("heading", { level: 2 })}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().toggleHeading({ level: 2 }).run();
            }}
          >
            <Heading2 className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="三级标题"
            shortcut="###"
            active={editor?.isActive("heading", { level: 3 })}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().toggleHeading({ level: 3 }).run();
            }}
          >
            <Heading3 className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="正文文本"
            active={editor?.isActive("paragraph")}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().setParagraph().run();
            }}
          >
            <Type className="size-3.5" />
          </ToolbarIconButton>

          <div className="mx-1 h-3.5 w-px shrink-0 bg-border/60" />

          {/* 字体格式化 */}
          <ToolbarIconButton
            label="加粗"
            shortcut="Ctrl+B"
            active={editor?.isActive("bold")}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().toggleBold().run();
            }}
          >
            <Bold className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="斜体"
            shortcut="Ctrl+I"
            active={editor?.isActive("italic")}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().toggleItalic().run();
            }}
          >
            <Italic className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="删除线"
            active={editor?.isActive("strike")}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().toggleStrike().run();
            }}
          >
            <Strikethrough className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="行内代码"
            active={editor?.isActive("code")}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().toggleCode().run();
            }}
          >
            <Code className="size-3.5" />
          </ToolbarIconButton>

          <div className="mx-1 h-3.5 w-px shrink-0 bg-border/60" />

          {/* 列表与待办 */}
          <ToolbarIconButton
            label="待办清单"
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().insertContent("- [ ] 待办任务项").run();
            }}
          >
            <CheckSquare className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="无序列表"
            active={editor?.isActive("bulletList")}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().toggleBulletList().run();
            }}
          >
            <List className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="有序列表"
            active={editor?.isActive("orderedList")}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().toggleOrderedList().run();
            }}
          >
            <ListOrdered className="size-3.5" />
          </ToolbarIconButton>

          <div className="mx-1 h-3.5 w-px shrink-0 bg-border/60" />

          {/* 块级结构 */}
          <ToolbarIconButton
            label="引用说明"
            active={editor?.isActive("blockquote")}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().toggleBlockquote().run();
            }}
          >
            <Quote className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="代码块"
            active={editor?.isActive("codeBlock")}
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().toggleCodeBlock().run();
            }}
          >
            <Code2 className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="插入表格"
            active={editor?.isActive("table")}
            onMouseDown={(e) => {
              e.preventDefault();
              editor
                ?.chain()
                .focus()
                .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
                .run();
            }}
          >
            <TableIcon className="size-3.5" />
          </ToolbarIconButton>
          <ToolbarIconButton
            label="分割线"
            onMouseDown={(e) => {
              e.preventDefault();
              editor?.chain().focus().setHorizontalRule().run();
            }}
          >
            <Minus className="size-3.5" />
          </ToolbarIconButton>

          <div className="mx-1 h-3.5 w-px shrink-0 bg-border/60" />

          {/* 批注工具 */}
          <ToolbarIconButton
            label="添加批注"
            onMouseDown={(e) => {
              e.preventDefault();
              openAnnotationPopup();
            }}
          >
            <MessageSquarePlus className="size-3.5 text-amber-500" />
          </ToolbarIconButton>
        </div>
      )}

      {/* 主编辑画布区 */}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        {editorMode === "visual" ? (
          <div
            ref={anchorRef}
            className="relative h-full min-h-0 overflow-y-auto bg-background/50 px-3 py-3"
          >
            <div className="mx-auto max-w-3xl rounded-xl border border-border/40 bg-background/90 p-1 shadow-2xs transition-colors">
              <EditorContent editor={editor} />
            </div>

            {/* 选中文本时的轻量悬浮气泡条 (Bubble Menu) */}
            <AnimatePresence>
              {bubbleToolbar && !slashMenu && !annotationPopup && editor && (
                <motion.div
                  initial={{ opacity: 0, y: 6, scale: 0.96 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 4, scale: 0.96 }}
                  transition={{ duration: 0.12, ease: [0.22, 1, 0.36, 1] }}
                  className="absolute z-50 flex items-center gap-0.5 rounded-lg border border-border/80 bg-popover/95 px-1 py-0.5 shadow-lg backdrop-blur-md"
                  style={{
                    left: Math.max(
                      8,
                      Math.min(bubbleToolbar.left - 120, (anchorRef.current?.clientWidth ?? 400) - 260),
                    ),
                    top: Math.max(8, bubbleToolbar.top - 36),
                  }}
                  onMouseDown={(e) => e.preventDefault()}
                >
                  <ToolbarIconButton
                    label="加粗"
                    active={editor.isActive("bold")}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      editor.chain().focus().toggleBold().run();
                    }}
                  >
                    <Bold className="size-3.5" />
                  </ToolbarIconButton>
                  <ToolbarIconButton
                    label="斜体"
                    active={editor.isActive("italic")}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      editor.chain().focus().toggleItalic().run();
                    }}
                  >
                    <Italic className="size-3.5" />
                  </ToolbarIconButton>
                  <ToolbarIconButton
                    label="行内代码"
                    active={editor.isActive("code")}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      editor.chain().focus().toggleCode().run();
                    }}
                  >
                    <Code className="size-3.5" />
                  </ToolbarIconButton>
                  <ToolbarIconButton
                    label="标题"
                    active={editor.isActive("heading", { level: 2 })}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      editor.chain().focus().toggleHeading({ level: 2 }).run();
                    }}
                  >
                    <Heading2 className="size-3.5" />
                  </ToolbarIconButton>

                  <div className="mx-0.5 h-3.5 w-px bg-border/60" />

                  <button
                    type="button"
                    onClick={openAnnotationPopup}
                    className="inline-flex h-6.5 items-center gap-1 rounded px-1.5 text-xs font-medium text-amber-600 transition-colors hover:bg-amber-500/15 dark:text-amber-400"
                  >
                    <MessageSquarePlus className="size-3" />
                    <span>批注</span>
                  </button>
                </motion.div>
              )}
            </AnimatePresence>

            {/* 批注输入悬浮弹窗 */}
            <AnimatePresence>
              {annotationPopup && (
                <motion.div
                  initial={{ opacity: 0, y: -4, scale: 0.96 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -4, scale: 0.96 }}
                  transition={{ duration: 0.12, ease: [0.22, 1, 0.36, 1] }}
                  className="absolute z-50 flex w-76 items-center gap-1.5 rounded-xl border border-amber-500/40 bg-popover/98 p-1.5 shadow-xl backdrop-blur-md"
                  style={{
                    left: Math.max(8, annotationPopup.left),
                    top: annotationPopup.top,
                  }}
                  onMouseDown={(e) => e.stopPropagation()}
                >
                  <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-amber-500/15 text-amber-600 dark:text-amber-400">
                    <MessageSquarePlus className="size-3" />
                  </div>
                  <input
                    ref={annotationInputRef}
                    type="text"
                    placeholder="输入修改批注 (Enter 确认)..."
                    className="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground/70"
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
                  <Button
                    size="sm"
                    className="h-6 bg-amber-500 px-2 text-[11px] font-medium text-white hover:bg-amber-600"
                    onClick={confirmAnnotation}
                  >
                    确定
                  </Button>
                  <button
                    type="button"
                    onClick={() => {
                      setAnnotationPopup(null);
                      pendingAnnotationIdRef.current = null;
                    }}
                    className="shrink-0 rounded p-1 text-muted-foreground/60 transition-colors hover:text-foreground"
                  >
                    <X className="size-3" />
                  </button>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Slash (/) 命令弹出面板 */}
            {slashMenu && dropdownStyle
              ? createPortal(
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95, y: -4 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ duration: 0.1, ease: "easeOut" }}
                    className="fixed z-[100] max-h-[340px] w-76 overflow-y-auto rounded-xl border border-border/80 bg-popover/98 p-1 shadow-2xl backdrop-blur-md"
                    style={dropdownStyle}
                  >
                    <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-muted-foreground/80">
                      快速插入模块
                    </div>
                    {filteredSlashCommands.length > 0 ? (
                      filteredSlashCommands.map((command, index) => {
                        const isSelected = index === selectedSlashIndex;
                        return (
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
                              "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors",
                              isSelected ? "bg-accent text-accent-foreground font-medium" : "hover:bg-muted/60",
                            )}
                          >
                            <span
                              className={cn(
                                "flex size-6 shrink-0 items-center justify-center rounded-md border text-xs",
                                isSelected
                                  ? "border-primary/40 bg-primary/10 text-primary"
                                  : "border-border/60 bg-muted/50 text-muted-foreground",
                              )}
                            >
                              {command.id === "heading-1" ? (
                                <Heading1 className="size-3" />
                              ) : command.id === "heading-2" ? (
                                <Heading2 className="size-3" />
                              ) : command.id === "heading-3" ? (
                                <Heading3 className="size-3" />
                              ) : command.id === "task-list" ? (
                                <CheckSquare className="size-3" />
                              ) : command.id === "bullet-list" ? (
                                <List className="size-3" />
                              ) : command.id === "ordered-list" ? (
                                <ListOrdered className="size-3" />
                              ) : command.id === "blockquote" ? (
                                <Quote className="size-3" />
                              ) : command.id === "code-block" ? (
                                <Code2 className="size-3" />
                              ) : command.id === "table" ? (
                                <TableIcon className="size-3" />
                              ) : (
                                <Minus className="size-3" />
                              )}
                            </span>
                            <div className="flex min-w-0 flex-1 flex-col">
                              <span className="truncate text-xs">{command.label}</span>
                              <span className="truncate text-[10px] text-muted-foreground/80">
                                {command.description}
                              </span>
                            </div>
                            {command.shortcut && (
                              <kbd className="shrink-0 rounded bg-muted px-1 py-0.2 text-[9px] font-mono text-muted-foreground">
                                {command.shortcut}
                              </kbd>
                            )}
                          </button>
                        );
                      })
                    ) : (
                      <div className="px-3 py-3 text-center text-xs text-muted-foreground">
                        未找到匹配的命令
                      </div>
                    )}
                  </motion.div>,
                  document.body,
                )
              : null}
          </div>
        ) : (
          /* Markdown 源码模式 */
          <div className="h-full w-full">
            <Editor
              height="100%"
              language="markdown"
              value={value}
              onChange={(val) => onChange(val ?? "")}
              theme={isDarkMode ? "vs-dark" : "vs"}
              options={{
                fontSize: 13,
                fontFamily: "var(--font-mono, JetBrains Mono, monospace)",
                lineNumbers: "on",
                wordWrap: "on",
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                automaticLayout: true,
                padding: { top: 12, bottom: 12 },
                renderLineHighlight: "line",
              }}
            />
          </div>
        )}
      </div>

      {/* 底部批注管理抽屉面板 */}
      <AnimatePresence>
        {isAnnotationsOpen && annotations.length > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            className="shrink-0 border-t border-border/60 bg-muted/25"
          >
            <div className="flex max-h-44 flex-col overflow-hidden px-3 py-2">
              <div className="mb-1.5 flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-700 dark:text-amber-400">
                  <MessageSquarePlus className="size-3.5" />
                  <span>批注与修改意见 ({annotations.length})</span>
                </div>
                <button
                  type="button"
                  onClick={() => setIsAnnotationsOpen(false)}
                  className="rounded p-0.5 text-xs text-muted-foreground hover:text-foreground"
                >
                  <X className="size-3" />
                </button>
              </div>

              <div className="flex flex-1 flex-col gap-1 overflow-y-auto pr-1">
                {annotations.map((ann, index) => {
                  const isActive = activeAnnotationId === ann.id;
                  return (
                    <div
                      key={ann.id}
                      className={cn(
                        "group flex items-start gap-2 rounded-md border p-1.5 text-xs transition-all",
                        isActive
                          ? "border-amber-500/60 bg-amber-500/10 shadow-2xs"
                          : "border-border/60 bg-background hover:border-amber-500/30",
                      )}
                    >
                      <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-amber-500/20 text-[9px] font-bold text-amber-700 dark:text-amber-300">
                        {index + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate italic text-muted-foreground text-[11px]">
                          &ldquo;{ann.selectedText}&rdquo;
                        </div>
                        {ann.text && (
                          <div className="font-medium text-foreground text-xs">
                            {ann.text}
                          </div>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-0.5 opacity-80 group-hover:opacity-100">
                        <button
                          type="button"
                          onClick={() => scrollToAnnotation(ann.id)}
                          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                          title="在文档中定位"
                        >
                          <LocateFixed className="size-3" />
                        </button>
                        <button
                          type="button"
                          onClick={() => removeAnnotation(ann.id)}
                          className="rounded p-1 text-muted-foreground/60 hover:bg-destructive/10 hover:text-destructive"
                          title="删除批注"
                        >
                          <Trash2 className="size-3" />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 底部精简状态栏 */}
      <footer className="flex h-7 shrink-0 items-center justify-between border-t border-border/50 bg-background px-3 text-[10.5px] text-muted-foreground">
        <div className="flex items-center gap-2">
          <span>{characterCount} 字符</span>
          <span className="text-border">·</span>
          <span>{wordCount} 词</span>
          <span className="text-border">·</span>
          <span>阅读 ~{estimatedReadMinutes}m</span>
        </div>

        <div className="hidden items-center gap-2.5 sm:flex">
          <span className="flex items-center gap-1">
            <kbd className="rounded bg-muted px-1 text-[9px] font-mono">/</kbd>
            <span>快捷命令</span>
          </span>
          <span className="text-border">·</span>
          <span className="flex items-center gap-1 text-primary font-medium">
            <CornerDownLeft className="size-2.5" />
            <span>Ctrl+Enter 交付执行</span>
          </span>
        </div>
      </footer>

      {/* 专属排版样式 (Typography System) */}
      <style>{`
        .no-scrollbar::-webkit-scrollbar {
          display: none;
        }
        .no-scrollbar {
          -ms-overflow-style: none;
          scrollbar-width: none;
        }
        
        .plan-annotation-highlight {
          background-color: rgba(245, 158, 11, 0.18);
          border-bottom: 2px solid rgba(245, 158, 11, 0.65);
          border-radius: 2px;
          padding: 0 2px;
          cursor: pointer;
          transition: background-color 0.15s ease;
        }
        .plan-annotation-highlight:hover {
          background-color: rgba(245, 158, 11, 0.28);
        }
        .plan-annotation-flash {
          animation: plan-flash 1.2s ease-out;
        }
        @keyframes plan-flash {
          0%, 100% { background-color: rgba(245, 158, 11, 0.18); }
          50% { background-color: rgba(245, 158, 11, 0.55); }
        }
        
        .plan-prose h1 {
          font-size: 1.55rem;
          line-height: 1.25;
          font-weight: 700;
          letter-spacing: -0.02em;
          margin-top: 1.4rem;
          margin-bottom: 0.6rem;
          color: var(--foreground);
          border-bottom: 1px solid var(--border);
          padding-bottom: 0.35rem;
        }
        .plan-prose h2 {
          font-size: 1.25rem;
          line-height: 1.3;
          font-weight: 650;
          letter-spacing: -0.015em;
          margin-top: 1.25rem;
          margin-bottom: 0.45rem;
          color: var(--foreground);
        }
        .plan-prose h3 {
          font-size: 1.05rem;
          line-height: 1.35;
          font-weight: 600;
          margin-top: 1rem;
          margin-bottom: 0.35rem;
          color: var(--foreground);
        }
        .plan-prose p {
          margin: 0.5rem 0;
          line-height: 1.65;
        }
        .plan-prose ul {
          list-style-type: disc;
          padding-left: 1.4rem;
          margin: 0.5rem 0;
        }
        .plan-prose ol {
          list-style-type: decimal;
          padding-left: 1.4rem;
          margin: 0.5rem 0;
        }
        .plan-prose li {
          margin: 0.2rem 0;
          line-height: 1.6;
        }
        .plan-prose blockquote {
          border-left: 3px solid var(--primary);
          background: color-mix(in oklch, var(--primary), transparent 94%);
          padding: 0.4rem 0.75rem;
          margin: 0.75rem 0;
          border-radius: 0 0.4rem 0.4rem 0;
          color: var(--muted-foreground);
          font-style: italic;
        }
        .plan-prose pre {
          background: color-mix(in oklch, var(--foreground), transparent 93%);
          border: 1px solid var(--border);
          border-radius: 0.45rem;
          padding: 0.75rem 0.9rem;
          margin: 0.75rem 0;
          overflow-x: auto;
          font-family: var(--font-mono, JetBrains Mono, monospace);
          font-size: 0.85rem;
          line-height: 1.55;
        }
        .plan-prose code {
          background: color-mix(in oklch, var(--foreground), transparent 92%);
          border: 1px solid color-mix(in oklch, var(--border), transparent 40%);
          border-radius: 0.3rem;
          padding: 0.1rem 0.3rem;
          font-family: var(--font-mono, JetBrains Mono, monospace);
          font-size: 0.88em;
          color: var(--primary);
        }
        .plan-prose pre code {
          background: transparent;
          border: 0;
          padding: 0;
          color: inherit;
        }
        .plan-prose hr {
          border: 0;
          border-top: 1px solid var(--border);
          margin: 1.3rem 0;
        }
        .plan-prose table {
          border-collapse: collapse;
          table-layout: fixed;
          width: 100%;
          margin: 0.85rem 0;
          overflow: hidden;
          border-radius: 0.45rem;
          border: 1px solid var(--border);
        }
        .plan-prose th,
        .plan-prose td {
          border: 1px solid var(--border);
          min-width: 70px;
          padding: 6px 10px;
          position: relative;
          vertical-align: top;
          box-sizing: border-box;
          font-size: 0.88rem;
        }
        .plan-prose th {
          background-color: var(--muted);
          font-weight: 600;
          text-align: left;
        }
        .plan-prose .selectedCell::after {
          content: "";
          position: absolute;
          inset: 0;
          background: rgba(59, 130, 246, 0.12);
          pointer-events: none;
        }
      `}</style>
    </div>
  );
}
