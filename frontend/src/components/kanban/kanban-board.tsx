import React, { useCallback, useEffect, useMemo, useState } from 'react';
import type {
  KanbanBoard as KanbanBoardType,
  KanbanAiState,
  KanbanCard,
  KanbanColumn as KanbanColumnType,
  CardStatus,
  Priority,
} from '@/lib/kanban-types';
import type { FileTreeNode } from '@/lib/app-types';
import { KanbanColumn } from './kanban-column';
import { KanbanCardDrawer } from './kanban-card-drawer';
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { Filter, LayoutDashboard, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { apiUrl } from '@/lib/api-client';

type KanbanBoardProps = {
  workspace: string;
  fileTree?: FileTreeNode[];
  onSendCardToAi?: (card: KanbanCard) => Promise<KanbanAiState | void> | KanbanAiState | void;
};

type BoardPayload = {
  board?: KanbanBoardType;
  boards?: KanbanBoardType[];
  card?: KanbanCard;
};

function workspaceKanbanUrl(workspace: string, suffix: string) {
  return apiUrl(`/api/workspaces/${encodeURIComponent(workspace)}/kanban${suffix}`);
}

async function readApiError(response: Response, fallback: string) {
  try {
    const data = await response.json();
    if (typeof data?.detail === 'string' && data.detail.trim()) {
      return data.detail;
    }
  } catch {
    // ignore malformed error responses
  }
  return fallback;
}

export function KanbanBoard({ workspace, fileTree = [], onSendCardToAi }: KanbanBoardProps) {
  const [board, setBoard] = useState<KanbanBoardType | null>(null);
  const [draggedCardId, setDraggedCardId] = useState<string | null>(null);
  const [isTrashDragOver, setIsTrashDragOver] = useState(false);
  const [selectedCard, setSelectedCard] = useState<KanbanCard | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [priorityFilter, setPriorityFilter] = useState<Priority | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loadBoard = useCallback(async () => {
    if (!workspace) return;

    setIsLoading(true);
    setErrorMessage(null);
    try {
      const listResponse = await fetch(workspaceKanbanUrl(workspace, '/boards'));
      if (!listResponse.ok) {
        throw new Error(await readApiError(listResponse, '读取看板失败'));
      }
      const listData = await listResponse.json() as BoardPayload;
      const existingBoard = listData.boards?.[0] ?? null;

      if (existingBoard) {
        const boardResponse = await fetch(workspaceKanbanUrl(workspace, `/boards/${existingBoard.id}`));
        if (!boardResponse.ok) {
          throw new Error(await readApiError(boardResponse, '读取看板详情失败'));
        }
        const boardData = await boardResponse.json() as BoardPayload;
        setBoard(boardData.board ?? null);
        return;
      }

      const createResponse = await fetch(workspaceKanbanUrl(workspace, '/boards'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: '默认看板' }),
      });
      if (!createResponse.ok) {
        throw new Error(await readApiError(createResponse, '创建默认看板失败'));
      }
      const createData = await createResponse.json() as BoardPayload;
      setBoard(createData.board ?? null);
    } catch (error) {
      console.error(error);
      setErrorMessage(error instanceof Error ? error.message : '加载看板失败');
      setBoard(null);
    } finally {
      setIsLoading(false);
    }
  }, [workspace]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadBoard();
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [loadBoard]);

  useEffect(() => {
    if (!board?.cards.some((card) => card.aiState?.status === 'running' || card.aiState?.status === 'queued')) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadBoard();
    }, 2500);
    return () => window.clearInterval(intervalId);
  }, [board?.cards, loadBoard]);

  useEffect(() => {
    const handleDragEnd = () => {
      document.querySelectorAll('[draggable]').forEach((el) => {
        (el as HTMLElement).style.opacity = '1';
      });
      setDraggedCardId(null);
    };
    window.addEventListener('dragend', handleDragEnd);
    return () => window.removeEventListener('dragend', handleDragEnd);
  }, []);

  const refreshSelectedCard = useCallback((nextBoard: KanbanBoardType, cardId?: string) => {
    const nextSelected = nextBoard.cards.find((card) => card.id === (cardId ?? selectedCard?.id)) ?? null;
    setSelectedCard(nextSelected);
  }, [selectedCard?.id]);

  const updateBoardFromPayload = useCallback((payload: BoardPayload, cardId?: string) => {
    if (payload.board) {
      setBoard(payload.board);
      refreshSelectedCard(payload.board, cardId);
    }
  }, [refreshSelectedCard]);

  const handleDragStart = (e: React.DragEvent<HTMLDivElement>, cardId: string) => {
    setDraggedCardId(cardId);
    e.dataTransfer.effectAllowed = 'move';
    setTimeout(() => {
      const el = e.target as HTMLElement;
      el.style.opacity = '0.5';
    }, 0);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
  };

  const handleDrop = async (e: React.DragEvent<HTMLDivElement>, targetStatus: CardStatus) => {
    e.preventDefault();
    if (!draggedCardId || !board) return;

    const targetColumn = board.columns.find((column) => column.name === targetStatus);
    if (!targetColumn) return;

    const nextCards = board.cards.map((card) =>
      card.id === draggedCardId
        ? { ...card, columnId: targetColumn.id, status: targetStatus, updatedAt: new Date().toISOString() }
        : card,
    );
    setBoard({ ...board, cards: nextCards });
    setDraggedCardId(null);

    try {
      const response = await fetch(workspaceKanbanUrl(workspace, `/cards/${draggedCardId}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ columnId: targetColumn.id }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response, '移动卡片失败'));
      }
      const payload = await response.json() as BoardPayload;
      updateBoardFromPayload(payload, draggedCardId);
    } catch (error) {
      console.error(error);
      setErrorMessage(error instanceof Error ? error.message : '移动卡片失败');
      void loadBoard();
    }
  };

  const handleCardClick = (card: KanbanCard) => {
    setSelectedCard(card);
    setIsDrawerOpen(true);
  };

  const applyCardUpdateLocally = useCallback((cardId: string, updater: (card: KanbanCard) => KanbanCard) => {
    setBoard((currentBoard) => {
      if (!currentBoard) return currentBoard;
      const nextCards = currentBoard.cards.map((card) => card.id === cardId ? updater(card) : card);
      const nextBoard = { ...currentBoard, cards: nextCards };
      refreshSelectedCard(nextBoard, cardId);
      return nextBoard;
    });
  }, [refreshSelectedCard]);

  const handleTrashDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setIsTrashDragOver(true);
  };

  const handleTrashDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsTrashDragOver(false);
  };

  const handleTrashDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsTrashDragOver(false);
    if (!draggedCardId || !board) return;
    const cardId = draggedCardId;
    setDraggedCardId(null);
    void handleDeleteCard(cardId);
  };

  const handleSaveCard = async (updatedCard: KanbanCard) => {
    if (!board) return;

    setIsSaving(true);
    setErrorMessage(null);
    try {
      const response = await fetch(workspaceKanbanUrl(workspace, `/cards/${updatedCard.id}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: updatedCard.title,
          description: updatedCard.description,
          priority: updatedCard.priority,
          labels: updatedCard.labels,
          assignee: updatedCard.assignee,
          status: updatedCard.status,
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response, '保存卡片失败'));
      }
      const payload = await response.json() as BoardPayload;
      updateBoardFromPayload(payload, updatedCard.id);
      setIsDrawerOpen(false);
    } catch (error) {
      console.error(error);
      setErrorMessage(error instanceof Error ? error.message : '保存卡片失败');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteCard = async (cardId: string) => {
    if (!board) return;

    setIsSaving(true);
    setErrorMessage(null);
    try {
      const response = await fetch(workspaceKanbanUrl(workspace, `/cards/${cardId}`), {
        method: 'DELETE',
      });
      if (!response.ok) {
        throw new Error(await readApiError(response, '删除卡片失败'));
      }
      setBoard({ ...board, cards: board.cards.filter((card) => card.id !== cardId) });
      setIsDrawerOpen(false);
      setSelectedCard(null);
    } catch (error) {
      console.error(error);
      setErrorMessage(error instanceof Error ? error.message : '删除卡片失败');
    } finally {
      setIsSaving(false);
    }
  };

  const handleCreateCard = async (column?: KanbanColumnType) => {
    if (!board || board.columns.length === 0) return;

    const targetColumn = column ?? board.columns[0];
    setIsSaving(true);
    setErrorMessage(null);
    try {
      const response = await fetch(workspaceKanbanUrl(workspace, '/cards'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          boardId: board.id,
          columnId: targetColumn.id,
          title: '新卡片',
          description: '',
          priority: 'none',
          labels: [],
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response, '创建卡片失败'));
      }
      const payload = await response.json() as BoardPayload;
      updateBoardFromPayload(payload, payload.card?.id);
      if (payload.card) {
        setSelectedCard(payload.card);
        setIsDrawerOpen(true);
      }
    } catch (error) {
      console.error(error);
      setErrorMessage(error instanceof Error ? error.message : '创建卡片失败');
    } finally {
      setIsSaving(false);
    }
  };

  const filteredCards = useMemo(
    () =>
      board?.cards.filter((card) => {
        if (priorityFilter !== 'all' && card.priority !== priorityFilter) return false;
        if (searchQuery.trim()) {
          const q = searchQuery.trim().toLowerCase();
          return (
            card.title.toLowerCase().includes(q) ||
            card.description.toLowerCase().includes(q)
          );
        }
        return true;
      }) ?? [],
    [board?.cards, priorityFilter, searchQuery],
  );

  if (isLoading && !board) {
    return <div className="flex h-full items-center justify-center p-8 text-muted-foreground">正在加载看板...</div>;
  }

  if (!board) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-muted-foreground">
        <div className="space-y-3 text-center">
          <div>{errorMessage ?? '暂无可用看板'}</div>
          <Button size="sm" variant="outline" onClick={() => void loadBoard()}>
            <RefreshCw className="h-3.5 w-3.5" />
            重试
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col bg-background">
      <div className="flex h-14 shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2 font-semibold">
          <LayoutDashboard className="h-5 w-5 text-primary" />
          <span>{workspace}</span>
        </div>

        <div className="flex items-center gap-4">
          {errorMessage ? <div className="text-xs text-destructive">{errorMessage}</div> : null}
          <div
            className={cn(
              "flex h-8 items-center gap-1.5 rounded-lg border-2 border-dashed px-3 text-xs transition-colors",
              isTrashDragOver
                ? "border-destructive/60 bg-destructive/10 text-destructive"
                : "border-muted-foreground/20 text-muted-foreground/40 hover:border-muted-foreground/40 hover:text-muted-foreground/60",
            )}
            onDragOver={handleTrashDragOver}
            onDragLeave={handleTrashDragLeave}
            onDrop={handleTrashDrop}
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span>回收站</span>
          </div>
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索卡片..."
              className="h-8 w-44 rounded-lg border border-input bg-background pl-7 pr-3 text-xs outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
            />
          </div>
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <Select
              value={priorityFilter}
              onValueChange={(val: Priority | 'all') => setPriorityFilter(val)}
            >
              <SelectTrigger className="w-[120px] h-8 text-xs">
                <SelectValue placeholder="筛选优先级" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部优先级</SelectItem>
                <SelectItem value="urgent">紧急</SelectItem>
                <SelectItem value="high">高</SelectItem>
                <SelectItem value="medium">中</SelectItem>
                <SelectItem value="low">低</SelectItem>
                <SelectItem value="none">无</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button size="sm" className="h-8 gap-1.5" onClick={() => void handleCreateCard()} disabled={isSaving}>
            <Plus className="h-3.5 w-3.5" />
            新建卡片
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        <ScrollArea className="h-full w-full">
          <div className="flex h-full gap-4 p-4 pb-8">
            {board.columns.map((col) => {
              const columnCards = filteredCards.filter((card) => card.columnId === col.id || card.status === col.name);
              return (
                <KanbanColumn
                  key={col.id}
                  column={col}
                  cards={columnCards}
                  onCardClick={handleCardClick}
                  onDragStart={handleDragStart}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onCreateCard={handleCreateCard}
                  isCreatingCard={isSaving}
                />
              );
            })}
          </div>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
      </div>

      <KanbanCardDrawer
        card={selectedCard}
        isOpen={isDrawerOpen}
        isSaving={isSaving}
        fileTree={fileTree}
        onClose={() => setIsDrawerOpen(false)}
        onSave={(card) => void handleSaveCard(card)}
        onDelete={(cardId) => void handleDeleteCard(cardId)}
        onSendToAi={async (card) => {
          setIsDrawerOpen(false);
          const nextAiState = await onSendCardToAi?.(card);
          if (nextAiState) {
            applyCardUpdateLocally(card.id, (currentCard) => ({
              ...currentCard,
              aiState: nextAiState,
              updatedAt: new Date().toISOString(),
            }));
          } else {
            void loadBoard();
          }
        }}
      />
    </div>
  );
}
