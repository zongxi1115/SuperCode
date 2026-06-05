export type ProjectDocStyle = 'body' | 'heading-1' | 'heading-2' | 'heading-3' | 'quote' | 'bullet' | 'numbered' | 'code' | 'table' | 'divider';

export const PROJECT_DOC_STYLES: Array<{
  id: ProjectDocStyle;
  label: string;
  description: string;
}> = [
  { id: 'body', label: '正文', description: '普通段落' },
  { id: 'heading-1', label: '一级标题', description: '章节标题' },
  { id: 'heading-2', label: '二级标题', description: '小节标题' },
  { id: 'heading-3', label: '三级标题', description: '细分标题' },
  { id: 'quote', label: '引用', description: '强调说明' },
  { id: 'bullet', label: '无序列表', description: '要点罗列' },
  { id: 'numbered', label: '有序列表', description: '步骤编号' },
  { id: 'code', label: '代码块', description: '命令或代码' },
  { id: 'table', label: '表格', description: '结构化信息' },
  { id: 'divider', label: '分割线', description: '章节分隔' },
];
