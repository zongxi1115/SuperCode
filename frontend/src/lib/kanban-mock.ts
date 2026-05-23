import type { KanbanBoard, KanbanCard, KanbanColumn } from './kanban-types';

export const mockColumns: KanbanColumn[] = [
  { id: 'col-1', name: 'Backlog', order: 0 },
  { id: 'col-2', name: 'Todo', order: 1 },
  { id: 'col-3', name: 'In Progress', order: 2 },
  { id: 'col-4', name: 'Done', order: 3 },
];

export const mockCards: KanbanCard[] = [
  {
    id: 'card-1',
    title: 'Initialize SuperCode Project',
    description: 'Set up the initial repository structure and add basic configurations.',
    status: 'Done',
    priority: 'Critical',
    labels: ['setup', 'infra'],
    assignee: 'Alice',
    createdAt: new Date(Date.now() - 100000000).toISOString(),
    updatedAt: new Date(Date.now() - 50000000).toISOString(),
  },
  {
    id: 'card-2',
    title: 'Implement Kanban UI',
    description: 'Create the frontend components for the Kanban board using Tailwind CSS and React.',
    status: 'In Progress',
    priority: 'High',
    labels: ['frontend', 'feature'],
    assignee: 'Bob',
    createdAt: new Date(Date.now() - 80000000).toISOString(),
    updatedAt: new Date(Date.now() - 10000000).toISOString(),
  },
  {
    id: 'card-3',
    title: 'Design Backend Plugin API',
    description: 'Design and document the REST API endpoints for the plugin system.',
    status: 'Todo',
    priority: 'Medium',
    labels: ['backend', 'api'],
    createdAt: new Date(Date.now() - 50000000).toISOString(),
    updatedAt: new Date(Date.now() - 50000000).toISOString(),
  },
  {
    id: 'card-4',
    title: 'Fix Sidebar Layout Bug',
    description: 'The sidebar sometimes overlaps with the editor panel when resized rapidly.',
    status: 'Backlog',
    priority: 'Low',
    labels: ['bug', 'ui'],
    createdAt: new Date(Date.now() - 10000000).toISOString(),
    updatedAt: new Date(Date.now() - 10000000).toISOString(),
  }
];

export const mockBoard: KanbanBoard = {
  id: 'board-1',
  name: 'SuperCode Main Board',
  columns: mockColumns,
  cards: mockCards,
};
