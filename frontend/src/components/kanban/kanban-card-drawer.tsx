import React, { useState, useEffect } from 'react';
import type { KanbanCard, CardStatus, Priority } from '@/lib/kanban-types';
import { CARD_STATUS_LABELS, PRIORITY_LABELS } from '@/lib/kanban-types';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';

interface KanbanCardDrawerProps {
  card: KanbanCard | null;
  isOpen: boolean;
  isSaving?: boolean;
  onClose: () => void;
  onSave: (card: KanbanCard) => void;
}

export function KanbanCardDrawer({ card, isOpen, isSaving = false, onClose, onSave }: KanbanCardDrawerProps) {
  const [editedCard, setEditedCard] = useState<KanbanCard | null>(null);

  useEffect(() => {
    if (card) {
      setEditedCard({ ...card });
    } else {
      setEditedCard(null);
    }
  }, [card, isOpen]);

  if (!editedCard) return null;

  const handleSave = () => {
    onSave({
      ...editedCard,
      updatedAt: new Date().toISOString()
    });
  };

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="sm:max-w-[425px] flex flex-col gap-6 overflow-y-auto">
        <SheetHeader>
          <SheetTitle>编辑卡片</SheetTitle>
          <SheetDescription>
            修改卡片内容、状态和优先级，保存后会同步到当前工作区看板。
          </SheetDescription>
        </SheetHeader>
        
        <div className="flex flex-col gap-4">
          <div className="grid gap-2">
            <Label htmlFor="title">标题</Label>
            <Input 
              id="title" 
              value={editedCard.title} 
              onChange={(e) => setEditedCard({ ...editedCard, title: e.target.value })}
            />
          </div>
          
          <div className="grid gap-2">
            <Label htmlFor="description">描述</Label>
            <Textarea 
              id="description" 
              value={editedCard.description} 
              onChange={(e) => setEditedCard({ ...editedCard, description: e.target.value })}
              className="min-h-[100px]"
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

          <div className="grid gap-2">
            <Label htmlFor="assignee">负责人</Label>
            <Input 
              id="assignee" 
              value={editedCard.assignee || ''} 
              onChange={(e) => setEditedCard({ ...editedCard, assignee: e.target.value })}
              placeholder="例如：Alice"
            />
          </div>
        </div>

        <div className="mt-auto flex items-center justify-end gap-2 pt-4 border-t">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSave} disabled={isSaving}>{isSaving ? '保存中...' : '保存更改'}</Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
