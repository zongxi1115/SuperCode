import React, { useEffect, useState } from 'react';
import type { KanbanCard, CardStatus, Priority } from '@/lib/kanban-types';
import { CARD_STATUS_LABELS, PRIORITY_LABELS } from '@/lib/kanban-types';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Maximize2, Minimize2, Sparkles, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { FileTreeNode } from '@/lib/app-types';
import { KanbanDescriptionEditor } from './kanban-description-editor';

interface KanbanCardDrawerProps {
  card: KanbanCard | null;
  isOpen: boolean;
  isSaving?: boolean;
  fileTree?: FileTreeNode[];
  onClose: () => void;
  onSave: (card: KanbanCard) => void;
  onDelete: (cardId: string) => void;
  onSendToAi?: (card: KanbanCard) => void;
}

export function KanbanCardDrawer({
  card,
  isOpen,
  isSaving = false,
  fileTree = [],
  onClose,
  onSave,
  onDelete,
  onSendToAi,
}: KanbanCardDrawerProps) {
  if (!card) return null;

  return (
    <KanbanCardDrawerContent
      key={card.id}
      card={card}
      isOpen={isOpen}
      isSaving={isSaving}
      fileTree={fileTree}
      onClose={onClose}
      onSave={onSave}
      onDelete={onDelete}
      onSendToAi={onSendToAi}
    />
  );
}

function KanbanCardDrawerContent({
  card,
  isOpen,
  isSaving,
  fileTree,
  onClose,
  onSave,
  onDelete,
  onSendToAi,
}: {
  card: KanbanCard;
  isOpen: boolean;
  isSaving: boolean;
  fileTree: FileTreeNode[];
  onClose: () => void;
  onSave: (card: KanbanCard) => void;
  onDelete: (cardId: string) => void;
  onSendToAi?: (card: KanbanCard) => void;
}) {
  const [editedCard, setEditedCard] = useState<KanbanCard>(() => ({ ...card }));
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    setEditedCard({ ...card });
  }, [card]);

  const handleClose = () => {
    setIsExpanded(false);
    onClose();
  };

  const handleSave = () => {
    onSave({
      ...editedCard,
      updatedAt: new Date().toISOString()
    });
  };

  const handleSendToAi = () => {
    onSendToAi?.({
      ...editedCard,
      updatedAt: new Date().toISOString(),
    });
  };

  return (
    <Sheet
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) {
          handleClose();
        }
      }}
    >
      <SheetContent
        className={cn(
          "flex flex-col gap-6 overflow-hidden",
          isExpanded
            ? "left-4 right-4 top-4 bottom-4 h-auto w-auto rounded-lg border sm:max-w-none"
            : "sm:max-w-[425px]",
        )}
      >
        <SheetHeader className="pr-10">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <SheetTitle>编辑卡片</SheetTitle>
              <SheetDescription>
                修改卡片内容、状态和优先级，保存后会同步到当前工作区看板。
              </SheetDescription>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0"
              onClick={() => setIsExpanded((value) => !value)}
              aria-label={isExpanded ? '还原侧边栏' : '全屏编辑'}
              title={isExpanded ? '还原侧边栏' : '全屏编辑'}
            >
              {isExpanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </Button>
          </div>
        </SheetHeader>
        
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
          <div className="grid gap-2">
            <Label htmlFor="title">标题</Label>
            <Input 
              id="title" 
              value={editedCard.title} 
              onChange={(e) => setEditedCard({ ...editedCard, title: e.target.value })}
            />
          </div>
          
          <div className={cn("grid gap-2", isExpanded && "min-h-0 flex-1")}>
            <Label htmlFor="description">描述</Label>
            <KanbanDescriptionEditor
              value={editedCard.description}
              fileTree={fileTree}
              isExpanded={isExpanded}
              onChange={(description) => {
                setEditedCard((currentCard) => currentCard ? { ...currentCard, description } : currentCard);
              }}
              className={isExpanded ? "flex-1" : "min-h-[220px]"}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="status">状态</Label>
            <Select 
              value={editedCard.status} 
              onValueChange={(val: CardStatus) => setEditedCard({ ...editedCard, status: val })}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择状态" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Backlog">{CARD_STATUS_LABELS.Backlog}</SelectItem>
                <SelectItem value="Todo">{CARD_STATUS_LABELS.Todo}</SelectItem>
                <SelectItem value="In Progress">{CARD_STATUS_LABELS['In Progress']}</SelectItem>
                <SelectItem value="Done">{CARD_STATUS_LABELS.Done}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="priority">优先级</Label>
            <Select 
              value={editedCard.priority} 
              onValueChange={(val: Priority) => setEditedCard({ ...editedCard, priority: val })}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择优先级" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{PRIORITY_LABELS.none}</SelectItem>
                <SelectItem value="low">{PRIORITY_LABELS.low}</SelectItem>
                <SelectItem value="medium">{PRIORITY_LABELS.medium}</SelectItem>
                <SelectItem value="high">{PRIORITY_LABELS.high}</SelectItem>
                <SelectItem value="urgent">{PRIORITY_LABELS.urgent}</SelectItem>
              </SelectContent>
            </Select>
          </div>


        </div>

        <div className="mt-auto flex items-center justify-between gap-2 pt-4 border-t">
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              className="gap-1.5"
              onClick={handleSendToAi}
              disabled={!onSendToAi || isSaving}
            >
              <Sparkles className="h-3.5 w-3.5" />
              交给 AI
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="gap-1.5 text-destructive hover:text-destructive"
              onClick={() => onDelete(card.id)}
              disabled={isSaving}
            >
              <Trash2 className="h-3.5 w-3.5" />
              删除
            </Button>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={handleClose}>取消</Button>
            <Button onClick={handleSave} disabled={isSaving}>{isSaving ? '保存中...' : '保存更改'}</Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
