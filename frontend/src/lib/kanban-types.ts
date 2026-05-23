export type Priority = 'none' | 'low' | 'medium' | 'high' | 'urgent';
export type CardStatus = 'Backlog' | 'Todo' | 'In Progress' | 'Done';

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
