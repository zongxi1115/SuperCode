import Editor from '@monaco-editor/react';
import { FileTree } from '@/components/ai-elements/file-tree';
import { EditorSidebar } from '@/components/app/editor-sidebar';
import { PlanRichTextEditor } from '@/components/app/plan-rich-text-editor';
import { EditorTools, type EditorTarget } from '@/components/app/editor-tools';
import { renderFileTreeNodes } from '@/components/app/file-tree-renderers';
import { ResizableHandle } from '@/components/app/resizable-handle';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { getFileLanguage } from '@/lib/app-utils';
import type { FileTreeNode } from '@/lib/app-types';
import { SiJetbrains, SiSublimetext, SiVscodium, SiZedindustries } from '@icons-pack/react-simple-icons';
import { motion } from 'motion/react';
import { CircleAlert, FileCode, FolderTree, PanelsTopLeft, SquareTerminal } from 'lucide-react';
import type { editor as MonacoEditor } from 'monaco-editor';
import { useCallback, useEffect, useRef, useState } from 'react';

export type PlanData = {
  title: string;
  markdown: string;
};

type EditorPanelProps = {
  fileTree: FileTreeNode[];
  selectedFilePath: string;
  selectedFileContent: string;
  onLoadFile: (path: string) => void | Promise<void>;
  onSaveFile?: (path: string, content: string) => void | Promise<void>;
  sessionId: string | null;
  isWebPreviewOpen: boolean;
  onToggleWebPreview: () => void;
  webPreviewUrl: string;
  onWebPreviewUrlChange: (url: string) => void;
  onSelectPreviewElement?: (html: string, selector: string) => void;
  planData?: PlanData | null;
  onPlanSave?: (markdown: string) => void;
  onClosePlan?: () => void;
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

export function EditorPanel({
  fileTree,
  selectedFilePath,
  selectedFileContent,
  onLoadFile,
  onSaveFile,
  sessionId,
  isWebPreviewOpen,
  onToggleWebPreview,
  webPreviewUrl,
  onWebPreviewUrlChange,
  onSelectPreviewElement,
  planData,
  onPlanSave,
  onClosePlan,
}: EditorPanelProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [fileTreeWidth, setFileTreeWidth] = useState(DEFAULT_FILE_TREE_WIDTH);
  const [isFileTreeVisible, setIsFileTreeVisible] = useState(true);
  const [editorLaunchError, setEditorLaunchError] = useState<string | null>(null);
  const [planEditContent, setPlanEditContent] = useState('');
  const monacoRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null);
  const isEditingRef = useRef(false);
  const editContentRef = useRef('');
  const lastPlanSyncRef = useRef<string | null>(null);

  const isPlanMode = Boolean(planData);

  useEffect(() => { isEditingRef.current = isEditing; }, [isEditing]);
  useEffect(() => { editContentRef.current = editContent; }, [editContent]);

  useEffect(() => {
    setIsEditing(false);
    setEditContent('');
  }, [selectedFilePath]);

  useEffect(() => {
    if (!planData) {
      lastPlanSyncRef.current = null;
      setPlanEditContent('');
      return;
    }

    if (lastPlanSyncRef.current === planData.markdown) {
      return;
    }

    lastPlanSyncRef.current = planData.markdown;
    setPlanEditContent((current) => (current === planData.markdown ? current : planData.markdown));
  }, [planData?.markdown]);

  useEffect(() => {
    if (isWebPreviewOpen) {
      setIsFileTreeVisible(false);
    }
  }, [isWebPreviewOpen]);

  const handleStartEdit = useCallback(() => {
    if (!selectedFilePath) return;
    setEditContent(selectedFileContent);
    setIsEditing(true);
    setTimeout(() => monacoRef.current?.focus(), 50);
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
        await onSaveFile(selectedFilePath, editContent);
      } else {
        const query = new URLSearchParams({
          session_id: sessionId,
          path: selectedFilePath,
        });
        const res = await fetch(`http://localhost:8000/api/files?${query.toString()}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: editContent }),
        });
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.error || '保存失败');
        }
      }
      setIsEditing(false);
      setEditContent('');
      void onLoadFile(selectedFilePath);
    } catch (error) {
      console.error(error);
    } finally {
      setIsSaving(false);
    }
  }, [editContent, onLoadFile, onSaveFile, selectedFilePath, sessionId]);

  useEffect(() => {
    if (!isEditing && !isPlanMode) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (isPlanMode) {
          onPlanSave?.(planEditContent);
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isEditing, isPlanMode, onPlanSave, planEditContent]);

  const handleFileTreeResize = useCallback((delta: number) => {
    setFileTreeWidth((prev) => Math.min(Math.max(prev + delta, MIN_FILE_TREE_WIDTH), MAX_FILE_TREE_WIDTH));
  }, []);

  const handleSaveRef = useRef(handleSave);
  useEffect(() => { handleSaveRef.current = handleSave; }, [handleSave]);

  const handleEditorMount = useCallback((editor: MonacoEditor.IStandaloneCodeEditor) => {
    monacoRef.current = editor;
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      if (isEditingRef.current) {
        void handleSaveRef.current();
      }
    });
  }, []);

  const openInEditor = useCallback(async (command: string) => {
    if (!sessionId || !selectedFilePath) return;

    try {
      const res = await fetch('http://localhost:8000/api/files/open', {
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
    }
  }, [selectedFilePath, sessionId]);

  const hasSelectedFile = Boolean(selectedFilePath);
  const shouldShowFileTree = !isWebPreviewOpen && isFileTreeVisible;

  return (
    <>
      <div className="flex-1 min-h-0 p-2">
        <div className="flex h-full min-h-0 overflow-hidden rounded-xl border bg-card/70 shadow-sm">
          <div className="flex flex-1 min-w-0 min-h-0 p-2">
            <div className="flex h-full min-h-0 w-full overflow-hidden rounded-lg border bg-background">
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
                  <div className="flex items-center justify-between border-b bg-muted/30 px-3 py-2 shrink-0">
                    <div className="flex min-w-0 items-center gap-2 text-muted-foreground text-xs">
                      <FileCode className="w-3.5 h-3.5 shrink-0" />
                      <span className="truncate font-medium">{planData?.title || '计划草案'}</span>
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">计划</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Button size="sm" variant="ghost" className="h-7 gap-1.5 text-xs" onClick={onClosePlan}>
                        返回编辑器
                      </Button>
                    </div>
                  </div>

                  <div className="flex-1 min-h-0 overflow-hidden">
                    <PlanRichTextEditor
                      value={planEditContent}
                      onChange={setPlanEditContent}
                      autoFocus
                    />
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex flex-1 min-w-0 min-h-0 flex-col overflow-hidden">
                    <div className="flex items-center justify-between border-b bg-muted/30 px-3 py-2 shrink-0">
                      <div className="flex min-w-0 items-center gap-2 text-muted-foreground font-mono text-xs">
                        <FileCode className="w-3.5 h-3.5 shrink-0" />
                        <span className="truncate">{selectedFilePath || '未选择文件'}</span>
                      </div>

                      <EditorTools
                        canEdit={hasSelectedFile}
                        isEditing={isEditing}
                        isSaving={isSaving}
                        isWebPreviewOpen={isWebPreviewOpen}
                        editorTargets={EDITORS}
                        onStartEdit={handleStartEdit}
                        onCancelEdit={handleCancelEdit}
                        onSave={() => void handleSave()}
                        onOpenInEditor={(command) => void openInEditor(command)}
                        onToggleWebPreview={onToggleWebPreview}
                      />
                    </div>

                    <div className="flex-1 min-w-0 min-h-0 overflow-hidden">
                      {hasSelectedFile ? (
                        <Editor
                          height="100%"
                          language={getFileLanguage(selectedFilePath)}
                          value={isEditing ? editContent : selectedFileContent}
                          onChange={isEditing ? ((v) => setEditContent(v ?? '')) : undefined}
                          onMount={handleEditorMount}
                          theme="vs"
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
                        className="border-l border-border/60 bg-background/40 hover:bg-primary/15"
                      />

                      <motion.div
                        animate={{ width: fileTreeWidth }}
                        transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
                        className="flex shrink-0 flex-col overflow-hidden border-l bg-muted/10"
                      >
                        <div className="flex items-center border-b px-3 py-2">
                          <span className="flex-1 text-xs font-semibold text-muted-foreground">项目结构</span>
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
                        <div className="flex-1 overflow-auto">
                          <div className="p-2">
                            {fileTree.length > 0 ? (
                              <FileTree selectedPath={selectedFilePath} onSelect={onLoadFile}>
                                {renderFileTreeNodes(fileTree)}
                              </FileTree>
                            ) : (
                              <div className="py-4 text-center text-xs text-muted-foreground">暂无文件结构</div>
                            )}
                          </div>
                        </div>
                      </motion.div>
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
                </>
              )}
            </div>
          </div>
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
