export type Priority = 'none' | 'low' | 'medium' | 'high' | 'urgent';
export type CardStatus = 'Backlog' | 'Todo' | 'In Progress' | 'Done';
export type KanbanAiTaskStatus = 'queued' | 'running' | 'completed' | 'error';

export interface KanbanAiStep {
  id: string;
  title: string;
  description: string;
  status: 'pending' | 'running' | 'blocked' | 'completed' | 'error';
}

export interface KanbanAiState {
  status: KanbanAiTaskStatus;
  sessionId?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  lastMessage?: string | null;
  activeStepTitle?: string | null;
  result?: string | null;
  error?: string | null;
  planSteps?: KanbanAiStep[];
  progress?: {
    completed: number;
    total: number;
  } | null;
}

export const PRIORITY_LABELS: Record<Priority, string> = {
  none: '无',
  low: '低',
  medium: '中',
  high: '高',
  urgent: '紧急',
};

export const CARD_STATUS_LABELS: Record<CardStatus, string> = {
  Backlog: '待整理',
  Todo: '待办',
  'In Progress': '进行中',
  Done: '已完成',
};

export interface KanbanCard {
  id: string;
  boardId: string;
  columnId: string;
  title: string;
  description: string;
  status: CardStatus;
  priority: Priority;
  labels: string[];
  assignee?: string;
  position: number;
  aiState?: KanbanAiState | null;
  createdAt: string;
  updatedAt: string;
}

export interface KanbanColumn {
  id: string;
  boardId: string;
  name: CardStatus;
  statusKey: string;
  position: number;
  order: number;
  wipLimit?: number | null;
}

export interface KanbanBoard {
  id: string;
  workspace?: string;
  name: string;
  description?: string | null;
  createdAt?: string;
  updatedAt?: string;
  columns: KanbanColumn[];
  cards: KanbanCard[];
}
