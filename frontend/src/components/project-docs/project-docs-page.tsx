import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { apiFetch } from '@/lib/api-client';
import type { FileTreeNode } from '@/lib/app-types';
import { PROJECT_DOC_STYLES, type ProjectDocStyle } from '@/lib/project-docs';
import { cn } from '@/lib/utils';
import type { Editor } from '@tiptap/core';
import { Extension, mergeAttributes, Node as TiptapNode } from '@tiptap/core';
import Placeholder from '@tiptap/extension-placeholder';
import { EditorContent, NodeViewWrapper, ReactNodeViewRenderer, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Table } from '@tiptap/extension-table';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import { TableRow } from '@tiptap/extension-table-row';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { marked } from 'marked';
import TurndownService from 'turndown';
import {
  Check,
  Code2,
  FileText,
  Hash,
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  Loader2,
  Plus,
  Quote,
  Save,
  TableIcon,
  Text as TextIcon,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

type ProjectDocsPageProps = {
  sessionId: string | null;
  workspace: string;
  fileTree?: FileTreeNode[];
};

type ProjectDocSummary = {
  id: string;
  title: string;
  relativePath: string;
  path?: string;
  exists?: boolean;
};

type ProjectDocPayload = ProjectDocSummary & {
  markdown: string;
};

type ProjectDocsListPayload = {
  activeId?: string;
  documents?: ProjectDocSummary[];
};

type LocalProjectDocDraft = {
  markdown: string;
  savedAt: number;
};

type SlashCommand = {
  id: ProjectDocStyle;
  label: string;
  description: string;
  keywords: string[];
};

type SlashMenuState = {
  from: number;
  to: number;
  query: string;
  left: number;
  bottom: number;
};

type InlineBlockSuggestion = {
  id: string;
  label: string;
  description: string;
  value: string;
  kind: 'file' | 'custom';
};

type InlineBlockAttrs = {
  id: string;
  label: string;
};

type InlineBlockMenuState = SlashMenuState;

type TableSize = {
  rows: number;
  cols: number;
};

type TableControlsState = {
  top: number;
  left: number;
};

type TableAction = 'add-row-after' | 'add-column-after' | 'delete-row' | 'delete-column' | 'delete-table';

type SaveState = 'idle' | 'loading' | 'dirty' | 'syncing' | 'synced' | 'error';

const PROJECT_DOC_SYNC_INTERVAL_MS = 8000;
const PROJECT_DOC_DRAFT_PREFIX = 'supercode:project-docs:draft';
const DEFAULT_TABLE_SIZE: TableSize = { rows: 3, cols: 3 };
const TABLE_DIMENSION_MIN = 1;
const TABLE_DIMENSION_MAX = 12;

const turndown = new TurndownService({
  bulletListMarker: '-',
  codeBlockStyle: 'fenced',
  headingStyle: 'atx',
});

turndown.addRule('projectDocInlineBlock', {
  filter: (node) =>
    node instanceof HTMLElement &&
    node.tagName === 'SPAN' &&
    node.hasAttribute('data-project-doc-inline-block-id'),
  replacement: (_content, node) => {
    if (!(node instanceof HTMLElement)) return '';
    return formatInlineBlockToken(node.getAttribute('data-project-doc-inline-block-id') ?? '');
  },
});

turndown.addRule('projectDocTable', {
  filter: 'table',
  replacement: (_content, node) => {
    if (!(node instanceof HTMLTableElement)) return '';
    const rows = Array.from(node.querySelectorAll('tr')).map((row) =>
      Array.from(row.children)
        .filter((cell): cell is HTMLTableCellElement => cell instanceof HTMLTableCellElement)
        .map((cell) => cell.textContent?.replace(/\s+/g, ' ').trim() ?? ''),
    );
    if (rows.length === 0) return '';

    const columnCount = Math.max(...rows.map((row) => row.length), 1);
    const normalizeRow = (row: string[]) =>
      Array.from({ length: columnCount }, (_, index) => row[index] ?? '');
    const escapeCell = (value: string) => value.replace(/\|/g, '\\|');
    const header = normalizeRow(rows[0]).map(escapeCell);
    const bodyRows = rows.slice(1).map((row) => normalizeRow(row).map(escapeCell));
    const divider = Array.from({ length: columnCount }, () => '---');
    return [
      '',
      `| ${header.join(' | ')} |`,
      `| ${divider.join(' | ')} |`,
      ...bodyRows.map((row) => `| ${row.join(' | ')} |`),
      '',
    ].join('\n');
  },
});

function markdownToHtml(markdown: string) {
  const value = markdown.trim();
  if (!value) return '<p></p>';
  const parsed = marked.parse(value, { async: false, gfm: true });
  return decorateInlineBlockTokens(typeof parsed === 'string' ? parsed : '<p></p>');
}

function htmlToMarkdown(html: string) {
  return turndown.turndown(html).replace(/\r\n/g, '\n').trimEnd();
}

function formatInlineBlockToken(value: string) {
  return `@[${value.replaceAll(']', '\\]')}]`;
}

function decodeInlineBlockTokenValue(value: string) {
  return value.replace(/\\\]/g, ']');
}

function inlineBlockLabel(value: string) {
  if (value.startsWith('file:')) {
    return getPathLeaf(value.slice(5));
  }
  const normalized = value.replace(/\\/g, '/').trim();
  if (!normalized) return '@';
  const parts = normalized.split('/').filter(Boolean);
  return parts.at(-1) ?? normalized;
}

function getPathLeaf(input: string) {
  const normalized = input.replace(/\\/g, '/');
  return normalized.split('/').filter(Boolean).pop() ?? input;
}

function buildFileInlineBlockSuggestions(fileTree: FileTreeNode[]) {
  const suggestions: InlineBlockSuggestion[] = [];
  const seen = new Set<string>();

  const visit = (nodes: FileTreeNode[]) => {
    for (const node of nodes) {
      if (node.type === 'file' && node.path) {
        const key = node.path.toLowerCase();
        if (!seen.has(key)) {
          seen.add(key);
          suggestions.push({
            id: `file:${node.path}`,
            label: node.name || getPathLeaf(node.path),
            description: node.path,
            value: node.path,
            kind: 'file',
          });
        }
      }
      if (node.children) visit(node.children);
    }
  };

  visit(fileTree);
  return suggestions;
}

function decorateInlineBlockTokens(html: string) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  const textNodes: globalThis.Text[] = [];

  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.nodeType !== Node.TEXT_NODE) continue;
    const parent = node.parentElement;
    if (parent?.closest('code, pre, span[data-project-doc-inline-block-id]')) continue;
    textNodes.push(node as globalThis.Text);
  }

  for (const node of textNodes) {
    const text = node.nodeValue ?? '';
    const tokenRe = /@\[((?:\\.|[^\]])*)\]/g;
    if (!tokenRe.test(text)) continue;

    tokenRe.lastIndex = 0;
    const fragment = doc.createDocumentFragment();
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = tokenRe.exec(text)) !== null) {
      const prefix = text.slice(lastIndex, match.index);
      if (prefix) fragment.append(doc.createTextNode(prefix));

      const value = decodeInlineBlockTokenValue(match[1] ?? '');
      const inlineBlock = doc.createElement('span');
      inlineBlock.setAttribute('data-project-doc-inline-block-id', value);
      inlineBlock.setAttribute('data-project-doc-inline-block-label', inlineBlockLabel(value));
      inlineBlock.textContent = inlineBlockLabel(value);
      fragment.append(inlineBlock);

      lastIndex = match.index + match[0].length;
    }

    const suffix = text.slice(lastIndex);
    if (suffix) fragment.append(doc.createTextNode(suffix));
    node.replaceWith(fragment);
  }

  return doc.body.innerHTML || '<p></p>';
}

function projectDocDraftKey(workspace: string, documentId: string) {
  return `${PROJECT_DOC_DRAFT_PREFIX}:${encodeURIComponent(workspace)}:${documentId}`;
}

function readLocalDraft(workspace: string, documentId: string): LocalProjectDocDraft | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(projectDocDraftKey(workspace, documentId));
    if (!raw) return null;
    const payload = JSON.parse(raw) as Partial<LocalProjectDocDraft>;
    if (typeof payload.markdown !== 'string') return null;
    return {
      markdown: payload.markdown,
      savedAt: typeof payload.savedAt === 'number' ? payload.savedAt : 0,
    };
  } catch {
    return null;
  }
}

function writeLocalDraft(workspace: string, documentId: string, markdown: string) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(
    projectDocDraftKey(workspace, documentId),
    JSON.stringify({ markdown, savedAt: Date.now() }),
  );
}

function removeLocalDraft(workspace: string, documentId: string) {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(projectDocDraftKey(workspace, documentId));
}

function normalizeDocumentSummary(document: ProjectDocSummary): ProjectDocSummary {
  return {
    id: String(document.id),
    title: String(document.title || '未命名文档'),
    relativePath: String(document.relativePath || ''),
    path: document.path ? String(document.path) : undefined,
    exists: Boolean(document.exists),
  };
}

function normalizeDocumentPayload(payload: ProjectDocPayload, fallbackId: string): ProjectDocPayload {
  const summary = normalizeDocumentSummary({
    id: String(payload.id || fallbackId),
    title: String(payload.title || '未命名文档'),
    relativePath: String(payload.relativePath || ''),
    path: payload.path,
    exists: payload.exists,
  });
  return {
    ...summary,
    markdown: String(payload.markdown ?? ''),
  };
}

function readApiDetail(payload: unknown, fallback: string) {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    return String((payload as { detail?: unknown }).detail ?? fallback);
  }
  return fallback;
}

function clampTableDimension(value: number) {
  if (!Number.isFinite(value)) return TABLE_DIMENSION_MIN;
  return Math.min(TABLE_DIMENSION_MAX, Math.max(TABLE_DIMENSION_MIN, Math.trunc(value)));
}

function normalizeTableSize(size: TableSize): TableSize {
  return {
    rows: clampTableDimension(size.rows),
    cols: clampTableDimension(size.cols),
  };
}

function buildTableContent(size: TableSize) {
  const { rows, cols } = normalizeTableSize(size);
  return Array.from({ length: rows }, (_, rowIndex) => ({
    type: 'tableRow',
    content: Array.from({ length: cols }, () => ({
      type: rowIndex === 0 ? 'tableHeader' : 'tableCell',
      content: [{ type: 'paragraph' }],
    })),
  }));
}

function getActiveTableControlsState(editor: Editor, frame: HTMLElement | null): TableControlsState | null {
  if (!frame || !editor.isActive('table')) return null;
  const domAtSelection = editor.view.domAtPos(editor.state.selection.from);
  const element =
    domAtSelection.node instanceof HTMLElement ? domAtSelection.node : domAtSelection.node.parentElement;
  const table = element?.closest('table');
  if (!table) return null;

  const tableRect = table.getBoundingClientRect();
  const frameRect = frame.getBoundingClientRect();
  return {
    top: Math.max(8, tableRect.top - frameRect.top - 38),
    left: Math.max(8, tableRect.left - frameRect.left),
  };
}

function getSlashMenuState(editor: Editor): SlashMenuState | null {
  if (editor.view.composing || !editor.state.selection.empty) return null;
  const { from } = editor.state.selection;
  const $from = editor.state.selection.$from;
  const textBefore = $from.parent.textBetween(0, $from.parentOffset, '\n', '\0');
  const slashIndex = textBefore.lastIndexOf('/');
  if (slashIndex < 0) return null;

  const previousChar = textBefore[slashIndex - 1];
  if (previousChar && !/\s/.test(previousChar)) return null;

  const query = textBefore.slice(slashIndex + 1);
  if (/\s/.test(query)) return null;

  const coords = editor.view.coordsAtPos(from);
  return {
    from: from - query.length - 1,
    to: from,
    query,
    left: coords.left,
    bottom: coords.bottom,
  };
}

function getInlineBlockMenuState(editor: Editor): InlineBlockMenuState | null {
  if (editor.view.composing || !editor.state.selection.empty) return null;
  const { from } = editor.state.selection;
  const $from = editor.state.selection.$from;
  const textBefore = $from.parent.textBetween(0, $from.parentOffset, '\n', '\0');
  const mentionStart = textBefore.lastIndexOf('@');
  if (mentionStart < 0) return null;

  const previousChar = textBefore[mentionStart - 1];
  if (previousChar && !/[\s([{"'`]/.test(previousChar)) return null;

  const query = textBefore.slice(mentionStart + 1);
  if (/[\s@]/.test(query)) return null;

  const coords = editor.view.coordsAtPos(from);
  return {
    from: from - query.length - 1,
    to: from,
    query,
    left: coords.left,
    bottom: coords.bottom,
  };
}

const STYLE_ICON_COLOR: Record<ProjectDocStyle, string> = {
  body: '#71717a',
  'heading-1': '#3b82f6',
  'heading-2': '#6366f1',
  'heading-3': '#8b5cf6',
  quote: '#eab308',
  bullet: '#22c55e',
  numbered: '#a855f7',
  code: '#64748b',
  table: '#0f766e',
  divider: '#94a3b8',
};

function iconForStyle(style: ProjectDocStyle) {
  const color = STYLE_ICON_COLOR[style];
  const props = { className: 'size-4', style: { color } };
  if (style === 'heading-1') return <Heading1 {...props} />;
  if (style === 'heading-2') return <Heading2 {...props} />;
  if (style === 'heading-3') return <Heading3 {...props} />;
  if (style === 'quote') return <Quote {...props} />;
  if (style === 'bullet') return <List {...props} />;
  if (style === 'numbered') return <ListOrdered {...props} />;
  if (style === 'code') return <Code2 {...props} />;
  if (style === 'table') return <TableIcon {...props} />;
  return <TextIcon {...props} />;
}

function applyParagraphStyle(editor: Editor, style: ProjectDocStyle, tableSize: TableSize = DEFAULT_TABLE_SIZE) {
  const chain = editor.chain().focus();
  if (style === 'table') {
    chain.insertContent({ type: 'table', content: buildTableContent(tableSize) }).run();
    return;
  }
  if (style === 'body') {
    chain.setParagraph().run();
    return;
  }
  if (style === 'heading-1') {
    chain.toggleHeading({ level: 1 }).run();
    return;
  }
  if (style === 'heading-2') {
    chain.toggleHeading({ level: 2 }).run();
    return;
  }
  if (style === 'heading-3') {
    chain.toggleHeading({ level: 3 }).run();
    return;
  }
  if (style === 'quote') {
    chain.toggleBlockquote().run();
    return;
  }
  if (style === 'bullet') {
    chain.toggleBulletList().run();
    return;
  }
  if (style === 'numbered') {
    chain.toggleOrderedList().run();
    return;
  }
  if (style === 'code') {
    chain.toggleCodeBlock().run();
    return;
  }
  chain.setHorizontalRule().run();
}

function currentStyle(editor: Editor | null): ProjectDocStyle {
  if (!editor) return 'body';
  if (editor.isActive('table')) return 'table';
  if (editor.isActive('heading', { level: 1 })) return 'heading-1';
  if (editor.isActive('heading', { level: 2 })) return 'heading-2';
  if (editor.isActive('heading', { level: 3 })) return 'heading-3';
  if (editor.isActive('blockquote')) return 'quote';
  if (editor.isActive('bulletList')) return 'bullet';
  if (editor.isActive('orderedList')) return 'numbered';
  if (editor.isActive('codeBlock')) return 'code';
  return 'body';
}

function InlineBlockView(props: { node: { attrs: InlineBlockAttrs } }) {
  const attrs = props.node.attrs;
  return (
    <NodeViewWrapper
      as="span"
      className="project-docs-inline-block"
      contentEditable={false}
      data-project-doc-inline-block-id={attrs.id}
      data-project-doc-inline-block-label={attrs.label}
    >
      <span className="project-docs-inline-block-icon">
        <FileText className="size-3" />
      </span>
      <span className="truncate">{attrs.label || inlineBlockLabel(attrs.id)}</span>
    </NodeViewWrapper>
  );
}

const InlineBlockNode = TiptapNode.create({
  name: 'projectDocInlineBlock',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      id: {
        default: '',
        parseHTML: (element: HTMLElement) => element.getAttribute('data-project-doc-inline-block-id') ?? '',
        renderHTML: (attributes: Record<string, unknown>) => ({
          'data-project-doc-inline-block-id': attributes.id,
        }),
      },
      label: {
        default: '',
        parseHTML: (element: HTMLElement) => element.getAttribute('data-project-doc-inline-block-label') ?? '',
        renderHTML: (attributes: Record<string, unknown>) => ({
          'data-project-doc-inline-block-label': attributes.label,
        }),
      },
    };
  },

  parseHTML() {
    return [{ tag: 'span[data-project-doc-inline-block-id]' }];
  },

  renderHTML({ node, HTMLAttributes }) {
    const attrs = node.attrs as InlineBlockAttrs;
    return [
      'span',
      mergeAttributes(HTMLAttributes, {
        'data-project-doc-inline-block-id': attrs.id,
        'data-project-doc-inline-block-label': attrs.label,
      }),
      attrs.label || inlineBlockLabel(attrs.id),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(InlineBlockView);
  },
});

export function ProjectDocsPage({ sessionId, workspace, fileTree = [] }: ProjectDocsPageProps) {
  const lastMarkdownRef = useRef('');
  const serverMarkdownRef = useRef('');
  const syncTimerRef = useRef<number | null>(null);
  const pendingSyncRef = useRef(false);
  const activeDocIdRef = useRef<string | null>(null);
  const editorRef = useRef<Editor | null>(null);
  const hasLoadedRef = useRef(false);
  const workspaceRef = useRef(workspace);
  const syncInFlightRef = useRef<Set<string>>(new Set());
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const articleFrameRef = useRef<HTMLDivElement>(null);
  const tableSizeRef = useRef<TableSize>(DEFAULT_TABLE_SIZE);

  const [documents, setDocuments] = useState<ProjectDocSummary[]>([]);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [hasLoaded, setHasLoaded] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [slashMenu, setSlashMenu] = useState<SlashMenuState | null>(null);
  const [slashIndex, setSlashIndex] = useState(0);
  const [inlineBlockMenu, setInlineBlockMenu] = useState<InlineBlockMenuState | null>(null);
  const [inlineBlockIndex, setInlineBlockIndex] = useState(0);
  const [styleValue, setStyleValue] = useState<ProjectDocStyle>('body');
  const [hoverPos, setHoverPos] = useState<number | null>(null);
  const [hoverCoords, setHoverCoords] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const [insertMenuPos, setInsertMenuPos] = useState<{ top: number; left: number } | null>(null);
  const [insertIndex, setInsertIndex] = useState(0);
  const [tableSize, setTableSize] = useState<TableSize>(DEFAULT_TABLE_SIZE);
  const [tableControls, setTableControls] = useState<TableControlsState | null>(null);

  const slashStateRef = useRef({
    menu: null as SlashMenuState | null,
    index: 0,
    commands: [] as SlashCommand[],
    editor: null as Editor | null,
  });
  const inlineBlockStateRef = useRef({
    menu: null as InlineBlockMenuState | null,
    index: 0,
    suggestions: [] as InlineBlockSuggestion[],
    editor: null as Editor | null,
  });

  const activeDocument = useMemo(
    () => documents.find((document) => document.id === activeDocId) ?? null,
    [activeDocId, documents],
  );

  const filteredCommands = useMemo(() => {
    const query = slashMenu?.query.trim().toLowerCase() ?? '';
    const tableLabel = `${tableSize.rows}x${tableSize.cols}`;
    const commands: SlashCommand[] = PROJECT_DOC_STYLES.map((style) => {
      const isTable = style.id === 'table';
      return {
        ...style,
        label: isTable ? `${style.label} ${tableLabel}` : style.label,
        description: isTable ? `插入 ${tableLabel} 表格` : style.description,
        keywords: [style.id, style.label, style.description, isTable ? tableLabel : ''],
      };
    });
    if (!query) return commands;
    return commands.filter((command) =>
      command.keywords.some((keyword) => keyword.toLowerCase().includes(query)),
    );
  }, [slashMenu?.query, tableSize.cols, tableSize.rows]);

  const inlineBlockSuggestions = useMemo<InlineBlockSuggestion[]>(
    () => buildFileInlineBlockSuggestions(fileTree),
    [fileTree],
  );

  const filteredInlineBlockSuggestions = useMemo<InlineBlockSuggestion[]>(() => {
    const query = inlineBlockMenu?.query.trim().toLowerCase() ?? '';
    if (!query) return inlineBlockSuggestions;
    const matches = inlineBlockSuggestions.filter((suggestion) =>
      [suggestion.label, suggestion.description, suggestion.value].some((item) =>
        item.toLowerCase().includes(query),
      ),
    );
    if (matches.length > 0) return matches;
    const rawQuery = inlineBlockMenu?.query.trim() ?? '';
    return rawQuery
      ? [
          {
            id: 'custom',
            label: rawQuery,
            description: '创建行内块',
            value: `custom:${rawQuery}`,
            kind: 'custom',
          },
        ]
      : [];
  }, [inlineBlockMenu?.query, inlineBlockSuggestions]);

  useEffect(() => {
    tableSizeRef.current = tableSize;
  }, [tableSize]);

  useEffect(() => {
    slashStateRef.current = {
      menu: slashMenu,
      index: slashIndex,
      commands: filteredCommands,
      editor: slashStateRef.current.editor,
    };
  }, [filteredCommands, slashIndex, slashMenu]);

  useEffect(() => {
    inlineBlockStateRef.current = {
      menu: inlineBlockMenu,
      index: inlineBlockIndex,
      suggestions: filteredInlineBlockSuggestions,
      editor: inlineBlockStateRef.current.editor,
    };
  }, [filteredInlineBlockSuggestions, inlineBlockIndex, inlineBlockMenu]);

  const refreshEditorUi = useCallback((currentEditor: Editor) => {
    const nextInlineBlockMenu = getInlineBlockMenuState(currentEditor);
    setInlineBlockMenu(nextInlineBlockMenu);
    setInlineBlockIndex(0);
    setSlashMenu(nextInlineBlockMenu ? null : getSlashMenuState(currentEditor));
    setStyleValue(currentStyle(currentEditor));
    setTableControls(getActiveTableControlsState(currentEditor, articleFrameRef.current));
  }, [setInlineBlockIndex, setInlineBlockMenu, setSlashMenu, setStyleValue, setTableControls]);

  const SlashKeymap = useMemo(
    () =>
      Extension.create({
        name: 'slashKeymap',
        addProseMirrorPlugins() {
          return [
            new Plugin({
              key: new PluginKey('slashTextInput'),
              props: {
                handleTextInput: (_view, _from, _to, text) => {
                  if (text !== '/') return false;
                  window.requestAnimationFrame(() => {
                    const ed = slashStateRef.current.editor ?? editorRef.current;
                    if (!ed) return;
                    refreshEditorUi(ed);
                    setSlashIndex(0);
                  });
                  return false;
                },
              },
            }),
          ];
        },
        addKeyboardShortcuts() {
          return {
            ArrowDown: () => {
              if (inlineBlockStateRef.current.menu) return false;
              const { menu, commands } = slashStateRef.current;
              if (!menu || commands.length === 0) return false;
              setSlashIndex((prev) => (prev + 1) % commands.length);
              return true;
            },
            ArrowUp: () => {
              if (inlineBlockStateRef.current.menu) return false;
              const { menu, commands } = slashStateRef.current;
              if (!menu || commands.length === 0) return false;
              setSlashIndex((prev) => (prev - 1 + commands.length) % commands.length);
              return true;
            },
            Enter: () => {
              const { menu, index, commands, editor: ed } = slashStateRef.current;
              if (!menu || commands.length === 0) return false;
              const cmd = commands[index] ?? commands[0];
              if (ed) {
                ed.chain().focus().deleteRange({ from: menu.from, to: menu.to }).run();
                applyParagraphStyle(ed, cmd.id, tableSizeRef.current);
              }
              setSlashMenu(null);
              setSlashIndex(0);
              return true;
            },
            Escape: () => {
              const { menu } = slashStateRef.current;
              if (!menu) return false;
              setSlashMenu(null);
              return true;
            },
          };
        },
      }),
    [refreshEditorUi, setSlashIndex],
  );

  const insertInlineBlockSuggestion = useCallback((suggestion: InlineBlockSuggestion, menu: InlineBlockMenuState) => {
    const ed = inlineBlockStateRef.current.editor ?? editorRef.current;
    if (!ed) return;
    ed.chain()
      .focus()
      .deleteRange({ from: menu.from, to: menu.to })
      .insertContent([
        {
          type: 'projectDocInlineBlock',
          attrs: {
            id: suggestion.value,
            label: suggestion.label,
          },
        },
        { type: 'text', text: ' ' },
      ])
      .run();
    setInlineBlockMenu(null);
    setInlineBlockIndex(0);
  }, []);

  const InlineBlockKeymap = useMemo(
    () =>
      Extension.create({
        name: 'inlineBlockKeymap',
        addKeyboardShortcuts() {
          return {
            ArrowDown: () => {
              const { menu, suggestions } = inlineBlockStateRef.current;
              if (!menu || suggestions.length === 0) return false;
              setInlineBlockIndex((prev) => (prev + 1) % suggestions.length);
              return true;
            },
            ArrowUp: () => {
              const { menu, suggestions } = inlineBlockStateRef.current;
              if (!menu || suggestions.length === 0) return false;
              setInlineBlockIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
              return true;
            },
            Enter: () => {
              const { menu, index, suggestions } = inlineBlockStateRef.current;
              if (!menu || suggestions.length === 0) return false;
              insertInlineBlockSuggestion(suggestions[index] ?? suggestions[0], menu);
              return true;
            },
            Escape: () => {
              const { menu } = inlineBlockStateRef.current;
              if (!menu) return false;
              setInlineBlockMenu(null);
              return true;
            },
          };
        },
      }),
    [insertInlineBlockSuggestion],
  );

  const HoverPlugin = useMemo(
    () =>
      Extension.create({
        name: 'blockHover',
        addProseMirrorPlugins() {
          let prevPos: number | null = null;
          return [
            new Plugin({
              key: new PluginKey('blockHover'),
              props: {
                handleDOMEvents: {
                  mousemove: (view, event) => {
                    const frame = articleFrameRef.current;
                    if (!frame) return false;
                    const e = event as MouseEvent;
                    const editorElement = frame.querySelector('.project-docs-editor') as HTMLElement | null;
                    const editorRect = editorElement?.getBoundingClientRect() ?? frame.getBoundingClientRect();
                    const paddingLeft = editorElement
                      ? Number.parseFloat(window.getComputedStyle(editorElement).paddingLeft) || 0
                      : 0;
                    const contentLeft = editorRect.left + paddingLeft;

                    if (prevPos !== null && e.clientX < contentLeft) {
                      return false;
                    }

                    const result = view.posAtCoords({ left: e.clientX, top: e.clientY });
                    if (!result) return false;

                    const $pos = view.state.doc.resolve(result.pos);
                    const blockPos = $pos.depth > 0 ? $pos.before(1) : 0;

                    const blockDom = view.nodeDOM(blockPos);
                    let blockTop: number;
                    let blockHeight: number;
                    if (blockDom instanceof HTMLElement) {
                      const rect = blockDom.getBoundingClientRect();
                      blockTop = rect.top;
                      blockHeight = Math.max(24, rect.height);
                    } else {
                      const probePos = Math.max(0, Math.min(blockPos + 1, view.state.doc.content.size));
                      const coords = view.coordsAtPos(probePos);
                      blockTop = coords.top;
                      blockHeight = Math.max(24, coords.bottom - coords.top);
                    }

                    const frameRect = frame.getBoundingClientRect();

                    setHoverCoords({
                      top: blockTop - frameRect.top + Math.max(0, (blockHeight - 24) / 2),
                      left: Math.max(6, editorRect.left - frameRect.left + paddingLeft - 34),
                    });
                    prevPos = blockPos;
                    setHoverPos(blockPos);
                    return false;
                  },
                  mouseleave: (_, event) => {
                    const relatedTarget = (event as MouseEvent).relatedTarget;
                    if (relatedTarget instanceof Node && articleFrameRef.current?.contains(relatedTarget)) {
                      return false;
                    }
                    if (prevPos !== null) {
                      prevPos = null;
                      setHoverPos(null);
                    }
                    return false;
                  },
                },
              },
            }),
          ];
        },
      }),
    [setHoverCoords, setHoverPos],
  );

  const editor = useEditor(
    {
      immediatelyRender: false,
      extensions: [
        StarterKit.configure({ hardBreak: true }),
        InlineBlockNode,
        Table.configure({ resizable: false }),
        TableRow,
        TableCell,
        TableHeader,
        Placeholder.configure({ placeholder: '输入 / 启用下拉菜单' }),
        SlashKeymap,
        InlineBlockKeymap,
        HoverPlugin,
      ],
      content: markdownToHtml(''),
      autofocus: 'end',
      editorProps: {
        attributes: {
          class:
            'project-docs-editor min-h-[calc(100vh-9rem)] px-6 py-8 text-[15px] leading-7 outline-none md:px-14 md:py-12',
        },
      },
      onUpdate({ editor: currentEditor }) {
        const nextMarkdown = htmlToMarkdown(currentEditor.getHTML());
        lastMarkdownRef.current = nextMarkdown;

        const documentId = activeDocIdRef.current;
        if (documentId && hasLoadedRef.current) {
          writeLocalDraft(workspaceRef.current, documentId, nextMarkdown);
          const hasPendingSync = nextMarkdown !== serverMarkdownRef.current;
          pendingSyncRef.current = hasPendingSync;
          if (hasPendingSync) {
            setSaveState((prev) => (prev === 'syncing' ? prev : 'dirty'));
          } else {
            removeLocalDraft(workspaceRef.current, documentId);
            setSaveState('synced');
          }
        }

        refreshEditorUi(currentEditor);
      },
      onSelectionUpdate({ editor: currentEditor }) {
        refreshEditorUi(currentEditor);
      },
    },
    [],
  );

  useEffect(() => {
    editorRef.current = editor;
    if (editor) {
      slashStateRef.current.editor = editor;
      inlineBlockStateRef.current.editor = editor;
    }
  }, [editor]);

  useEffect(() => {
    activeDocIdRef.current = activeDocId;
  }, [activeDocId]);

  useEffect(() => {
    hasLoadedRef.current = hasLoaded;
  }, [hasLoaded]);

  useEffect(() => {
    workspaceRef.current = workspace;
  }, [workspace]);

  const syncDocument = useCallback(
    async (documentId: string, value: string, options: { silent?: boolean } = {}) => {
      if (!sessionId || syncInFlightRef.current.has(documentId)) return;
      syncInFlightRef.current.add(documentId);
      const isActive = activeDocIdRef.current === documentId;
      if (isActive && !options.silent) {
        setSaveState('syncing');
        setErrorMessage('');
      }

      try {
        const response = await apiFetch(`/api/sessions/${sessionId}/project-docs/${encodeURIComponent(documentId)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ markdown: value }),
        });
        const rawPayload = await response.json();
        if (!response.ok) {
          throw new Error(readApiDetail(rawPayload, '同步项目文档失败'));
        }
        const payload = normalizeDocumentPayload(rawPayload as ProjectDocPayload, documentId);

        removeLocalDraft(workspaceRef.current, documentId);
        setDocuments((prev) =>
          prev.map((document) =>
            document.id === documentId
              ? {
                  ...document,
                  title: payload.title,
                  relativePath: payload.relativePath,
                  path: payload.path,
                  exists: true,
                }
              : document,
          ),
        );

        if (activeDocIdRef.current === documentId) {
          serverMarkdownRef.current = value;
          const stillPending = lastMarkdownRef.current !== value;
          pendingSyncRef.current = stillPending;
          if (stillPending) {
            writeLocalDraft(workspaceRef.current, documentId, lastMarkdownRef.current);
            if (!options.silent) setSaveState('dirty');
          } else if (!options.silent) {
            setSaveState('synced');
          }
        }
      } catch (error) {
        if (activeDocIdRef.current === documentId && !options.silent) {
          pendingSyncRef.current = true;
          setSaveState('error');
          setErrorMessage(error instanceof Error ? error.message : '同步项目文档失败');
        }
      } finally {
        syncInFlightRef.current.delete(documentId);
      }
    },
    [sessionId],
  );

  const closeFloatingMenus = useCallback(() => {
    setSlashMenu(null);
    setInlineBlockMenu(null);
    setInsertMenuPos(null);
  }, []);

  const loadDocument = useCallback(
    async (documentId: string) => {
      if (!sessionId) return;
      const currentDocumentId = activeDocIdRef.current;
      if (currentDocumentId && pendingSyncRef.current) {
        void syncDocument(currentDocumentId, lastMarkdownRef.current, { silent: true });
      }

      setHasLoaded(false);
      hasLoadedRef.current = false;
      pendingSyncRef.current = false;
      setSaveState('loading');
      setErrorMessage('');
      closeFloatingMenus();
      setHoverPos(null);
      setTableControls(null);

      try {
        const response = await apiFetch(`/api/sessions/${sessionId}/project-docs/${encodeURIComponent(documentId)}`);
        const rawPayload = await response.json();
        if (!response.ok) {
          throw new Error(readApiDetail(rawPayload, '读取项目文档失败'));
        }
        const payload = normalizeDocumentPayload(rawPayload as ProjectDocPayload, documentId);

        const localDraft = readLocalDraft(workspace, payload.id);
        const nextMarkdown =
          localDraft && localDraft.markdown !== payload.markdown
            ? localDraft.markdown
            : payload.markdown;
        const hasPendingSync = nextMarkdown !== payload.markdown;

        activeDocIdRef.current = payload.id;
        setActiveDocId(payload.id);
        serverMarkdownRef.current = payload.markdown;
        lastMarkdownRef.current = nextMarkdown;
        pendingSyncRef.current = hasPendingSync;
        setDocuments((prev) => {
          const nextSummary = {
            id: payload.id,
            title: payload.title,
            relativePath: payload.relativePath,
            path: payload.path,
            exists: payload.exists,
          };
          if (prev.some((document) => document.id === payload.id)) {
            return prev.map((document) => (document.id === payload.id ? nextSummary : document));
          }
          return [...prev, nextSummary];
        });
        editorRef.current?.commands.setContent(markdownToHtml(nextMarkdown), false);
        setHasLoaded(true);
        hasLoadedRef.current = true;
        setSaveState(hasPendingSync ? 'dirty' : 'synced');
      } catch (error) {
        setHasLoaded(true);
        hasLoadedRef.current = true;
        setSaveState('error');
        setErrorMessage(error instanceof Error ? error.message : '读取项目文档失败');
      }
    },
    [closeFloatingMenus, sessionId, syncDocument, workspace],
  );

  const loadDocuments = useCallback(async () => {
    if (!sessionId) {
      setDocuments([]);
      setActiveDocId(null);
      activeDocIdRef.current = null;
      pendingSyncRef.current = false;
      lastMarkdownRef.current = '';
      serverMarkdownRef.current = '';
      setHasLoaded(false);
      hasLoadedRef.current = false;
      setSaveState('idle');
      return;
    }

    setDocuments([]);
    setActiveDocId(null);
    activeDocIdRef.current = null;
    pendingSyncRef.current = false;
    lastMarkdownRef.current = '';
    serverMarkdownRef.current = '';
    setHasLoaded(false);
    hasLoadedRef.current = false;
    setSaveState('loading');
    setErrorMessage('');

    try {
      const response = await apiFetch(`/api/sessions/${sessionId}/project-docs/documents`);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(readApiDetail(payload, '读取项目文档列表失败'));
      }
      const listPayload = payload as ProjectDocsListPayload;
      const nextDocuments = (listPayload.documents ?? []).map(normalizeDocumentSummary);
      const safeDocuments =
        nextDocuments.length > 0
          ? nextDocuments
          : [{ id: 'main', title: '项目文档', relativePath: '.supercode/project-docs.md', exists: false }];
      setDocuments(safeDocuments);
      const nextActiveId = String(listPayload.activeId || safeDocuments[0].id);
      await loadDocument(nextActiveId);
    } catch (error) {
      setHasLoaded(true);
      hasLoadedRef.current = true;
      setSaveState('error');
      setErrorMessage(error instanceof Error ? error.message : '读取项目文档列表失败');
    }
  }, [loadDocument, sessionId]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    if (!editor || !hasLoaded) return;
    editor.commands.setContent(markdownToHtml(lastMarkdownRef.current), false);
  }, [activeDocId, editor, hasLoaded]);

  useEffect(() => {
    if (!sessionId || !activeDocId || !hasLoaded) return;
    if (syncTimerRef.current !== null) {
      window.clearInterval(syncTimerRef.current);
    }
    syncTimerRef.current = window.setInterval(() => {
      const documentId = activeDocIdRef.current;
      if (!documentId || !pendingSyncRef.current) return;
      void syncDocument(documentId, lastMarkdownRef.current);
    }, PROJECT_DOC_SYNC_INTERVAL_MS);

    return () => {
      if (syncTimerRef.current !== null) {
        window.clearInterval(syncTimerRef.current);
        syncTimerRef.current = null;
      }
    };
  }, [activeDocId, hasLoaded, sessionId, syncDocument]);

  const handleCreateDocument = useCallback(async () => {
    if (!sessionId) return;
    const currentDocumentId = activeDocIdRef.current;
    if (currentDocumentId && pendingSyncRef.current) {
      void syncDocument(currentDocumentId, lastMarkdownRef.current, { silent: true });
    }

    setSaveState('loading');
    setErrorMessage('');
    try {
      const response = await apiFetch(`/api/sessions/${sessionId}/project-docs/documents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const rawPayload = await response.json();
      if (!response.ok) {
        throw new Error(readApiDetail(rawPayload, '新建项目文档失败'));
      }
      const payload = normalizeDocumentPayload(rawPayload as ProjectDocPayload, 'main');

      activeDocIdRef.current = payload.id;
      setActiveDocId(payload.id);
      serverMarkdownRef.current = payload.markdown;
      lastMarkdownRef.current = payload.markdown;
      pendingSyncRef.current = false;
      removeLocalDraft(workspaceRef.current, payload.id);
      setDocuments((prev) => [...prev, payload]);
      editorRef.current?.commands.setContent(markdownToHtml(payload.markdown), false);
      setHasLoaded(true);
      hasLoadedRef.current = true;
      setSaveState('synced');
    } catch (error) {
      setSaveState('error');
      setErrorMessage(error instanceof Error ? error.message : '新建项目文档失败');
    }
  }, [sessionId, syncDocument]);

  const handleSelectDocument = useCallback(
    (documentId: string) => {
      if (documentId === activeDocIdRef.current || saveState === 'loading') return;
      void loadDocument(documentId);
    },
    [loadDocument, saveState],
  );

  const updateTableSize = useCallback((key: keyof TableSize, rawValue: string) => {
    const parsed = Number.parseInt(rawValue, 10);
    setTableSize((prev) => ({
      ...prev,
      [key]: clampTableDimension(parsed),
    }));
  }, [setTableSize]);

  const insertTableAtSelection = useCallback(() => {
    if (!editor) return;
    applyParagraphStyle(editor, 'table', tableSize);
    window.requestAnimationFrame(() => setTableControls(getActiveTableControlsState(editor, articleFrameRef.current)));
  }, [editor, setTableControls, tableSize]);

  const handleTableAction = useCallback(
    (action: TableAction) => {
      if (!editor) return;
      const chain = editor.chain().focus();
      if (action === 'add-row-after') chain.addRowAfter().run();
      if (action === 'add-column-after') chain.addColumnAfter().run();
      if (action === 'delete-row') chain.deleteRow().run();
      if (action === 'delete-column') chain.deleteColumn().run();
      if (action === 'delete-table') chain.deleteTable().run();
      window.requestAnimationFrame(() => setTableControls(getActiveTableControlsState(editor, articleFrameRef.current)));
    },
    [editor, setTableControls],
  );

  const handleInsert = useCallback(
    (style: ProjectDocStyle) => {
      if (!editor || hoverPos === null) return;
      const node = editor.state.doc.nodeAt(hoverPos);
      const insertAt = node ? hoverPos + node.nodeSize : hoverPos + 1;
      if (style === 'divider') {
        editor.chain().focus().insertContentAt(insertAt, { type: 'horizontalRule' }).run();
      } else if (style === 'table') {
        editor
          .chain()
          .focus()
          .insertContentAt(insertAt, {
            type: 'table',
            content: buildTableContent(tableSize),
          })
          .run();
      } else {
        editor
          .chain()
          .focus()
          .insertContentAt(insertAt, { type: 'paragraph' })
          .setTextSelection(insertAt + 1)
          .run();
        applyParagraphStyle(editor, style);
      }
      setInsertMenuPos(null);
      setInsertIndex(0);
    },
    [editor, hoverPos, setInsertIndex, setInsertMenuPos, tableSize],
  );

  const statusLabel =
    saveState === 'syncing'
      ? '同步中'
      : saveState === 'loading'
        ? '读取中'
        : saveState === 'error'
          ? '同步失败'
          : saveState === 'dirty'
            ? '本地已保存'
            : saveState === 'synced'
              ? '已同步'
              : '未加载';

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background text-foreground">
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-background/80 px-4 backdrop-blur">
          <div className="flex min-w-0 items-center gap-3">
            <Select
              value={styleValue}
              onValueChange={(value) => {
                const style = value as ProjectDocStyle;
                setStyleValue(style);
                if (editor) applyParagraphStyle(editor, style, tableSize);
              }}
            >
              <SelectTrigger size="sm" className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="start">
                {PROJECT_DOC_STYLES.map((style) => (
                  <SelectItem key={style.id} value={style.id}>
                    <span className="flex items-center gap-2">
                      {iconForStyle(style.id)}
                      {style.label}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="hidden items-center gap-1.5 rounded-md border border-border bg-muted/30 px-2 py-1 sm:flex">
              <span className="text-[11px] font-medium text-muted-foreground">表格</span>
              <input
                aria-label="表格行数"
                type="number"
                min={TABLE_DIMENSION_MIN}
                max={TABLE_DIMENSION_MAX}
                value={tableSize.rows}
                onChange={(event) => updateTableSize('rows', event.currentTarget.value)}
                className="h-6 w-10 rounded border border-border bg-background px-1.5 text-center text-xs outline-none focus:border-ring"
              />
              <span className="text-xs text-muted-foreground">x</span>
              <input
                aria-label="表格列数"
                type="number"
                min={TABLE_DIMENSION_MIN}
                max={TABLE_DIMENSION_MAX}
                value={tableSize.cols}
                onChange={(event) => updateTableSize('cols', event.currentTarget.value)}
                className="h-6 w-10 rounded border border-border bg-background px-1.5 text-center text-xs outline-none focus:border-ring"
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-xs"
                disabled={!editor}
                onMouseDown={(event) => event.preventDefault()}
                onClick={insertTableAtSelection}
              >
                插入
              </Button>
            </div>
            <span className="hidden truncate text-xs text-muted-foreground sm:inline">
              {activeDocument?.relativePath || workspace}
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className={cn('h-8 gap-1.5 text-xs', saveState === 'error' && 'text-destructive')}
            disabled={!activeDocId || saveState === 'loading' || saveState === 'syncing'}
            onClick={() => {
              const documentId = activeDocIdRef.current;
              if (documentId) void syncDocument(documentId, lastMarkdownRef.current);
            }}
          >
            {saveState === 'synced' ? (
              <Check className="size-3.5" />
            ) : saveState === 'loading' || saveState === 'syncing' ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Save className="size-3.5" />
            )}
            {statusLabel}
          </Button>
        </div>

        {sessionId ? (
          <div className="flex min-h-0 flex-1">
            <aside className="flex w-52 shrink-0 flex-col border-r border-border bg-muted/20">
              <div className="flex h-11 shrink-0 items-center justify-between px-3">
                <span className="text-xs font-medium text-muted-foreground">文档</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  title="新建文档"
                  onClick={() => void handleCreateDocument()}
                  disabled={saveState === 'loading'}
                >
                  <Plus className="size-3.5" />
                </Button>
              </div>
              <div className="min-h-0 flex-1 overflow-auto px-2 pb-3">
                {documents.map((document) => {
                  const isActive = document.id === activeDocId;
                  return (
                    <button
                      key={document.id}
                      type="button"
                      title={document.relativePath}
                      className={cn(
                        'flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors',
                        isActive
                          ? 'bg-background text-foreground shadow-xs'
                          : 'text-muted-foreground hover:bg-background/70 hover:text-foreground',
                      )}
                      onClick={() => handleSelectDocument(document.id)}
                    >
                      <FileText className={cn('size-4 shrink-0', isActive ? 'text-primary' : 'text-muted-foreground')} />
                      <span className="min-w-0 flex-1 truncate">{document.title}</span>
                    </button>
                  );
                })}
              </div>
            </aside>

            <div ref={editorContainerRef} className="editor-scroll-container min-h-0 flex-1 overflow-auto">
              <div
                ref={articleFrameRef}
                className="relative mx-auto min-h-full max-w-4xl bg-background shadow-[0_1px_0_rgba(0,0,0,0.04)]"
                onMouseLeave={(event) => {
                  const relatedTarget = event.relatedTarget;
                  if (relatedTarget instanceof Node && articleFrameRef.current?.contains(relatedTarget)) return;
                  setHoverPos(null);
                  closeFloatingMenus();
                }}
              >
                <EditorContent editor={editor} />

                {tableControls && (
                  <div
                    className="slash-menu-animate absolute z-30 flex items-center gap-1 rounded-lg border border-border bg-popover p-1 text-xs shadow-xl"
                    style={{ top: tableControls.top, left: tableControls.left, transformOrigin: 'bottom left' }}
                    onMouseDown={(event) => event.preventDefault()}
                  >
                    <button
                      type="button"
                      title="在下方插入行"
                      className="flex h-7 items-center gap-1 rounded-md px-2 text-popover-foreground transition-colors hover:bg-accent"
                      onMouseDown={(event) => {
                        event.preventDefault();
                        handleTableAction('add-row-after');
                      }}
                    >
                      <Plus className="size-3.5" />
                      行
                    </button>
                    <button
                      type="button"
                      title="在右侧插入列"
                      className="flex h-7 items-center gap-1 rounded-md px-2 text-popover-foreground transition-colors hover:bg-accent"
                      onMouseDown={(event) => {
                        event.preventDefault();
                        handleTableAction('add-column-after');
                      }}
                    >
                      <Plus className="size-3.5" />
                      列
                    </button>
                    <span className="mx-1 h-4 w-px bg-border" />
                    <button
                      type="button"
                      title="删除当前行"
                      className="h-7 rounded-md px-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                      onMouseDown={(event) => {
                        event.preventDefault();
                        handleTableAction('delete-row');
                      }}
                    >
                      删行
                    </button>
                    <button
                      type="button"
                      title="删除当前列"
                      className="h-7 rounded-md px-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                      onMouseDown={(event) => {
                        event.preventDefault();
                        handleTableAction('delete-column');
                      }}
                    >
                      删列
                    </button>
                    <button
                      type="button"
                      title="删除表格"
                      className="h-7 rounded-md px-2 text-destructive transition-colors hover:bg-destructive/10"
                      onMouseDown={(event) => {
                        event.preventDefault();
                        handleTableAction('delete-table');
                      }}
                    >
                      删表
                    </button>
                  </div>
                )}

                {hoverPos !== null && (
                  <button
                    type="button"
                    className="block-hover-plus absolute z-10 flex size-6 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    style={{ top: hoverCoords.top, left: hoverCoords.left }}
                    onMouseEnter={() => {
                      if (insertMenuPos) return;
                      setHoverPos((prev) => prev ?? hoverPos);
                    }}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setInsertMenuPos((prev) =>
                        prev ? null : { top: hoverCoords.top + 24, left: hoverCoords.left },
                      );
                    }}
                  >
                    <Plus className="size-4" />
                  </button>
                )}

                {insertMenuPos && (
                  <div
                    className="slash-menu-animate absolute z-20 w-60 overflow-hidden rounded-lg border border-border bg-popover p-1 shadow-xl"
                    style={{ top: insertMenuPos.top, left: insertMenuPos.left, transformOrigin: 'top left' }}
                    onMouseLeave={() => setInsertMenuPos(null)}
                  >
                    {PROJECT_DOC_STYLES.map((style, index) => (
                      <button
                        key={style.id}
                        type="button"
                        className={cn(
                          'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-sm outline-none transition-colors',
                          index === insertIndex
                            ? 'bg-accent text-accent-foreground'
                            : 'text-popover-foreground hover:bg-accent/50',
                        )}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          handleInsert(style.id);
                        }}
                        onMouseEnter={() => setInsertIndex(index)}
                      >
                        <span className="flex size-5 shrink-0 items-center justify-center">
                          {iconForStyle(style.id)}
                        </span>
                        <span className="truncate font-medium">
                          {style.id === 'table' ? `${style.label} ${tableSize.rows}x${tableSize.cols}` : style.label}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            请先创建或恢复一个会话。
          </div>
        )}

        {errorMessage ? (
          <div className="border-t border-destructive/20 bg-destructive/8 px-4 py-2 text-xs text-destructive">
            {errorMessage}
          </div>
        ) : null}
      </main>

      {slashMenu && filteredCommands.length > 0
        ? createPortal(
            <div
              key="slash-menu"
              className="slash-menu-animate fixed z-[80] w-60 overflow-hidden rounded-lg border border-border bg-popover p-1 shadow-xl"
              style={{
                left: Math.min(Math.max(12, slashMenu.left), window.innerWidth - 256),
                top: Math.min(slashMenu.bottom + 8, window.innerHeight - 320),
                transformOrigin: 'top left',
              }}
            >
              {filteredCommands.map((command, index) => (
                <button
                  key={command.id}
                  type="button"
                  className={cn(
                    'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-sm outline-none transition-colors',
                    index === slashIndex
                      ? 'bg-accent text-accent-foreground'
                      : 'text-popover-foreground hover:bg-accent/50',
                  )}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    if (!editor || !slashMenu) return;
                    editor.chain().focus().deleteRange({ from: slashMenu.from, to: slashMenu.to }).run();
                    applyParagraphStyle(editor, command.id, tableSize);
                    setSlashMenu(null);
                    setSlashIndex(0);
                  }}
                >
                  <span className="flex size-5 shrink-0 items-center justify-center">
                    {iconForStyle(command.id)}
                  </span>
                  <span className="truncate font-medium">{command.label}</span>
                </button>
              ))}
            </div>,
            document.body,
          )
        : null}

      {inlineBlockMenu
        ? createPortal(
            <div
              key="inline-block-menu"
              className="slash-menu-animate fixed z-[80] w-72 overflow-hidden rounded-lg border border-border bg-popover p-1 shadow-xl"
              style={{
                left: Math.min(Math.max(12, inlineBlockMenu.left), window.innerWidth - 304),
                top: Math.min(inlineBlockMenu.bottom + 8, window.innerHeight - 280),
                transformOrigin: 'top left',
              }}
            >
              {filteredInlineBlockSuggestions.length > 0 ? (
                filteredInlineBlockSuggestions.map((suggestion, index) => (
                  <button
                    key={suggestion.id}
                    type="button"
                    className={cn(
                      'flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left text-sm outline-none transition-colors',
                      index === inlineBlockIndex
                        ? 'bg-accent text-accent-foreground'
                        : 'text-popover-foreground hover:bg-accent/50',
                    )}
                    onMouseEnter={() => setInlineBlockIndex(index)}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      insertInlineBlockSuggestion(suggestion, inlineBlockMenu);
                    }}
                  >
                    <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                      {suggestion.kind === 'file' ? (
                        <FileText className="size-3.5" />
                      ) : (
                        <Hash className="size-3.5" />
                      )}
                    </span>
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-medium">{suggestion.label}</span>
                      <span className="truncate text-xs text-muted-foreground">{suggestion.description}</span>
                    </span>
                  </button>
                ))
              ) : (
                <div className="rounded-md px-2.5 py-2 text-xs text-muted-foreground">
                  暂无可引用文件
                </div>
              )}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
