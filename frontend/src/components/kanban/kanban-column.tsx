import React from 'react';
import type { KanbanColumn as KanbanColumnType, KanbanCard as KanbanCardType, CardStatus } from '@/lib/kanban-types';
import { KanbanCard } from './kanban-card';
import { cn } from '@/lib/utils';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';

interface KanbanColumnProps {
  column: KanbanColumnType;
  cards: KanbanCardType[];
  onCardClick: (card: KanbanCardType) => void;
  onDragStart: (e: React.DragEvent<HTMLDivElement>, cardId: string) => void;
  onDrop: (e: React.DragEvent<HTMLDivElement>, status: CardStatus) => void;
  onDragOver: (e: React.DragEvent<HTMLDivElement>) => void;
  onDragLeave: (e: React.DragEvent<HTMLDivElement>) => void;
}

export function KanbanColumn({
  column,
  cards,
  onCardClick,
  onDragStart,
  onDrop,
  onDragOver,
  onDragLeave
}: KanbanColumnProps) {
  const [isDragOver, setIsDragOver] = React.useState(false);

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    onDragOver(e);
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    onDragLeave(e);
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    onDrop(e, column.name);
    setIsDragOver(false);
  };

  return (
    <div 
      className={cn(
        "flex h-full w-80 flex-shrink-0 flex-col rounded-xl bg-muted/30 border border-transparent transition-colors",
        isDragOver && "border-primary/50 bg-muted/50"
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="flex items-center justify-between p-3">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-sm">{column.name}</h3>
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground">
            {cards.length}
          </span>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-foreground">
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      
      <ScrollArea className="flex-1 px-3">
        <div className="flex flex-col gap-3 pb-3 min-h-[100px]">
          {cards.map((card) => (
            <KanbanCard 
              key={card.id} 
              card={card} 
              onClick={onCardClick} 
              onDragStart={onDragStart} 
            />
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
