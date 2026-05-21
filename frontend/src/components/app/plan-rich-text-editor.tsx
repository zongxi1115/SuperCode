"use client";

import { cn } from "@/lib/utils";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { marked } from "marked";
import TurndownService from "turndown";
import {
  Bold,
  ChevronDown,
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
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";

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
  viewportBottom: number;
};

type PlanRichTextEditorProps = {
  value: string;
  onChange: (markdown: string) => void;
  autoFocus?: boolean;
};

const turndown = new TurndownService({
  bulletListMarker: "-",
  codeBlockStyle: "fenced",
  headingStyle: "atx",
});

function normalizeMarkdown(value: string) {
  return value.replace(/\r\n/g, "\n").trimEnd();
}

function markdownToHtml(markdown: string) {
  const normalized = markdown.trim();
  if (!normalized) {
    return "<p></p>";
  }
  return marked.parse(normalized, { async: false }) as string;
}

function htmlToMarkdown(html: string) {
  return normalizeMarkdown(turndown.turndown(html));
}

function getSlashMenuState(
  editor: NonNullable<ReturnType<typeof useEditor>>,
  anchorRect: DOMRect | null,
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
    left: coords.left - (anchorRect?.left ?? 0),
    top: coords.top - (anchorRect?.top ?? 0),
    bottom: coords.bottom - (anchorRect?.top ?? 0),
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
        "inline-flex h-8 items-center justify-center rounded-md border px-2 text-muted-foreground transition-colors",
        active
          ? "border-primary/30 bg-primary/10 text-primary"
          : "border-border/60 bg-background hover:bg-accent hover:text-foreground",
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
}: PlanRichTextEditorProps) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const lastMarkdownRef = useRef(normalizeMarkdown(value));
  const [slashMenu, setSlashMenu] = useState<SlashMenuState | null>(null);
  const [slashNavigation, setSlashNavigation] = useState<{
    key: string | null;
    index: number;
  }>({
    key: null,
    index: 0,
  });
  const [bubbleToolbar, setBubbleToolbar] = useState<BubbleToolbarState | null>(null);

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
    const fromCoords = currentEditor.view.coordsAtPos(from);
    const toCoords = currentEditor.view.coordsAtPos(to);
    const left = (fromCoords.left + toCoords.left) / 2 - anchorRect.left;
    const top = fromCoords.top - anchorRect.top - 10;
    setBubbleToolbar({ left, top });
  }, []);

  const editor = useEditor(
    {
      immediatelyRender: false,
      extensions: [
        StarterKit.configure({
          hardBreak: true,
        }),
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
      },
      onUpdate({ editor: currentEditor }) {
        const markdown = htmlToMarkdown(currentEditor.getHTML());
        lastMarkdownRef.current = markdown;
        onChange(markdown);
        setSlashMenu(getSlashMenuState(currentEditor, anchorRef.current?.getBoundingClientRect() ?? null));
        updateBubbleToolbar(currentEditor);
      },
      onSelectionUpdate({ editor: currentEditor }) {
        setSlashMenu(getSlashMenuState(currentEditor, anchorRef.current?.getBoundingClientRect() ?? null));
        updateBubbleToolbar(currentEditor);
      },
    },
    [],
  );

  useEffect(() => {
    if (!editor) return;
    const normalized = normalizeMarkdown(value);
    if (normalized === lastMarkdownRef.current) return;
    editor.commands.setContent(markdownToHtml(normalized), false);
    lastMarkdownRef.current = normalized;
  }, [editor, value]);

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

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (!editor) return;

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
    ],
  );

  const dropdownStyle = useMemo(() => {
    if (!slashMenu) return null;
    const estimatedHeight = Math.min(filteredSlashCommands.length || 1, 6) * 52 + 12;
    const fitsBelow = slashMenu.viewportBottom + estimatedHeight < window.innerHeight - 16;
    return {
      left: Math.max(0, slashMenu.left),
      top: fitsBelow
        ? slashMenu.bottom + 10
        : Math.max(0, slashMenu.top - estimatedHeight - 10),
    };
  }, [filteredSlashCommands.length, slashMenu]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-[radial-gradient(circle_at_top,_rgba(59,130,246,0.07),_transparent_34%),linear-gradient(180deg,rgba(255,255,255,0.04),transparent)]">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/60 bg-muted/25 px-4 py-3">
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
        <div className="mx-1 h-5 w-px bg-border/70" />
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
          label="分割线"
          onMouseDown={(event) => {
            event.preventDefault();
            editor?.chain().focus().setHorizontalRule().run();
          }}
        >
          <Minus className="size-3.5" />
        </ToolbarButton>
        <div className="ml-auto flex items-center gap-1 rounded-full bg-background/80 px-2.5 py-1 text-[11px] text-muted-foreground shadow-sm">
          <ChevronDown className="size-3" />
          输入 <span className="font-medium text-foreground">/</span> 打开结构菜单
        </div>
      </div>

      <div ref={anchorRef} className="relative flex-1 min-h-0 overflow-auto">
        <EditorContent editor={editor} onKeyDown={handleKeyDown} />

        <AnimatePresence>
          {bubbleToolbar && !slashMenu && editor && (
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
            </motion.div>
          )}
        </AnimatePresence>

        {slashMenu && dropdownStyle ? (
          <div
            className="absolute z-50 w-fit min-w-[17rem] max-w-[min(32rem,calc(100vw-4rem))] rounded-xl border border-border/60 bg-popover/98 p-1.5 shadow-xl backdrop-blur"
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
          </div>
        ) : null}
      </div>
    </div>
  );
}
