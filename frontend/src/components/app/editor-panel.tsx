import { CodeBlock } from '@/components/ai-elements/code-block';
import { FileTree } from '@/components/ai-elements/file-tree';
import { renderFileTreeNodes } from '@/components/app/file-tree-renderers';
import { Button } from '@/components/ui/button';
import { getFileLanguage } from '@/lib/app-utils';
import type { FileTreeNode } from '@/lib/app-types';
import { AnimatePresence, motion } from 'motion/react';
import { FileCode, PanelLeftClose, PanelLeftOpen, Pencil, Save, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

type EditorPanelProps = {
  fileTree: FileTreeNode[];
  selectedFilePath: string;
  selectedFileContent: string;
  isFileTreeCollapsed: boolean;
  onToggleFileTree: () => void;
  onLoadFile: (path: string) => void | Promise<void>;
  onSaveFile?: (path: string, content: string) => void | Promise<void>;
  sessionId: string | null;
};

export function EditorPanel({
  fileTree,
  selectedFilePath,
  selectedFileContent,
  isFileTreeCollapsed,
  onToggleFileTree,
  onLoadFile,
  onSaveFile,
  sessionId,
}: EditorPanelProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setIsEditing(false);
    setEditContent('');
  }, [selectedFilePath]);

  const handleStartEdit = useCallback(() => {
    setEditContent(selectedFileContent);
    setIsEditing(true);
    setTimeout(() => textareaRef.current?.focus(), 50);
  }, [selectedFileContent]);

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
  }, [sessionId, selectedFilePath, editContent, onSaveFile, onLoadFile]);

  useEffect(() => {
    if (!isEditing) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        void handleSave();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isEditing, handleSave]);

  const lineCount = isEditing
    ? editContent.split('\n').length
    : selectedFileContent.split('\n').length;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex-1 overflow-hidden flex min-h-0">
        <motion.div
          animate={{ width: isFileTreeCollapsed ? 40 : 200 }}
          transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
          className="border-r bg-muted/10 flex flex-col flex-shrink-0 overflow-hidden"
        >
          <div className="flex items-center justify-center px-1 py-1.5 border-b h-8">
            {!isFileTreeCollapsed && <span className="text-xs font-semibold text-muted-foreground flex-1 ml-1">项目结构</span>}
            <Button variant="ghost" size="icon" onClick={onToggleFileTree} className="h-6 w-6 shrink-0">
              {isFileTreeCollapsed ? <PanelLeftOpen className="w-3.5 h-3.5" /> : <PanelLeftClose className="w-3.5 h-3.5" />}
            </Button>
          </div>
          <AnimatePresence mode="wait">
            {!isFileTreeCollapsed && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="flex-1 overflow-auto"
              >
                <div className="p-2">
                  {fileTree.length > 0 ? (
                    <FileTree selectedPath={selectedFilePath} onSelect={onLoadFile}>
                      {renderFileTreeNodes(fileTree)}
                    </FileTree>
                  ) : (
                    <div className="text-muted-foreground text-center py-4 text-xs">暂无文件结构</div>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>

        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {selectedFilePath && selectedFileContent ? (
            <>
              <div className="flex items-center justify-between px-3 py-1.5 border-b bg-muted/30 shrink-0">
                <div className="flex items-center gap-2 text-muted-foreground font-mono text-xs truncate">
                  <FileCode className="w-3.5 h-3.5 shrink-0" />
                  <span className="truncate">{selectedFilePath}</span>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {isEditing ? (
                    <>
                      <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleCancelEdit} title="取消编辑">
                        <X className="w-3.5 h-3.5" />
                      </Button>
                      <Button variant="default" size="icon" className="h-6 w-6" onClick={handleSave} disabled={isSaving} title="保存 (Ctrl+S)">
                        <Save className="w-3.5 h-3.5" />
                      </Button>
                    </>
                  ) : (
                    <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleStartEdit} title="编辑文件">
                      <Pencil className="w-3.5 h-3.5" />
                    </Button>
                  )}
                </div>
              </div>

              {isEditing ? (
                <div className="flex-1 overflow-auto flex min-h-0">
                  <div className="py-3 pr-0 pl-3 text-right select-none font-mono text-xs leading-[20px] text-muted-foreground/40 bg-muted/10 border-r shrink-0">
                    {Array.from({ length: lineCount }, (_, i) => (
                      <div key={i}>{i + 1}</div>
                    ))}
                  </div>
                  <textarea
                    ref={textareaRef}
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    className="flex-1 p-3 font-mono text-xs leading-[20px] resize-none bg-background outline-none min-w-0"
                    spellCheck={false}
                  />
                </div>
              ) : (
                <div className="flex-1 overflow-auto">
                  <CodeBlock
                    code={selectedFileContent}
                    language={getFileLanguage(selectedFilePath) as 'tsx'}
                    showLineNumbers
                    className="w-full text-sm border-0 rounded-none"
                  />
                </div>
              )}
            </>
          ) : (
            <div className="h-full flex items-center justify-center text-muted-foreground">
              <div className="text-center space-y-2">
                <FileCode className="w-10 h-10 mx-auto opacity-30" />
                <p className="text-xs">选择左侧文件以预览代码</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
