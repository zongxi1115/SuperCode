import type { KanbanAiState, KanbanCard as KanbanCardType } from '@/lib/kanban-types';
import { PRIORITY_LABELS } from '@/lib/kanban-types';
import { cn } from '@/lib/utils';
import { CheckCircle2, CircleDashed, Clock, LoaderCircle, TriangleAlert } from 'lucide-react';
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

  const getAiStatusMeta = (aiState?: KanbanAiState | null) => {
    switch (aiState?.status) {
      case 'completed':
        return {
          label: '已完成',
          className: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-600',
          icon: <CheckCircle2 className="h-3 w-3" />,
        };
      case 'error':
        return {
          label: '失败',
          className: 'border-destructive/20 bg-destructive/10 text-destructive',
          icon: <TriangleAlert className="h-3 w-3" />,
        };
      case 'queued':
        return {
          label: '排队中',
          className: 'border-sky-500/20 bg-sky-500/10 text-sky-600',
          icon: <CircleDashed className="h-3 w-3" />,
        };
      case 'running':
        return {
          label: '进行中',
          className: 'border-amber-500/20 bg-amber-500/10 text-amber-600',
          icon: <LoaderCircle className="h-3 w-3 animate-spin" />,
        };
      default:
        return null;
    }
  };

  const aiStatusMeta = getAiStatusMeta(card.aiState);
  const aiProgress = card.aiState?.progress;
  const aiStepText = card.aiState?.activeStepTitle || card.aiState?.lastMessage || '';

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
        {aiStatusMeta ? (
          <Badge variant="outline" className={cn('h-5 gap-1 px-1.5 text-[10px]', aiStatusMeta.className)}>
            {aiStatusMeta.icon}
            {aiStatusMeta.label}
          </Badge>
        ) : null}
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

      {card.aiState ? (
        <div className="rounded-md border border-border/50 bg-muted/40 px-2 py-1.5">
          {aiProgress ? (
            <div className="text-[10px] font-medium text-muted-foreground">
              进度 {aiProgress.completed}/{aiProgress.total}
            </div>
          ) : null}
          {aiStepText ? (
            <div className="mt-0.5 line-clamp-2 text-[11px] text-foreground/80">
              {aiStepText}
            </div>
          ) : null}
        </div>
      ) : null}
      
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
