import React from 'react';
import type { KanbanCard as KanbanCardType } from '@/lib/kanban-types';
import { PRIORITY_LABELS } from '@/lib/kanban-types';
import { cn } from '@/lib/utils';
import { Clock } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

interface KanbanCardProps {
  card: KanbanCardType;
  onClick: (card: KanbanCardType) => void;
  onDragStart: (e: React.DragEvent<HTMLDivElement>, cardId: string) => void;
}

export function KanbanCard({ card, onClick, onDragStart }: KanbanCardProps) {
  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'urgent': return 'bg-red-500/10 text-red-500 border-red-500/20';
      case 'high': return 'bg-orange-500/10 text-orange-500 border-orange-500/20';
      case 'medium': return 'bg-yellow-500/10 text-yellow-600 border-yellow-500/20';
      case 'low': return 'bg-blue-500/10 text-blue-500 border-blue-500/20';
      default: return 'bg-gray-500/10 text-gray-500 border-gray-500/20';
    }
  };

  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, card.id)}
      onClick={() => onClick(card)}
      className={cn(
        "group relative flex cursor-grab flex-col gap-2 rounded-lg border bg-card p-3 shadow-sm transition-all hover:shadow-md active:cursor-grabbing",
        "border-border/50 hover:border-primary/50"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-sm font-medium leading-snug">{card.title}</h4>
      </div>
      
      {card.labels && card.labels.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {card.labels.map(label => (
            <Badge key={label} variant="secondary" className="px-1.5 py-0 text-[10px] h-4">
              {label}
            </Badge>
          ))}
        </div>
      )}
      
      <div className="mt-1 flex items-center justify-between text-muted-foreground">
        <div className="flex items-center gap-3">
          <Badge variant="outline" className={cn("px-1.5 py-0 text-[10px] h-4 font-normal", getPriorityColor(card.priority))}>
            {PRIORITY_LABELS[card.priority]}
          </Badge>
          {card.assignee && (
            <div className="flex items-center gap-1 text-[11px]" title={`负责人：${card.assignee}`}>
              <div className="flex h-4 w-4 items-center justify-center rounded-full bg-primary/10 text-[9px] font-medium text-primary">
                {card.assignee.charAt(0).toUpperCase()}
              </div>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <Clock className="h-3 w-3" />
        </div>
      </div>
    </div>
  );
}
