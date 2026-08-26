import Editor from '@monaco-editor/react';
import { SiJetbrains, SiSublimetext, SiVscodium, SiZedindustries } from '@icons-pack/react-simple-icons';
import { FileTree } from '@/components/ai-elements/file-tree';
import { EditorSidebar } from '@/components/app/editor-sidebar';
import { PlanRichTextEditor, type Annotation } from '@/components/app/plan-rich-text-editor';
import { EditorTools, type EditorTarget } from '@/components/app/editor-tools';
import { renderFileTreeNodes } from '@/components/app/file-tree-renderers';
import { ResizableHandle } from '@/components/app/resizable-handle';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { message as appMessage } from '@/components/ui/message';
import { getFileLanguage } from '@/lib/app-utils';
import { apiFetch, apiUrl } from '@/lib/api-client';
import type { FileTreeNode } from '@/lib/app-types';
import { CircleAlert, FileCode, FolderTree, Maximize2, Minimize2, PanelsTopLeft, RefreshCw, SquareTerminal } from 'lucide-react';
import type { editor as MonacoEditor } from 'monaco-editor';
import { useCallback, useEffect, useRef, useState } from 'react';

export type PlanData = {
  title: string;
  markdown: string;
};

export type CodeSelectionContext = {
  filePath: string;
  language: string;
  selectedText: string;
  startLineNumber: number;
  endLineNumber: number;
};

type EditorPanelProps = {
  fileTree: FileTreeNode[];
  selectedFilePath: string;
  selectedFileContent: string;
  onLoadFile: (path: string) => void | Promise<void>;
  onLoadDirectory?: (path: string) => void | Promise<void>;
  onSaveFile?: (path: string, content: string) => void | Promise<void>;
  onRefreshFileTree?: () => void | Promise<void>;
  sessionId: string | null;
  isWebPreviewOpen: boolean;
  onToggleWebPreview: () => void;
  webPreviewUrl: string;
  onWebPreviewUrlChange: (url: string) => void;
  onSelectPreviewElement?: (html: string, selector: string, sourceUrl?: string) => void;
  planData?: PlanData | null;
  onPlanSave?: (markdown: string, annotations: Annotation[]) => void;
  onPlanAnnotationsChange?: (annotations: Annotation[]) => void;
  onSubmitPlan?: (markdown: string, annotations: Annotation[]) => void;
  onClosePlan?: () => void;
  onAddCodeContext?: (context: CodeSelectionContext) => void;
  isDarkMode?: boolean;
};

const DEFAULT_FILE_TREE_WIDTH = 200;
const MIN_FILE_TREE_WIDTH = 180;
const MAX_FILE_TREE_WIDTH = 420;

const EDITORS: EditorTarget[] = [
  { name: 'VS Code', command: 'code', icon: <SiVscodium size={14} color="#007ACC" /> },
  { name: 'VS Code Insiders', command: 'code-insiders', icon: <SiVscodium size={14} color="#24BFA5" /> },
  { name: 'Zed', command: 'zed', icon: <SiZedindustries size={14} color="#084CCF" /> },
  { name: 'Visual Studio', command: 'devenv', icon: <SquareTerminal className="h-3.5 w-3.5 text-violet-500" /> },
  { name: 'Sublime Text', command: 'subl', icon: <SiSublimetext size={14} color="#FF9800" /> },
  { name: 'WebStorm', command: 'webstorm', icon: <SiJetbrains size={14} color="#000000" /> },
];

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function EditorPanel({
  fileTree,
  selectedFilePath,
  selectedFileContent,
  onLoadFile,
  onLoadDirectory,
  onSaveFile,
  onRefreshFileTree,
  sessionId,
  isWebPreviewOpen,
  onToggleWebPreview,
  webPreviewUrl,
  onWebPreviewUrlChange,
  onSelectPreviewElement,
  planData,
  onPlanSave,
  onPlanAnnotationsChange,
  onSubmitPlan,
  onClosePlan,
  onAddCodeContext,
  isDarkMode = false,
}: EditorPanelProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [fileTreeWidth, setFileTreeWidth] = useState(DEFAULT_FILE_TREE_WIDTH);
  const [isFileTreeVisible, setIsFileTreeVisible] = useState(true);
  const [isFileTreeResizing, setIsFileTreeResizing] = useState(false);
  const [editorLaunchError, setEditorLaunchError] = useState<string | null>(null);
  const [planEditContent, setPlanEditContent] = useState('');
  const [isEditorFullscreen, setIsEditorFullscreen] = useState(false);
  const [isRefreshingFileTree, setIsRefreshingFileTree] = useState(false);
  const monacoRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null);
  const fullscreenMonacoRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null);
  const isEditorFullscreenRef = useRef(isEditorFullscreen);
  const isEditingRef = useRef(false);
  const editContentRef = useRef('');
  const selectedFilePathRef = useRef(selectedFilePath);
  const onAddCodeContextRef = useRef(onAddCodeContext);
  const lastPlanSyncRef = useRef<string | null>(null);
  const planAnnotationsRef = useRef<Annotation[]>([]);

  const isPlanMode = Boolean(planData);

  useEffect(() => {
    isEditingRef.current = isEditing;
  }, [isEditing]);

  useEffect(() => {
    isEditorFullscreenRef.current = isEditorFullscreen;
  }, [isEditorFullscreen]);

  useEffect(() => {
    editContentRef.current = editContent;
  }, [editContent]);

  useEffect(() => {
    selectedFilePathRef.current = selectedFilePath;
  }, [selectedFilePath]);

  useEffect(() => {
    onAddCodeContextRef.current = onAddCodeContext;
  }, [onAddCodeContext]);

  useEffect(() => {
    setIsEditing(false);
    setEditContent('');
  }, [selectedFilePath]);

  useEffect(() => {
    if (!planData) {
      lastPlanSyncRef.current = null;
      planAnnotationsRef.current = [];
      setPlanEditContent('');
      onPlanAnnotationsChange?.([]);
      return;
    }

    if (lastPlanSyncRef.current === planData.markdown) {
      return;
    }

    lastPlanSyncRef.current = planData.markdown;
    planAnnotationsRef.current = [];
    onPlanAnnotationsChange?.([]);
    setPlanEditContent((current) => (current === planData.markdown ? current : planData.markdown));
  }, [onPlanAnnotationsChange, planData]);

  useEffect(() => {
    if (isWebPreviewOpen) {
      setIsFileTreeVisible(false);
    }
  }, [isWebPreviewOpen]);

  const handleStartEdit = useCallback(() => {
    if (!selectedFilePath) return;
    setEditContent(selectedFileContent);
    setIsEditing(true);
    setTimeout(() => {
      const activeEditor = isEditorFullscreenRef.current
        ? fullscreenMonacoRef.current ?? monacoRef.current
        : monacoRef.current ?? fullscreenMonacoRef.current;
      activeEditor?.focus();
    }, 50);
  }, [selectedFileContent, selectedFilePath]);

  const handleCancelEdit = useCallback(() => {
    setIsEditing(false);
    setEditContent('');
  }, []);

  const handleSave = useCallback(async () => {
    if (!sessionId || !selectedFilePath) return;

    setIsSaving(true);
    try {
      if (onSaveFile) {
        await onSaveFile(selectedFilePath, editContentRef.current);
      } else {
        const query = new URLSearchParams({
          session_id: sessionId,
          path: selectedFilePath,
        });
        const res = await apiFetch(`/api/files?${query.toString()}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: editContentRef.current }),
        });
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.error || '保存失败');
        }
      }
      setIsEditing(false);
      setEditContent('');
      void onLoadFile(selectedFilePath);
      appMessage.success('文件已保存');
    } catch (error) {
      console.error(error);
      appMessage.error(getErrorMessage(error, '保存失败'));
    } finally {
      setIsSaving(false);
    }
  }, [onLoadFile, onSaveFile, selectedFilePath, sessionId]);

  const handleSaveRef = useRef(handleSave);
  useEffect(() => {
    handleSaveRef.current = handleSave;
  }, [handleSave]);

  useEffect(() => {
    if (!isEditing && !isPlanMode) return;

    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (isPlanMode) {
          onPlanSave?.(planEditContent, planAnnotationsRef.current);
        } else if (isEditingRef.current) {
          void handleSaveRef.current();
        }
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isEditing, isPlanMode, onPlanSave, planEditContent]);

  const handleFileTreeResize = useCallback((delta: number) => {
    setFileTreeWidth((prev) => Math.min(Math.max(prev + delta, MIN_FILE_TREE_WIDTH), MAX_FILE_TREE_WIDTH));
  }, []);

  const getCodeSelectionContext = useCallback((editor: MonacoEditor.ICodeEditor): CodeSelectionContext | null => {
    const filePath = selectedFilePathRef.current;
    const model = editor.getModel();
    const selection = editor.getSelection();

    if (!filePath || !model || !selection || selection.isEmpty()) {
      return null;
    }

    const selectedText = model.getValueInRange(selection);
    if (!selectedText.trim()) {
      return null;
    }

    const startLineNumber = Math.min(selection.startLineNumber, selection.endLineNumber);
    const endLineNumber = Math.max(selection.startLineNumber, selection.endLineNumber);

    return {
      filePath,
      language: getFileLanguage(filePath),
      selectedText,
      startLineNumber,
      endLineNumber,
    };
  }, []);

  const handleEditorMount = useCallback(
    (
      editor: MonacoEditor.IStandaloneCodeEditor,
      monaco: typeof import('monaco-editor'),
      isFullscreenEditor = false,
    ) => {
      if (isFullscreenEditor) {
        fullscreenMonacoRef.current = editor;
      } else {
        monacoRef.current = editor;
      }
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
        if (isEditingRef.current) {
          void handleSaveRef.current();
        }
      });
      const addContextActionDisposable = editor.addAction({
        id: isFullscreenEditor
          ? 'supercode.addSelectedCodeToChat.fullscreen'
          : 'supercode.addSelectedCodeToChat',
        label: '添加选中代码到对话',
        precondition: 'editorHasSelection',
        contextMenuGroupId: 'navigation',
        contextMenuOrder: 1.5,
        run: (activeEditor) => {
          const context = getCodeSelectionContext(activeEditor);
          if (!context) return;
          onAddCodeContextRef.current?.(context);
        },
      });
      editor.onDidDispose(() => {
        addContextActionDisposable.dispose();
        if (isFullscreenEditor && fullscreenMonacoRef.current === editor) {
          fullscreenMonacoRef.current = null;
        }
        if (!isFullscreenEditor && monacoRef.current === editor) {
          monacoRef.current = null;
        }
      });
    },
    [getCodeSelectionContext],
  );

  const openInEditor = useCallback(async (command: string) => {
    if (!sessionId || !selectedFilePath) return;

    try {
      const res = await apiFetch('/api/files/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          path: selectedFilePath,
          editor: command,
        }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(String(data.detail ?? data.error ?? '未安装该应用或未将其添加到 PATH 中。'));
      }
    } catch (error) {
      console.error(error);
      setEditorLaunchError(
        error instanceof Error && error.message
          ? error.message
          : '未安装该应用或未将其添加到 PATH 中。',
      );
      appMessage.error(getErrorMessage(error, '打开外部编辑器失败'));
    }
  }, [selectedFilePath, sessionId]);

  const handleRefreshFileTree = useCallback(async () => {
    if (isRefreshingFileTree || !onRefreshFileTree) return;

    setIsRefreshingFileTree(true);
    try {
      await onRefreshFileTree();
    } catch (error) {
      console.error('刷新文件树失败:', error);
      appMessage.error(getErrorMessage(error, '刷新文件树失败'));
    } finally {
      setIsRefreshingFileTree(false);
    }
  }, [isRefreshingFileTree, onRefreshFileTree]);

  const hasSelectedFile = Boolean(selectedFilePath);
  const selectedFileExtension = selectedFilePath.split('.').pop()?.toLowerCase() ?? '';
  const isSelectedHtmlFile = selectedFileExtension === 'html' || selectedFileExtension === 'htm';
  const handleOpenHtmlPreview = useCallback(() => {
    if (!sessionId || !selectedFilePath) return;
    const query = new URLSearchParams({
      session_id: sessionId,
      path: selectedFilePath,
    });
    onWebPreviewUrlChange(apiUrl(`/api/files/preview?${query.toString()}`));
    if (!isWebPreviewOpen) {
      onToggleWebPreview();
    }
  }, [isWebPreviewOpen, onToggleWebPreview, onWebPreviewUrlChange, selectedFilePath, sessionId]);
  const shouldShowFileTree = !isWebPreviewOpen && isFileTreeVisible;

  return (
    <>
      <div className="flex-1 min-h-0 p-2">
        <div className="flex h-full min-h-0 w-full overflow-hidden rounded-xl border border-border/70 bg-background shadow-xs">
          {isWebPreviewOpen ? (
            <EditorSidebar
              isOpen
              isFullscreen
              isFileTreeVisible={false}
              onToggle={onToggleWebPreview}
              onToggleFileTree={() => setIsFileTreeVisible((prev) => !prev)}
              url={webPreviewUrl}
              onUrlChange={onWebPreviewUrlChange}
              onSelectElement={onSelectPreviewElement}
            />
          ) : isPlanMode ? (
            <div className="flex h-full min-h-0 w-full flex-col overflow-hidden">
              <PlanRichTextEditor
                value={planEditContent}
                onChange={setPlanEditContent}
                autoFocus
                title={planData?.title || '计划方案草案'}
                onAnnotationsChange={(annotations) => {
                  planAnnotationsRef.current = annotations;
                  onPlanAnnotationsChange?.(annotations);
                }}
                onSave={() => {
                  onPlanSave?.(planEditContent, planAnnotationsRef.current);
                }}
                onSubmit={() => {
                  onSubmitPlan?.(planEditContent, planAnnotationsRef.current);
                }}
                onClose={onClosePlan}
                isSaving={isSaving}
                isDarkMode={isDarkMode}
              />
            </div>
          ) : (
            <>
              <div className="flex flex-1 min-w-0 min-h-0 flex-col overflow-hidden">
                <div className="flex items-center justify-between border-b bg-muted/30 px-3 py-2 shrink-0">
                  <div className="flex min-w-0 items-center gap-2 text-muted-foreground font-mono text-xs">
                    <FileCode className="w-3.5 h-3.5 shrink-0" />
                    <span className="truncate">{selectedFilePath || '未选择文件'}</span>
                  </div>

                  <div className="flex items-center gap-1">
                    <EditorTools
                      canEdit={hasSelectedFile}
                      isEditing={isEditing}
                      isSaving={isSaving}
                      isWebPreviewOpen={isWebPreviewOpen}
                      canOpenHtmlPreview={hasSelectedFile && isSelectedHtmlFile}
                      editorTargets={EDITORS}
                      onStartEdit={handleStartEdit}
                      onCancelEdit={handleCancelEdit}
                      onSave={() => void handleSave()}
                      onOpenInEditor={(command) => void openInEditor(command)}
                      onOpenHtmlPreview={handleOpenHtmlPreview}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      onClick={() => setIsEditorFullscreen((prev) => !prev)}
                      title={isEditorFullscreen ? '退出全屏' : '全屏编辑'}
                    >
                      {isEditorFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                    </Button>
                  </div>
                </div>

                <div className="flex-1 min-w-0 min-h-0 overflow-hidden">
                  {hasSelectedFile ? (
                    <Editor
                      height="100%"
                      language={getFileLanguage(selectedFilePath)}
                      value={isEditing ? editContent : selectedFileContent}
                      onChange={isEditing ? ((value) => setEditContent(value ?? '')) : undefined}
                      onMount={handleEditorMount}
                      theme={isDarkMode ? "vs-dark" : "vs"}
                      path={selectedFilePath}
                      options={{
                        readOnly: !isEditing,
                        minimap: { enabled: false },
                        fontSize: 13,
                        lineNumbers: 'on',
                        scrollBeyondLastLine: false,
                        automaticLayout: true,
                        padding: { top: 16 },
                        renderLineHighlight: isEditing ? 'line' : 'none',
                        overviewRulerBorder: false,
                        hideCursorInOverviewRuler: true,
                        overviewRulerLanes: 0,
                        scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 },
                        domReadOnly: !isEditing,
                      }}
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center text-muted-foreground">
                      <div className="space-y-2 text-center">
                        <FileCode className="mx-auto h-10 w-10 opacity-30" />
                        <p className="text-xs">展开右侧文件树以选择文件</p>
                        <div className="flex items-center justify-center gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            className="mt-2 gap-1.5 text-xs"
                            onClick={() => setIsFileTreeVisible(true)}
                          >
                            <PanelsTopLeft className="h-3.5 w-3.5" />
                            打开文件树
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="mt-2 gap-1.5 text-xs"
                            onClick={onToggleWebPreview}
                          >
                            <PanelsTopLeft className="h-3.5 w-3.5" />
                            打开浏览器预览
                          </Button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {shouldShowFileTree ? (
                <>
                  <ResizableHandle
                    side="right"
                    onResize={handleFileTreeResize}
                    onResizeStateChange={setIsFileTreeResizing}
                    className="border-l border-border/60 bg-background/40 hover:bg-primary/15"
                  />

                  <div
                    style={{
                      width: fileTreeWidth,
                      transition: isFileTreeResizing ? 'none' : 'width 0.2s cubic-bezier(0.25, 0.1, 0.25, 1)',
                    }}
                    className="flex shrink-0 flex-col overflow-hidden border-l bg-muted/10"
                  >
                    <div className="flex items-center border-b px-3 py-2">
                      <span className="flex-1 text-xs font-semibold text-muted-foreground">项目结构</span>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          onClick={() => void handleRefreshFileTree()}
                          disabled={isRefreshingFileTree}
                          title="刷新文件树"
                        >
                          <RefreshCw className={`h-3.5 w-3.5 ${isRefreshingFileTree ? 'animate-spin' : ''}`} />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          onClick={() => setIsFileTreeVisible(false)}
                          title="收起文件树"
                        >
                          <FolderTree className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                    <div className="flex-1 overflow-auto">
                      <div className="p-2">
                        {fileTree.length > 0 ? (
                          <FileTree
                            selectedPath={selectedFilePath}
                            onSelect={onLoadFile}
                            onFolderToggle={(path, expanded) => {
                              if (expanded) {
                                void onLoadDirectory?.(path);
                              }
                            }}
                          >
                            {renderFileTreeNodes(fileTree)}
                          </FileTree>
                        ) : (
                          <div className="py-4 text-center text-xs text-muted-foreground">暂无文件结构</div>
                        )}
                      </div>
                    </div>
                  </div>
                </>
              ) : null}

              <EditorSidebar
                isOpen={false}
                isFileTreeVisible={shouldShowFileTree}
                onToggle={onToggleWebPreview}
                onToggleFileTree={() => setIsFileTreeVisible((prev) => !prev)}
                url={webPreviewUrl}
                onUrlChange={onWebPreviewUrlChange}
                onSelectElement={onSelectPreviewElement}
              />

              {isEditorFullscreen && (
                <div className="fixed inset-0 z-50 flex flex-col bg-background">
                  <div className="flex items-center justify-between border-b bg-muted/30 px-4 py-2 shrink-0">
                    <div className="flex min-w-0 items-center gap-2 text-muted-foreground font-mono text-xs">
                      <FileCode className="w-3.5 h-3.5 shrink-0" />
                      <span className="truncate">{selectedFilePath || '未选择文件'}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <EditorTools
                        canEdit={hasSelectedFile}
                        isEditing={isEditing}
                        isSaving={isSaving}
                        isWebPreviewOpen={isWebPreviewOpen}
                        canOpenHtmlPreview={hasSelectedFile && isSelectedHtmlFile}
                        editorTargets={EDITORS}
                        onStartEdit={handleStartEdit}
                        onCancelEdit={handleCancelEdit}
                        onSave={() => void handleSave()}
                        onOpenInEditor={(command) => void openInEditor(command)}
                        onOpenHtmlPreview={handleOpenHtmlPreview}
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => setIsEditorFullscreen(false)}
                        title="退出全屏"
                      >
                        <Minimize2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                  <div className="flex flex-1 min-h-0 overflow-hidden">
                    <div className="flex flex-1 min-w-0 min-h-0 overflow-hidden">
                      <Editor
                        height="100%"
                        language={getFileLanguage(selectedFilePath)}
                        value={isEditing ? editContent : selectedFileContent}
                        onChange={isEditing ? ((value) => setEditContent(value ?? '')) : undefined}
                        onMount={(editor, monaco) => handleEditorMount(editor, monaco, true)}
                        theme={isDarkMode ? "vs-dark" : "vs"}
                        path={`fullscreen-${selectedFilePath}`}
                        options={{
                          readOnly: !isEditing,
                          minimap: { enabled: false },
                          fontSize: 13,
                          lineNumbers: 'on',
                          scrollBeyondLastLine: false,
                          automaticLayout: true,
                          padding: { top: 16 },
                          renderLineHighlight: isEditing ? 'line' : 'none',
                          overviewRulerBorder: false,
                          hideCursorInOverviewRuler: true,
                          overviewRulerLanes: 0,
                          scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 },
                          domReadOnly: !isEditing,
                        }}
                      />
                    </div>

                    {shouldShowFileTree && (
                      <>
                        <ResizableHandle
                          side="right"
                          onResize={handleFileTreeResize}
                          onResizeStateChange={setIsFileTreeResizing}
                          className="border-l border-border/60 bg-background/40 hover:bg-primary/15"
                        />
                        <div
                          style={{
                            width: fileTreeWidth,
                            transition: isFileTreeResizing ? 'none' : 'width 0.2s cubic-bezier(0.25, 0.1, 0.25, 1)',
                          }}
                          className="flex shrink-0 flex-col overflow-hidden border-l bg-muted/10"
                        >
                          <div className="flex items-center border-b px-3 py-2">
                            <span className="flex-1 text-xs font-semibold text-muted-foreground">项目结构</span>
                            <div className="flex items-center gap-1">
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                onClick={() => void handleRefreshFileTree()}
                                disabled={isRefreshingFileTree}
                                title="刷新文件树"
                              >
                                <RefreshCw className={`h-3.5 w-3.5 ${isRefreshingFileTree ? 'animate-spin' : ''}`} />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                onClick={() => setIsFileTreeVisible(false)}
                                title="收起文件树"
                              >
                                <FolderTree className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </div>
                          <div className="flex-1 overflow-auto">
                            <div className="p-2">
                              {fileTree.length > 0 ? (
                                <FileTree
                                  selectedPath={selectedFilePath}
                                  onSelect={onLoadFile}
                                  onFolderToggle={(path, expanded) => {
                                    if (expanded) {
                                      void onLoadDirectory?.(path);
                                    }
                                  }}
                                >
                                  {renderFileTreeNodes(fileTree)}
                                </FileTree>
                              ) : (
                                <div className="py-4 text-center text-xs text-muted-foreground">暂无文件结构</div>
                              )}
                            </div>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <Dialog open={Boolean(editorLaunchError)} onOpenChange={(open) => !open && setEditorLaunchError(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>无法打开外部编辑器</DialogTitle>
            <DialogDescription>当前环境没有成功启动你选择的编辑器。</DialogDescription>
          </DialogHeader>
          <Alert variant="destructive">
            <CircleAlert className="size-4" />
            <AlertTitle>启动失败</AlertTitle>
            <AlertDescription>
              {editorLaunchError ?? '未安装该应用或未将其添加到 PATH 中。'}
            </AlertDescription>
          </Alert>
        </DialogContent>
      </Dialog>
    </>
  );
}
