import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import type { ReactNode } from 'react';
import { Pencil, Save, SquareArrowOutUpRight, X, PanelsTopLeft } from 'lucide-react';

export type EditorTarget = {
  name: string;
  command: string;
  icon: ReactNode;
};

type EditorToolsProps = {
  canEdit: boolean;
  isEditing: boolean;
  isSaving: boolean;
  isWebPreviewOpen: boolean;
  editorTargets: EditorTarget[];
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSave: () => void;
  onOpenInEditor: (command: string) => void;
  onToggleWebPreview: () => void;
};

export function EditorTools({
  canEdit,
  isEditing,
  isSaving,
  isWebPreviewOpen,
  editorTargets,
  onStartEdit,
  onCancelEdit,
  onSave,
  onOpenInEditor,
  onToggleWebPreview,
}: EditorToolsProps) {
  return (
    <div className="flex items-center gap-1 shrink-0">
      {isEditing ? (
        <>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onCancelEdit}>
                  <X className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>取消编辑</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="default" size="icon" className="h-7 w-7" onClick={onSave} disabled={isSaving}>
                  <Save className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>保存 (Ctrl+S)</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </>
      ) : (
        <>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onStartEdit} disabled={!canEdit}>
                  <Pencil className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>编辑文件</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                disabled={!canEdit}
                title="在编辑器中打开"
              >
                <SquareArrowOutUpRight className="w-3.5 h-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {editorTargets.map((editor) => (
                <DropdownMenuItem key={editor.command} onClick={() => onOpenInEditor(editor.command)}>
                  <span className="mr-2 flex h-4 w-4 items-center justify-center">
                    {editor.icon}
                  </span>
                  {editor.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      )}

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={isWebPreviewOpen ? 'secondary' : 'ghost'}
              size="icon"
              onClick={onToggleWebPreview}
              className="h-7 w-7"
            >
              <PanelsTopLeft className="w-3.5 h-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>{isWebPreviewOpen ? '关闭浏览器预览' : '打开浏览器预览'}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}
