import React, { useEffect, useState } from 'react';
import type { KanbanAiState, KanbanCard, CardStatus, Priority } from '@/lib/kanban-types';
import { CARD_STATUS_LABELS, PRIORITY_LABELS } from '@/lib/kanban-types';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { CheckCircle2, LoaderCircle, Maximize2, Minimize2, Sparkles, TriangleAlert, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { FileTreeNode } from '@/lib/app-types';
import { KanbanDescriptionEditor } from './kanban-description-editor';
import { Badge } from '@/components/ui/badge';

interface KanbanCardDrawerProps {
  card: KanbanCard | null;
  isOpen: boolean;
  isSaving?: boolean;
  fileTree?: FileTreeNode[];
  onClose: () => void;
  onSave: (card: KanbanCard) => void;
  onDelete: (cardId: string) => void;
  onSendToAi?: (card: KanbanCard) => Promise<void> | void;
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
  onSendToAi?: (card: KanbanCard) => Promise<void> | void;
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
    void onSendToAi?.({
      ...editedCard,
      updatedAt: new Date().toISOString(),
    });
  };

  const getAiStatusMeta = (aiState?: KanbanAiState | null) => {
    switch (aiState?.status) {
      case 'completed':
        return {
          label: '已完成',
          icon: <CheckCircle2 className="h-3.5 w-3.5" />,
          className: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-600',
        };
      case 'error':
        return {
          label: '失败',
          icon: <TriangleAlert className="h-3.5 w-3.5" />,
          className: 'border-destructive/20 bg-destructive/10 text-destructive',
        };
      case 'queued':
      case 'running':
        return {
          label: aiState.status === 'queued' ? '排队中' : '进行中',
          icon: <LoaderCircle className="h-3.5 w-3.5 animate-spin" />,
          className: 'border-amber-500/20 bg-amber-500/10 text-amber-600',
        };
      default:
        return null;
    }
  };

  const aiStatusMeta = getAiStatusMeta(editedCard.aiState);

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

          {editedCard.aiState ? (
            <div className="rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium">AI 任务状态</div>
                {aiStatusMeta ? (
                  <Badge variant="outline" className={cn('gap-1 border px-2 py-0.5 text-[11px]', aiStatusMeta.className)}>
                    {aiStatusMeta.icon}
                    {aiStatusMeta.label}
                  </Badge>
                ) : null}
              </div>
              {editedCard.aiState.progress ? (
                <div className="mt-2 text-xs text-muted-foreground">
                  进度 {editedCard.aiState.progress.completed}/{editedCard.aiState.progress.total}
                </div>
              ) : null}
              {editedCard.aiState.activeStepTitle ? (
                <div className="mt-1 text-sm text-foreground/90">
                  当前步骤：{editedCard.aiState.activeStepTitle}
                </div>
              ) : null}
              {editedCard.aiState.lastMessage ? (
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  {editedCard.aiState.lastMessage}
                </div>
              ) : null}
              {editedCard.aiState.planSteps && editedCard.aiState.planSteps.length > 0 ? (
                <div className="mt-3 space-y-2">
                  {editedCard.aiState.planSteps.map((step) => (
                    <div key={step.id} className="flex items-start gap-2 text-xs">
                      <div className={cn(
                        'mt-0.5 h-2.5 w-2.5 rounded-full',
                        step.status === 'completed' && 'bg-emerald-500',
                        step.status === 'running' && 'bg-amber-500',
                        step.status === 'error' && 'bg-destructive',
                        step.status === 'blocked' && 'bg-orange-500',
                        step.status === 'pending' && 'bg-muted-foreground/30',
                      )} />
                      <div className="min-w-0">
                        <div className="font-medium text-foreground/90">{step.title}</div>
                        <div className="text-muted-foreground">{step.description}</div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
              {editedCard.aiState.result ? (
                <div className="mt-3 rounded-md border bg-background/80 p-2 text-xs leading-5 text-foreground/80">
                  {editedCard.aiState.result}
                </div>
              ) : null}
              {editedCard.aiState.error ? (
                <div className="mt-3 rounded-md border border-destructive/20 bg-destructive/5 p-2 text-xs leading-5 text-destructive">
                  {editedCard.aiState.error}
                </div>
              ) : null}
            </div>
          ) : null}
          
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
