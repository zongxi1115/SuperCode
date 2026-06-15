import { type DragEvent, useCallback, useEffect, useRef, useState } from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { message as appMessage } from '@/components/ui/message';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { apiFetch } from '@/lib/api-client';
import type {
  AppSettings,
  MCPServerConfig,
  MCPServerTestResult,
  ModelConnectionTestResult,
  SessionCleanupRequest,
  SessionCleanupResponse,
  SessionStorageDataKind,
  SessionStorageOverview,
  UIModelProvider,
} from '@/lib/app-types';
import {
  AlertTriangle,
  Brain,
  Braces,
  CalendarClock,
  ChevronDown,
  Check,
  CheckCircle2,
  CircleDollarSign,
  CodeXml,
  Database,
  Eraser,
  Eye,
  EyeOff,
  FileText,
  Globe,
  GripVertical,
  HardDrive,
  ImageIcon,
  Key,
  List,
  MemoryStick,
  PieChart,
  Plus,
  RefreshCcw,
  Search,
  Server,
  Settings2,
  Shield,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  Type,
  Video,
  Volume2,
  Wrench,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

type EditableProvider = UIModelProvider;

type EditableMCPServer = MCPServerConfig & {
  argsText: string;
  envText: string;
  headersText: string;
};

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

const BODY_FONT_OPTIONS = [
  {
    label: '默认界面',
    value:
      'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  {
    label: '圆润舒适',
    value:
      '"DM Sans", "SF Pro Rounded", "Segoe UI", ui-rounded, system-ui, -apple-system, sans-serif',
  },
  {
    label: '代码风格',
    value: '"Cascadia Mono", "JetBrains Mono", Consolas, "Courier New", monospace',
  },
] as const;

const BODY_TEXT_SIZE_OPTIONS = [
  { label: '紧凑', fontSize: 13, lineHeight: 20 },
  { label: '默认', fontSize: 14, lineHeight: 22 },
  { label: '舒适', fontSize: 15, lineHeight: 24 },
  { label: '大字', fontSize: 16, lineHeight: 26 },
] as const;

const IMAGE_QUALITY_OPTIONS = ['auto', 'low', 'medium', 'high'] as const;

type ModelTagOption = {
  value: string;
  label: string;
  icon: LucideIcon;
};

const MODEL_MODALITY_OPTIONS = [
  { value: 'text', label: '文本', icon: Type },
  { value: 'image', label: '图片', icon: ImageIcon },
  { value: 'audio', label: '音频', icon: Volume2 },
  { value: 'video', label: '视频', icon: Video },
  { value: 'file', label: '文件', icon: FileText },
  { value: 'embedding', label: '向量', icon: Database },
] satisfies readonly ModelTagOption[];

const MODEL_CAPABILITY_OPTIONS = [
  { value: 'tools', label: '工具调用', icon: Wrench },
  { value: 'vision', label: '视觉', icon: Eye },
  { value: 'json', label: 'JSON', icon: Braces },
  { value: 'reasoning', label: '推理', icon: Brain },
  { value: 'image_generation', label: '生图', icon: ImageIcon },
  { value: 'audio_input', label: '音频输入', icon: Volume2 },
  { value: 'audio_output', label: '音频输出', icon: Volume2 },
  { value: 'video_generation', label: '视频', icon: Video },
  { value: 'embedding', label: '向量', icon: Database },
  { value: 'rerank', label: '重排', icon: List },
] satisfies readonly ModelTagOption[];

const MODEL_CAPABILITY_PREVIEW_OPTIONS = [
  ...MODEL_CAPABILITY_OPTIONS,
  { value: 'basic_text', label: '基础文本', icon: Type },
] satisfies readonly ModelTagOption[];

const MODEL_PARAMETER_OPTIONS = [
  { value: 'tools', label: '工具', icon: Wrench },
  { value: 'tool_choice', label: '工具选择', icon: Settings2 },
  { value: 'response_format', label: '响应格式', icon: Braces },
  { value: 'json_schema', label: 'JSON Schema', icon: Braces },
  { value: 'temperature', label: '温度', icon: SlidersHorizontal },
  { value: 'top_p', label: 'Top P', icon: SlidersHorizontal },
  { value: 'max_tokens', label: '最大 Token', icon: Type },
  { value: 'stream', label: '流式输出', icon: RefreshCcw },
  { value: 'reasoning_effort', label: '推理强度', icon: Brain },
  { value: 'seed', label: 'Seed', icon: Settings2 },
  { value: 'stop', label: '停止词', icon: List },
] satisfies readonly ModelTagOption[];

type SettingsDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  providers: UIModelProvider[];
  configPath: string | null;
  mcpServers: MCPServerConfig[];
  mcpConfigPath: string | null;
  settings: AppSettings;
  currentWorkspace: string;
  onSaveProviders: (providers: UIModelProvider[]) => Promise<void>;
  onDiscoverModels: (provider: UIModelProvider) => Promise<{
    models: UIModelProvider['models'];
  }>;
  onTestModelConnection: (
    provider: UIModelProvider,
    model: string | null,
  ) => Promise<ModelConnectionTestResult>;
  onSaveMcpServers: (servers: MCPServerConfig[]) => Promise<void>;
  onTestMcpServer: (server: MCPServerConfig) => Promise<MCPServerTestResult>;
  onTestEmbedding: (embedding: AppSettings['embedding']) => Promise<string>;
  onSaveSettings: (settings: AppSettings) => Promise<void>;
  onSessionsChanged?: () => void | Promise<void>;
};

function createModelRecord() {
  return {
    id: '',
    name: null,
    contextWindow: 32_000,
    maxOutputTokens: null,
    inputModalities: ['text'],
    outputModalities: ['text'],
    supportedParameters: [],
    capabilities: [],
    pricing: {},
    ownedBy: null,
    created: null,
    description: null,
  };
}

function compactStringList(values: unknown) {
  return Array.isArray(values)
    ? values.map((item) => String(item).trim()).filter(Boolean)
    : [];
}

function toggleStringListValue(values: string[], value: string, checked: boolean) {
  const next = values.filter((item) => item.toLowerCase() !== value.toLowerCase());
  return checked ? [...next, value] : next;
}

function getModelTagOptions(
  values: string[],
  options: readonly ModelTagOption[],
  getLabel: (value: string) => string,
) {
  const optionByValue = new Map(options.map((option) => [option.value.toLowerCase(), option]));
  return compactStringList(values).map((value) => {
    const option = optionByValue.get(value.toLowerCase());
    return option ?? { value, label: getLabel(value), icon: Settings2 };
  });
}

function ModelMetadataPreviewBadges({
  label,
  values,
  options,
  getLabel,
}: {
  label: string;
  values: string[];
  options: readonly ModelTagOption[];
  getLabel: (value: string) => string;
}) {
  const selectedOptions = getModelTagOptions(values, options, getLabel);
  if (selectedOptions.length === 0) return null;

  return (
    <span className="inline-flex min-w-0 items-center gap-1">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <span className="inline-flex min-w-0 flex-wrap gap-1">
        {selectedOptions.slice(0, 4).map((option) => {
          const Icon = option.icon;
          return (
            <Badge
              key={`${label}-${option.value}`}
              variant="secondary"
              title={option.label}
              className="h-5 gap-1 rounded-md px-1.5 text-[10px]"
            >
              <Icon className="size-2.5" />
              {option.label}
            </Badge>
          );
        })}
        {selectedOptions.length > 4 ? (
          <Badge variant="outline" className="h-5 rounded-md px-1.5 text-[10px]">
            +{selectedOptions.length - 4}
          </Badge>
        ) : null}
      </span>
    </span>
  );
}

function ModelMetadataTagSelect({
  values,
  onChange,
  options,
  getLabel,
  placeholder,
}: {
  values: string[];
  options: readonly ModelTagOption[];
  getLabel: (value: string) => string;
  placeholder: string;
  onChange: (values: string[]) => void;
}) {
  const selectedValues = compactStringList(values);
  const selectedOptions = getModelTagOptions(selectedValues, options, getLabel);
  const optionByValue = new Map(options.map((option) => [option.value.toLowerCase(), option]));
  const unknownOptions = selectedOptions.filter(
    (option) => !optionByValue.has(option.value.toLowerCase()),
  );
  const allOptions = [...options, ...unknownOptions];

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className="h-auto min-h-8 w-full justify-between gap-2 px-2 py-1.5 text-left font-normal"
        >
          <span className="flex min-w-0 flex-1 flex-wrap gap-1">
            {selectedOptions.length === 0 ? (
              <span className="text-[11px] text-muted-foreground">{placeholder}</span>
            ) : (
              selectedOptions.map((option) => {
                const Icon = option.icon;
                return (
                  <Badge
                    key={option.value}
                    variant="secondary"
                    className="h-5 gap-1 rounded-md px-1.5 text-[10px]"
                  >
                    <Icon className="size-2.5" />
                    {option.label}
                  </Badge>
                );
              })
            )}
          </span>
          <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[--radix-popover-trigger-width] p-0">
        <Command>
          <CommandInput placeholder="搜索..." className="h-8 text-xs" />
          <CommandList className="max-h-56">
            <CommandEmpty className="py-4 text-xs text-muted-foreground">没有匹配项</CommandEmpty>
            <CommandGroup>
              {allOptions.map((option) => {
                const checked = selectedValues.some(
                  (value) => value.toLowerCase() === option.value.toLowerCase(),
                );
                const Icon = option.icon;
                return (
                  <CommandItem
                    key={option.value}
                    value={`${option.label} ${option.value}`}
                    onSelect={() =>
                      onChange(toggleStringListValue(selectedValues, option.value, !checked))
                    }
                    className="gap-2 text-xs"
                  >
                    <span className="flex size-5 items-center justify-center rounded border bg-background">
                      <Icon className="size-3 text-muted-foreground" />
                    </span>
                    <span className="flex-1">{option.label}</span>
                    <span className="font-mono text-[10px] text-muted-foreground">{option.value}</span>
                    <Check
                      className={`size-3 ${checked ? 'opacity-100' : 'opacity-0'}`}
                    />
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function serializeModelRecord(model: UIModelProvider['models'][number]) {
  const pricing =
    model.pricing && typeof model.pricing === 'object' && !Array.isArray(model.pricing)
      ? model.pricing
      : {};
  return {
    id: model.id.trim(),
    name: model.name?.trim() || null,
    contextWindow: model.contextWindow ?? null,
    maxOutputTokens: model.maxOutputTokens ?? null,
    inputModalities: compactStringList(model.inputModalities),
    outputModalities: compactStringList(model.outputModalities),
    supportedParameters: compactStringList(model.supportedParameters),
    capabilities: compactStringList(model.capabilities),
    pricing,
    ownedBy: model.ownedBy?.trim() || null,
    created: model.created ?? null,
    description: model.description?.trim() || null,
  };
}

function serializeProvider(provider: EditableProvider): UIModelProvider {
  return {
    id: provider.id ?? null,
    name: provider.name.trim() || '未命名供应商',
    baseUrl: provider.baseUrl.trim(),
    apiKey: provider.apiKey.trim(),
    models: provider.models.map(serializeModelRecord).filter((model) => model.id),
    provider: provider.provider ?? null,
    apiMode: provider.apiMode ?? 'chat_completions',
  };
}

function formatTokenCount(value: number | null | undefined) {
  if (!value || value <= 0) return '未知';
  return value.toLocaleString();
}

function formatPricePerMillion(value: unknown) {
  const numeric = typeof value === 'number' ? value : Number(String(value ?? '').trim());
  if (!Number.isFinite(numeric) || numeric < 0) return '$--';
  return `$${(numeric * 1_000_000).toFixed(3)}`;
}

function modalityLabel(value: string) {
  const normalized = value.toLowerCase();
  if (normalized === 'image') return '图片';
  if (normalized === 'audio') return '音频';
  if (normalized === 'video') return '视频';
  if (normalized === 'file') return '文件';
  if (normalized === 'embedding') return '向量';
  return '文本';
}

function capabilityLabel(value: string) {
  const normalized = value.toLowerCase();
  if (normalized === 'vision') return '视觉';
  if (normalized === 'tools') return '工具';
  if (normalized === 'json') return 'JSON';
  if (normalized === 'reasoning') return '推理';
  if (normalized === 'image_generation') return '生图';
  if (normalized === 'audio_input') return '音频输入';
  if (normalized === 'audio_output') return '音频输出';
  if (normalized === 'video_generation') return '视频';
  if (normalized === 'embedding') return '向量';
  if (normalized === 'rerank') return '重排';
  return value;
}

function normalizeLines(text: string) {
  return text
    .replace(/\\n/g, '\n')
    .split(/\n+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function stringifyMap(value: Record<string, string> | undefined) {
  return Object.entries(value ?? {})
    .map(([key, item]) => `${key}=${item}`)
    .join('\n');
}

function parseMap(text: string) {
  const entries: Record<string, string> = {};
  for (const line of text.split(/\n+/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const separatorIndex = trimmed.indexOf('=');
    if (separatorIndex < 0) {
      entries[trimmed] = '';
      continue;
    }
    const key = trimmed.slice(0, separatorIndex).trim();
    if (!key) continue;
    entries[key] = trimmed.slice(separatorIndex + 1).trim();
  }
  return entries;
}

function toEditableProvider(provider?: UIModelProvider): EditableProvider {
  return {
    id: provider?.id ?? null,
    name: provider?.name ?? '',
    baseUrl: provider?.baseUrl ?? '',
    apiKey: provider?.apiKey ?? '',
    models: provider?.models ?? [],
    provider: provider?.provider ?? null,
    apiMode: provider?.apiMode ?? 'chat_completions',
  };
}

function createMcpServerId() {
  return `mcp-${crypto.randomUUID().slice(0, 8)}`;
}

function toEditableMcpServer(server?: MCPServerConfig): EditableMCPServer {
  const id = server?.id ?? createMcpServerId();
  return {
    id,
    name: server?.name ?? '',
    enabled: server?.enabled ?? true,
    transport: server?.transport ?? 'stdio',
    command: server?.command ?? '',
    args: server?.args ?? [],
    env: server?.env ?? {},
    url: server?.url ?? '',
    bearerToken: server?.bearerToken ?? '',
    headers: server?.headers ?? {},
    status: server?.status,
    argsText: (server?.args ?? []).join('\n'),
    envText: stringifyMap(server?.env),
    headersText: stringifyMap(server?.headers),
  };
}

function serializeMcpServer(server: EditableMCPServer): MCPServerConfig {
  return {
    id: server.id ?? createMcpServerId(),
    name: server.name.trim() || '未命名 MCP',
    enabled: server.enabled,
    transport: server.transport,
    command: server.command.trim(),
    args: normalizeLines(server.argsText),
    env: parseMap(server.envText),
    url: server.url.trim(),
    bearerToken: server.bearerToken.trim(),
    headers: parseMap(server.headersText),
  };
}

function withSettingsDefaults(settings: AppSettings): AppSettings {
  return {
    ...settings,
    finalAnswerRendering: settings.finalAnswerRendering ?? 'markdown',
    embedding: {
      enabled: settings.embedding?.enabled ?? false,
      baseUrl: settings.embedding?.baseUrl ?? '',
      apiKey: settings.embedding?.apiKey ?? '',
      model: settings.embedding?.model ?? '',
    },
    imageGeneration: {
      enabled: settings.imageGeneration?.enabled ?? false,
      baseUrl: settings.imageGeneration?.baseUrl ?? '',
      apiKey: settings.imageGeneration?.apiKey ?? '',
      model: settings.imageGeneration?.model ?? '',
      size: settings.imageGeneration?.size ?? '1024x1024',
      quality: settings.imageGeneration?.quality ?? 'auto',
    },
    tinyfish: {
      enabled: settings.tinyfish?.enabled ?? false,
      apiKey: settings.tinyfish?.apiKey ?? '',
      searchUrl: settings.tinyfish?.searchUrl ?? 'https://api.search.tinyfish.ai',
      fetchUrl: settings.tinyfish?.fetchUrl ?? 'https://api.fetch.tinyfish.ai',
      timeout: settings.tinyfish?.timeout ?? 30,
    },
    memory: {
      enabled: settings.memory?.enabled ?? true,
      autoLearn: settings.memory?.autoLearn ?? true,
      global: settings.memory?.global ?? [],
      workspaces: settings.memory?.workspaces ?? {},
    },
  };
}

function createMemoryItem(scope: 'global' | 'workspace'): AppSettings['memory']['global'][number] {
  const now = Date.now();
  return {
    id: crypto.randomUUID(),
    content: '',
    scope,
    enabled: true,
    createdAt: now,
    updatedAt: now,
    sourceSessionId: null,
    sourcePreview: '手动添加',
  };
}

const SESSION_CHART_COLORS = [
  '#2563eb',
  '#16a34a',
  '#f59e0b',
  '#e11d48',
  '#7c3aed',
  '#0891b2',
  '#dc2626',
  '#475569',
];

function formatStorageBytes(value: number | null | undefined) {
  const bytes = Math.max(0, Number(value ?? 0));
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatStorageTime(value: number | null | undefined) {
  if (!value) return '未知';
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function buildSessionPieGradient(items: SessionStorageDataKind[]) {
  const visibleItems = items.filter((item) => item.weight > 0);
  const total = visibleItems.reduce((sum, item) => sum + item.weight, 0);
  if (!total) return 'conic-gradient(hsl(var(--muted)) 0deg 360deg)';
  let cursor = 0;
  return `conic-gradient(${visibleItems
    .map((item) => {
      const start = cursor;
      cursor += (item.weight / total) * 360;
      const index = Math.max(0, items.findIndex((candidate) => candidate.key === item.key));
      const color = SESSION_CHART_COLORS[index % SESSION_CHART_COLORS.length];
      return `${color} ${start.toFixed(2)}deg ${cursor.toFixed(2)}deg`;
    })
    .join(', ')})`;
}

export function SettingsDialog({
  open,
  onOpenChange,
  providers,
  configPath,
  mcpServers,
  mcpConfigPath,
  settings,
  currentWorkspace,
  onSaveProviders,
  onDiscoverModels,
  onTestModelConnection,
  onSaveMcpServers,
  onTestMcpServer,
  onTestEmbedding,
  onSaveSettings,
  onSessionsChanged,
}: SettingsDialogProps) {
  const [draftProviders, setDraftProviders] = useState<EditableProvider[]>(
    providers.length > 0 ? providers.map((p) => toEditableProvider(p)) : [toEditableProvider()],
  );
  const [draftMcpServers, setDraftMcpServers] = useState<EditableMCPServer[]>(
    mcpServers.map((server) => toEditableMcpServer(server)),
  );
  const [draftSettings, setDraftSettings] = useState<AppSettings>(() => withSettingsDefaults(settings));
  const [activeTab, setActiveTab] = useState('providers');
  const [isSaving, setIsSaving] = useState(false);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [modelTestingId, setModelTestingId] = useState<string | null>(null);
  const [mcpTestingId, setMcpTestingId] = useState<string | null>(null);
  const [isTestingEmbedding, setIsTestingEmbedding] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visibleKeys, setVisibleKeys] = useState<Set<string>>(new Set());
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [deleteMcpConfirmId, setDeleteMcpConfirmId] = useState<string | null>(null);
  const [selectedProviderIndex, setSelectedProviderIndex] = useState(0);
  const [selectedMcpIndex, setSelectedMcpIndex] = useState(0);
  const [editingModelKeys, setEditingModelKeys] = useState<Set<string>>(new Set());
  const [draggingProviderIndex, setDraggingProviderIndex] = useState<number | null>(null);
  const [modelTestResults, setModelTestResults] = useState<Record<string, ModelConnectionTestResult>>({});
  const [mcpTestResults, setMcpTestResults] = useState<Record<string, MCPServerTestResult>>({});
  const [sessionStorage, setSessionStorage] = useState<SessionStorageOverview | null>(null);
  const [sessionCleanupPreview, setSessionCleanupPreview] = useState<SessionCleanupResponse | null>(null);
  const [sessionCleanupMode, setSessionCleanupMode] = useState<SessionCleanupRequest['mode']>('older_than');
  const [sessionCleanupDays, setSessionCleanupDays] = useState(30);
  const [sessionCleanupWorkspace, setSessionCleanupWorkspace] = useState('');
  const [isLoadingSessionStorage, setIsLoadingSessionStorage] = useState(false);
  const [isPreviewingSessionCleanup, setIsPreviewingSessionCleanup] = useState(false);
  const [isCleaningSessions, setIsCleaningSessions] = useState(false);
  const [isSessionCleanupArmed, setIsSessionCleanupArmed] = useState(false);
  const didInitializeOpenDraftRef = useRef(false);
  const isMountedRef = useRef(false);
  const isOpenRef = useRef(open);
  const activeTextSize =
    BODY_TEXT_SIZE_OPTIONS.find(
      (option) =>
        option.fontSize === draftSettings.bodyFontSize &&
        option.lineHeight === draftSettings.bodyLineHeight,
    ) ?? BODY_TEXT_SIZE_OPTIONS[1];
  const embeddingKey = 'embedding-api-key';
  const isEmbeddingKeyVisible = visibleKeys.has(embeddingKey);
  const imageGenerationKey = 'image-generation-api-key';
  const isImageGenerationKeyVisible = visibleKeys.has(imageGenerationKey);
  const tinyfishKey = 'tinyfish-api-key';
  const isTinyfishKeyVisible = visibleKeys.has(tinyfishKey);
  const currentWorkspaceKey = currentWorkspace.trim();
  const workspaceMemoryItems =
    currentWorkspaceKey && draftSettings.memory?.workspaces
      ? draftSettings.memory.workspaces[currentWorkspaceKey] ?? []
      : [];
  const storageDataKinds = sessionStorage?.dataKinds ?? [];
  const storageWeightTotal = storageDataKinds.reduce((sum, item) => sum + Math.max(0, item.weight), 0);
  const topStorageWorkspaces = sessionStorage?.workspaces.slice(0, 5) ?? [];
  const cleanupSummary = sessionCleanupPreview?.summary;

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    isOpenRef.current = open;
  }, [open]);

  const canUpdateAsyncState = () => isMountedRef.current && isOpenRef.current;

  useEffect(() => {
    if (!open) {
      didInitializeOpenDraftRef.current = false;
      return;
    }
    if (didInitializeOpenDraftRef.current) {
      return;
    }
    didInitializeOpenDraftRef.current = true;
    setDraftProviders(
      providers.length > 0 ? providers.map((p) => toEditableProvider(p)) : [toEditableProvider()],
    );
    setDraftMcpServers(mcpServers.map((server) => toEditableMcpServer(server)));
    setDraftSettings(withSettingsDefaults(settings));
    setSelectedProviderIndex(0);
    setSelectedMcpIndex(0);
    setEditingModelKeys(new Set());
    setDeleteConfirmId(null);
    setDeleteMcpConfirmId(null);
    setMcpTestResults({});
    setIsSaving(false);
    setRefreshingId(null);
    setMcpTestingId(null);
    setIsTestingEmbedding(false);
    setFeedback(null);
    setError(null);
    setModelTestingId(null);
    setModelTestResults({});
    setSessionStorage(null);
    setSessionCleanupPreview(null);
    setSessionCleanupMode('older_than');
    setSessionCleanupDays(30);
    setSessionCleanupWorkspace(currentWorkspace.trim());
    setIsLoadingSessionStorage(false);
    setIsPreviewingSessionCleanup(false);
    setIsCleaningSessions(false);
    setIsSessionCleanupArmed(false);
  }, [open, providers, mcpServers, settings, currentWorkspace]);

  const loadSessionStorage = useCallback(async () => {
    setIsLoadingSessionStorage(true);
    setError(null);
    try {
      const res = await apiFetch('/api/sessions/storage');
      const data = await res.json();
      if (!res.ok) {
        throw new Error(String(data.detail ?? '读取 Session 数据失败'));
      }
      if (!canUpdateAsyncState()) return;
      const overview = data as SessionStorageOverview;
      setSessionStorage(overview);
      setSessionCleanupWorkspace((prev) => {
        const normalizedPrev = prev.trim();
        if (normalizedPrev && overview.workspaces.some((item) => item.workspace === normalizedPrev)) {
          return normalizedPrev;
        }
        if (currentWorkspace.trim() && overview.workspaces.some((item) => item.workspace === currentWorkspace.trim())) {
          return currentWorkspace.trim();
        }
        return overview.workspaces[0]?.workspace ?? '';
      });
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      const message = getErrorMessage(e, '读取 Session 数据失败');
      setError(message);
      appMessage.error(message);
    } finally {
      if (canUpdateAsyncState()) {
        setIsLoadingSessionStorage(false);
      }
    }
  }, [currentWorkspace]);

  useEffect(() => {
    if (!open || activeTab !== 'data') return;
    void loadSessionStorage();
  }, [activeTab, loadSessionStorage, open]);

  const buildSessionCleanupRequest = (dryRun: boolean): SessionCleanupRequest => ({
    mode: sessionCleanupMode,
    days: sessionCleanupMode === 'older_than' ? sessionCleanupDays : null,
    workspace: sessionCleanupMode === 'workspace' ? sessionCleanupWorkspace : null,
    dryRun,
    includeActive: false,
  });

  const requestSessionCleanup = async (dryRun: boolean) => {
    const request = buildSessionCleanupRequest(dryRun);
    const res = await apiFetch('/api/sessions/cleanup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(String(data.detail ?? 'Session 清理失败'));
    }
    return data as SessionCleanupResponse;
  };

  const handlePreviewSessionCleanup = async () => {
    setError(null);
    setFeedback(null);
    setIsSessionCleanupArmed(false);
    setIsPreviewingSessionCleanup(true);
    try {
      const data = await requestSessionCleanup(true);
      if (!canUpdateAsyncState()) return;
      setSessionCleanupPreview(data);
      setFeedback(`找到 ${data.candidateCount} 个可清理 Session`);
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      const message = getErrorMessage(e, 'Session 清理预览失败');
      setError(message);
      appMessage.error(message);
    } finally {
      if (canUpdateAsyncState()) {
        setIsPreviewingSessionCleanup(false);
      }
    }
  };

  const handleRunSessionCleanup = async () => {
    if (!sessionCleanupPreview || sessionCleanupPreview.candidateCount <= 0) {
      await handlePreviewSessionCleanup();
      return;
    }
    if (!isSessionCleanupArmed) {
      setIsSessionCleanupArmed(true);
      return;
    }
    setError(null);
    setFeedback(null);
    setIsCleaningSessions(true);
    try {
      const data = await requestSessionCleanup(false);
      if (!canUpdateAsyncState()) return;
      setSessionCleanupPreview(data);
      setIsSessionCleanupArmed(false);
      await loadSessionStorage();
      await onSessionsChanged?.();
      const message = `已清理 ${data.deletedCount} 个 Session`;
      setFeedback(message);
      appMessage.success(message);
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      const message = getErrorMessage(e, 'Session 清理失败');
      setError(message);
      appMessage.error(message);
    } finally {
      if (canUpdateAsyncState()) {
        setIsCleaningSessions(false);
      }
    }
  };

  const toggleKeyVisibility = (key: string) => {
    setVisibleKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const updateProvider = (index: number, patch: Partial<EditableProvider>) => {
    setDraftProviders((prev) =>
      prev.map((p, i) => {
        if (i !== index) return p;
        return { ...p, ...patch };
      }),
    );
  };

  const updateProviderModel = (
    providerIndex: number,
    modelIndex: number,
    patch: Partial<UIModelProvider['models'][number]>,
  ) => {
    setDraftProviders((prev) =>
      prev.map((provider, index) => {
        if (index !== providerIndex) return provider;
        return {
          ...provider,
          models: provider.models.map((model, itemIndex) =>
            itemIndex === modelIndex ? { ...model, ...patch } : model,
          ),
        };
      }),
    );
  };

  const toggleModelEditing = (key: string) => {
    setEditingModelKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const addProviderModel = (providerIndex: number) => {
    const provider = draftProviders[providerIndex];
    const nextModelIndex = provider?.models.length ?? 0;
    const modelEditKey = `${provider?.id ?? `draft-${providerIndex}`}::model-${nextModelIndex}`;
    setDraftProviders((prev) =>
      prev.map((provider, index) =>
        index === providerIndex
          ? { ...provider, models: [...provider.models, createModelRecord()] }
          : provider,
      ),
    );
    setEditingModelKeys((prev) => new Set(prev).add(modelEditKey));
  };

  const removeProviderModel = (providerIndex: number, modelIndex: number) => {
    setDraftProviders((prev) =>
      prev.map((provider, index) =>
        index === providerIndex
          ? { ...provider, models: provider.models.filter((_, itemIndex) => itemIndex !== modelIndex) }
          : provider,
      ),
    );
  };

  const updateMcpServer = (index: number, patch: Partial<EditableMCPServer>) => {
    setDraftMcpServers((prev) =>
      prev.map((server, i) => {
        if (i !== index) return server;
        const next = { ...server, ...patch };
        if (patch.argsText !== undefined) {
          next.args = normalizeLines(patch.argsText);
        }
        if (patch.envText !== undefined) {
          next.env = parseMap(patch.envText);
        }
        if (patch.headersText !== undefined) {
          next.headers = parseMap(patch.headersText);
        }
        return next;
      }),
    );
  };

  const handleAddProvider = useCallback(() => {
    setDraftProviders((prev) => {
      const next = [...prev, toEditableProvider()];
      setSelectedProviderIndex(next.length - 1);
      return next;
    });
    setActiveTab('providers');
  }, []);

  const handleAddMcpServer = useCallback(() => {
    setDraftMcpServers((prev) => {
      const next = [...prev, toEditableMcpServer()];
      setSelectedMcpIndex(next.length - 1);
      return next;
    });
    setActiveTab('mcp');
  }, []);

  const handleDeleteProvider = (index: number) => {
    setDraftProviders((prev) => prev.filter((_, i) => i !== index));
    setSelectedProviderIndex((prev) => {
      const nextCount = draftProviders.length - 1;
      if (nextCount === 0) return 0;
      if (prev >= nextCount) return nextCount - 1;
      if (prev > index) return prev - 1;
      return prev;
    });
    setDeleteConfirmId(null);
  };

  const handleDeleteMcpServer = (index: number) => {
    setDraftMcpServers((prev) => prev.filter((_, i) => i !== index));
    setSelectedMcpIndex((prev) => {
      const nextCount = draftMcpServers.length - 1;
      if (nextCount === 0) return 0;
      if (prev >= nextCount) return nextCount - 1;
      if (prev > index) return prev - 1;
      return prev;
    });
    setDeleteMcpConfirmId(null);
  };

  const handleProviderDragStart = (event: DragEvent<HTMLButtonElement>, index: number) => {
    setDraggingProviderIndex(index);
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', String(index));
  };

  const handleProviderDragOver = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  };

  const handleProviderDrop = (event: DragEvent<HTMLButtonElement>, targetIndex: number) => {
    event.preventDefault();
    const sourceIndex = Number(event.dataTransfer.getData('text/plain'));
    setDraggingProviderIndex(null);
    if (!Number.isInteger(sourceIndex) || sourceIndex === targetIndex) return;

    setDraftProviders((prev) => {
      if (sourceIndex < 0 || sourceIndex >= prev.length || targetIndex < 0 || targetIndex >= prev.length) {
        return prev;
      }
      const next = [...prev];
      const [moved] = next.splice(sourceIndex, 1);
      next.splice(targetIndex, 0, moved);
      return next;
    });
    setSelectedProviderIndex((prev) => {
      if (prev === sourceIndex) return targetIndex;
      if (sourceIndex < prev && prev <= targetIndex) return prev - 1;
      if (targetIndex <= prev && prev < sourceIndex) return prev + 1;
      return prev;
    });
  };

  const handleDiscoverModels = async (provider: EditableProvider, index: number) => {
    setError(null);
    setFeedback(null);
    setRefreshingId(provider.id ?? `draft-${index}`);
    try {
      const catalog = await onDiscoverModels({
        ...serializeProvider(provider),
        name: provider.name.trim() || '未命名供应商',
      });
      if (!canUpdateAsyncState()) return;
      updateProvider(index, {
        models: catalog.models,
      });
      const contextCount = catalog.models.filter((model) => model.contextWindow).length;
      const feedback = `已拉取 ${catalog.models.length} 个模型，缓存 ${contextCount} 个上下文窗口`;
      setFeedback(feedback);
      appMessage.success(feedback);
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      const message = getErrorMessage(e, '拉取模型失败');
      setError(message);
      appMessage.error(message);
    } finally {
      if (canUpdateAsyncState()) {
        setRefreshingId(null);
      }
    }
  };

  const handleTestModelConnection = async (
    provider: EditableProvider,
    index: number,
    modelId?: string | null,
  ) => {
    const serialized = serializeProvider(provider);
    const selectedModel = modelId?.trim() || serialized.models[0]?.id || null;
    const resultKey = `${provider.id ?? `draft-${index}`}::${selectedModel ?? 'list'}`;
    setError(null);
    setFeedback(null);
    setModelTestingId(resultKey);
    try {
      const result = await onTestModelConnection(serialized, selectedModel);
      if (!canUpdateAsyncState()) return;
      setModelTestResults((prev) => ({ ...prev, [resultKey]: result }));
      const message = result.message || '模型连接成功';
      setFeedback(message);
      appMessage.success(message);
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      const message = getErrorMessage(e, '模型连接测试失败');
      setModelTestResults((prev) => ({
        ...prev,
        [resultKey]: {
          ok: false,
          message,
          modelCount: 0,
          model: selectedModel,
        },
      }));
      setError(message);
      appMessage.error(message);
    } finally {
      if (canUpdateAsyncState()) {
        setModelTestingId(null);
      }
    }
  };

  const handleTestEmbedding = async () => {
    setError(null);
    setFeedback(null);
    setIsTestingEmbedding(true);
    try {
      const message = await onTestEmbedding({
        enabled: draftSettings.embedding?.enabled ?? false,
        baseUrl: draftSettings.embedding?.baseUrl ?? '',
        apiKey: draftSettings.embedding?.apiKey ?? '',
        model: draftSettings.embedding?.model ?? '',
      });
      if (!canUpdateAsyncState()) return;
      setFeedback(message);
      appMessage.success(message);
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      const message = getErrorMessage(e, 'Embedding 测试失败');
      setError(message);
      appMessage.error(message);
    } finally {
      if (canUpdateAsyncState()) {
        setIsTestingEmbedding(false);
      }
    }
  };

  const handleTestMcpServer = async (server: EditableMCPServer, index: number) => {
    const key = server.id ?? `draft-mcp-${index}`;
    setError(null);
    setFeedback(null);
    setMcpTestingId(key);
    try {
      const serialized = serializeMcpServer(server);
      const result = await onTestMcpServer(serialized);
      if (!canUpdateAsyncState()) return;
      setMcpTestResults((prev) => ({ ...prev, [key]: result }));
      updateMcpServer(index, {
        status: {
          state: 'ok',
          message: `已发现 ${result.toolCount} 个工具`,
          toolCount: result.toolCount,
        },
      });
      const message = `MCP 连接成功，发现 ${result.toolCount} 个工具`;
      setFeedback(message);
      appMessage.success(message);
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      const message = getErrorMessage(e, 'MCP 连接测试失败');
      updateMcpServer(index, {
        status: {
          state: 'error',
          message,
          toolCount: 0,
        },
      });
      setError(message);
    } finally {
      if (canUpdateAsyncState()) {
        setMcpTestingId(null);
      }
    }
  };

  const updateImageGenerationSettings = (patch: Partial<AppSettings['imageGeneration']>) => {
    setDraftSettings((prev) => ({
      ...prev,
      imageGeneration: {
        enabled: prev.imageGeneration?.enabled ?? false,
        baseUrl: prev.imageGeneration?.baseUrl ?? '',
        apiKey: prev.imageGeneration?.apiKey ?? '',
        model: prev.imageGeneration?.model ?? '',
        size: prev.imageGeneration?.size ?? '1024x1024',
        quality: prev.imageGeneration?.quality ?? 'auto',
        ...patch,
      },
    }));
  };

  const updateTinyfishSettings = (patch: Partial<AppSettings['tinyfish']>) => {
    setDraftSettings((prev) => ({
      ...prev,
      tinyfish: {
        enabled: prev.tinyfish?.enabled ?? false,
        apiKey: prev.tinyfish?.apiKey ?? '',
        searchUrl: prev.tinyfish?.searchUrl ?? 'https://api.search.tinyfish.ai',
        fetchUrl: prev.tinyfish?.fetchUrl ?? 'https://api.fetch.tinyfish.ai',
        timeout: prev.tinyfish?.timeout ?? 30,
        ...patch,
      },
    }));
  };

  const updateMemoryItem = (
    scope: 'global' | 'workspace',
    id: string,
    patch: Partial<AppSettings['memory']['global'][number]>,
  ) => {
    setDraftSettings((prev) => {
      const memory = {
        enabled: prev.memory?.enabled ?? true,
        autoLearn: prev.memory?.autoLearn ?? true,
        global: prev.memory?.global ?? [],
        workspaces: prev.memory?.workspaces ?? {},
      };
      const applyPatch = (item: AppSettings['memory']['global'][number]) =>
        item.id === id ? { ...item, ...patch, updatedAt: Date.now() } : item;
      if (scope === 'global') {
        return {
          ...prev,
          memory: {
            ...memory,
            global: memory.global.map(applyPatch),
          },
        };
      }
      if (!currentWorkspaceKey) return prev;
      return {
        ...prev,
        memory: {
          ...memory,
          workspaces: {
            ...memory.workspaces,
            [currentWorkspaceKey]: (memory.workspaces[currentWorkspaceKey] ?? []).map(applyPatch),
          },
        },
      };
    });
  };

  const addMemoryItem = (scope: 'global' | 'workspace') => {
    setDraftSettings((prev) => {
      const memory = {
        enabled: prev.memory?.enabled ?? true,
        autoLearn: prev.memory?.autoLearn ?? true,
        global: prev.memory?.global ?? [],
        workspaces: prev.memory?.workspaces ?? {},
      };
      const nextItem = createMemoryItem(scope);
      if (scope === 'global') {
        return {
          ...prev,
          memory: {
            ...memory,
            global: [...memory.global, nextItem],
          },
        };
      }
      if (!currentWorkspaceKey) return prev;
      return {
        ...prev,
        memory: {
          ...memory,
          workspaces: {
            ...memory.workspaces,
            [currentWorkspaceKey]: [...(memory.workspaces[currentWorkspaceKey] ?? []), nextItem],
          },
        },
      };
    });
  };

  const deleteMemoryItem = (scope: 'global' | 'workspace', id: string) => {
    setDraftSettings((prev) => {
      const memory = {
        enabled: prev.memory?.enabled ?? true,
        autoLearn: prev.memory?.autoLearn ?? true,
        global: prev.memory?.global ?? [],
        workspaces: prev.memory?.workspaces ?? {},
      };
      if (scope === 'global') {
        return {
          ...prev,
          memory: {
            ...memory,
            global: memory.global.filter((item) => item.id !== id),
          },
        };
      }
      if (!currentWorkspaceKey) return prev;
      return {
        ...prev,
        memory: {
          ...memory,
          workspaces: {
            ...memory.workspaces,
            [currentWorkspaceKey]: (memory.workspaces[currentWorkspaceKey] ?? []).filter(
              (item) => item.id !== id,
            ),
          },
        },
      };
    });
  };

  const handleSave = async () => {
    setError(null);
    setFeedback(null);
    setIsSaving(true);
    try {
      await onSaveProviders(draftProviders.map(serializeProvider));
      await onSaveMcpServers(draftMcpServers.map((server) => serializeMcpServer(server)));
      await onSaveSettings(draftSettings);
      if (!canUpdateAsyncState()) return;
      setFeedback('设置已保存');
      appMessage.success('设置已保存');
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      const message = getErrorMessage(e, '保存设置失败');
      setError(message);
      appMessage.error(message);
    } finally {
      if (canUpdateAsyncState()) {
        setIsSaving(false);
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        onInteractOutside={(event) => event.preventDefault()}
        className="flex max-h-[90vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-[860px]"
      >
          <DialogHeader className="shrink-0 px-6 pt-6 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10">
              <Settings2 className="size-4.5 text-primary" />
            </div>
            <div className="min-w-0 flex-1">
              <DialogTitle className="text-lg">设置</DialogTitle>
              <DialogDescription className="mt-0.5 text-sm">
                管理供应商、模型来源与安全选项
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <Separator />

        <Tabs
          value={activeTab}
          onValueChange={setActiveTab}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <div className="shrink-0 px-6 pt-4">
            <TabsList className="w-full">
              <TabsTrigger value="providers" className="flex-1 gap-1.5">
                <Server className="size-3.5" />
                供应商
              </TabsTrigger>
              <TabsTrigger value="mcp" className="flex-1 gap-1.5">
                <Server className="size-3.5" />
                MCP
              </TabsTrigger>
              <TabsTrigger value="memory" className="flex-1 gap-1.5">
                <MemoryStick className="size-3.5" />
                记忆
              </TabsTrigger>
              <TabsTrigger value="data" className="flex-1 gap-1.5">
                <Database className="size-3.5" />
                数据
              </TabsTrigger>
              <TabsTrigger value="general" className="flex-1 gap-1.5">
                <Shield className="size-3.5" />
                通用
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="providers" className="mt-0 min-h-0 flex-1 overflow-hidden px-6 py-4">
            <div className="flex h-full gap-0 -mx-6 px-6">
              <div className="flex w-36 shrink-0 flex-col border-r pr-0">
                <div className="flex items-center justify-between pb-2">
                  <span className="text-xs font-medium text-muted-foreground">供应商列表</span>
                  <Button variant="ghost" size="icon-xs" className="size-5" onClick={handleAddProvider} title="添加供应商">
                    <Plus className="size-3" />
                  </Button>
                </div>
                <div className="flex-1 overflow-y-auto">
                  {draftProviders.map((provider, index) => {
                    const key = provider.id ?? `draft-${index}`;
                    const isSelected = selectedProviderIndex === index;
                    return (
                      <button
                        key={key}
                        type="button"
                        draggable
                        onDragStart={(event) => handleProviderDragStart(event, index)}
                        onDragOver={handleProviderDragOver}
                        onDrop={(event) => handleProviderDrop(event, index)}
                        onDragEnd={() => setDraggingProviderIndex(null)}
                        onClick={() => setSelectedProviderIndex(index)}
                        className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs transition-colors ${
                          isSelected
                            ? 'bg-primary/10 font-medium text-primary'
                            : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                        } ${draggingProviderIndex === index ? 'opacity-50 ring-1 ring-primary/30' : ''}`}
                      >
                        <GripVertical className="size-3 shrink-0 cursor-grab text-muted-foreground/70 active:cursor-grabbing" />
                        <Globe className="size-3 shrink-0" />
                        <span className="truncate">{provider.name || `供应商 ${index + 1}`}</span>
                        <Badge variant="secondary" className="ml-auto shrink-0 px-1 py-0 text-[10px]">
                          {provider.models.length}
                        </Badge>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="flex min-w-0 flex-1 flex-col overflow-y-auto pl-4">
                {draftProviders.length === 0 ? (
                  <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                    暂无供应商，点击左侧 + 添加
                  </div>
                ) : (
                  (() => {
                    const index = Math.min(selectedProviderIndex, draftProviders.length - 1);
                    const provider = draftProviders[index];
                    const key = provider.id ?? `draft-${index}`;
                    const isRefreshing = refreshingId === key;
                    const isKeyVisible = visibleKeys.has(key);
                    const isConfirmingDelete = deleteConfirmId === key;
                    const providerTestModel = provider.models.find((model) => model.id.trim())?.id ?? null;
                    const providerTestKey = `${key}::${providerTestModel ?? 'list'}`;
                    const isTestingProvider = modelTestingId === providerTestKey;
                    const interfaceMode =
                      provider.provider?.trim() === 'anthropic'
                        ? 'anthropic'
                        : provider.apiMode ?? 'chat_completions';
                    const isAnthropicProvider = interfaceMode === 'anthropic';

                    return (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <p className="text-sm text-muted-foreground">
                            <code className="text-[11px]">Base URL</code> 只填公共前缀，后端会按模式自动补路径
                          </p>
                          <div className="flex items-center gap-1.5">
                            <Button
                              variant="outline"
                              size="sm"
                              className="gap-1.5 h-7 text-xs"
                              onClick={() => void handleTestModelConnection(provider, index, providerTestModel)}
                              disabled={isTestingProvider}
                            >
                              <CheckCircle2 className={`size-3 ${isTestingProvider ? 'animate-pulse' : ''}`} />
                              {isTestingProvider ? '测试中...' : '测试连接'}
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              className="gap-1.5 h-7 text-xs"
                              onClick={() => void handleDiscoverModels(provider, index)}
                              disabled={isRefreshing}
                            >
                              <RefreshCcw className={`size-3 ${isRefreshing ? 'animate-spin' : ''}`} />
                              拉取模型
                            </Button>
                            {isConfirmingDelete ? (
                              <div className="flex items-center gap-1">
                                <Button
                                  variant="destructive"
                                  size="sm"
                                  className="h-7 gap-1 px-2 text-xs"
                                  onClick={() => handleDeleteProvider(index)}
                                >
                                  确认
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="h-7 gap-1 px-2 text-xs"
                                  onClick={() => setDeleteConfirmId(null)}
                                >
                                  取消
                                </Button>
                              </div>
                            ) : (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 gap-1 text-xs text-muted-foreground"
                                onClick={() => setDeleteConfirmId(key)}
                              >
                                <Trash2 className="size-3" />
                                删除
                              </Button>
                            )}
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                              <Server className="size-2.5" />
                              名称
                            </label>
                            <Input
                              value={provider.name}
                              onChange={(e) => updateProvider(index, { name: e.target.value })}
                              placeholder="OpenRouter 主账号"
                              className="h-7 text-xs"
                            />
                          </div>
                          <div className="space-y-1">
                            <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                              <Globe className="size-2.5" />
                              Base URL
                            </label>
                            <Input
                              value={provider.baseUrl}
                              onChange={(e) => updateProvider(index, { baseUrl: e.target.value })}
                              placeholder={isAnthropicProvider ? 'https://api.anthropic.com' : 'https://api.openai.com/v1'}
                              className="h-7 text-xs"
                            />
                          </div>
                        </div>

                        <div className="space-y-1">
                          <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                            <Server className="size-2.5" />
                            接口模式
                          </label>
                          <Select
                            value={interfaceMode}
                            onValueChange={(value) =>
                              updateProvider(index, {
                                provider:
                                  value === 'anthropic'
                                    ? 'anthropic'
                                    : provider.provider === 'anthropic'
                                      ? null
                                      : provider.provider,
                                apiMode:
                                  value === 'responses'
                                    ? 'responses'
                                    : 'chat_completions',
                              })
                            }
                          >
                            <SelectTrigger className="h-7 w-full text-xs">
                              <SelectValue placeholder="选择接口模式" />
                            </SelectTrigger>
                            <SelectContent align="start">
                              <SelectItem value="chat_completions">OpenAI 兼容 /chat/completions</SelectItem>
                              <SelectItem value="responses">OpenAI /responses</SelectItem>
                              <SelectItem value="anthropic">Anthropic /messages</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>

                        <div className="space-y-1">
                          <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                            <Key className="size-2.5" />
                            API Key
                          </label>
                          <div className="relative">
                            <Input
                              type={isKeyVisible ? 'text' : 'password'}
                              value={provider.apiKey}
                              onChange={(e) => updateProvider(index, { apiKey: e.target.value })}
                              placeholder="sk-..."
                              className="h-7 pr-8 text-xs"
                            />
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              className="absolute top-1/2 right-1 -translate-y-1/2 size-5"
                              onClick={() => toggleKeyVisibility(key)}
                            >
                              {isKeyVisible ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
                            </Button>
                          </div>
                        </div>

                        <div className="space-y-1">
                          <div className="flex items-center justify-between gap-2">
                            <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                              <List className="size-2.5" />
                              模型
                            </label>
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-6 gap-1 px-2 text-[11px]"
                              onClick={() => addProviderModel(index)}
                            >
                              <Plus className="size-3" />
                              添加
                            </Button>
                          </div>
                          <div className="max-h-[360px] overflow-y-auto rounded-md border bg-background/70 p-2">
                            {provider.models.length === 0 ? (
                              <div className="flex h-20 items-center justify-center text-xs text-muted-foreground">
                                暂无模型，点击添加或拉取模型
                              </div>
                            ) : (
                              <div className="space-y-2">
                                {provider.models.map((model, modelIndex) => {
                                  const modelId = model.id.trim();
                                  const modelKey = `${key}::${modelId || `model-${modelIndex}`}`;
                                  const isTestingModel = modelTestingId === modelKey;
                                  const testResult = modelTestResults[modelKey];
                                  const inputModalities = compactStringList(model.inputModalities);
                                  const outputModalities = compactStringList(model.outputModalities);
                                  const capabilities = compactStringList(model.capabilities);
                                  const supportedParameters = compactStringList(model.supportedParameters);
                                  const promptPrice = model.pricing?.prompt ?? model.pricing?.input;
                                  const completionPrice = model.pricing?.completion ?? model.pricing?.output;
                                  const visibleCapabilities = capabilities.slice(0, 6);
                                  const visibleInputModalities = inputModalities.length ? inputModalities : ['text'];
                                  const visibleOutputModalities = outputModalities.length ? outputModalities : ['text'];
                                  const modelEditKey = `${provider.id ?? `draft-${index}`}::model-${modelIndex}`;
                                  const isEditingModel = editingModelKeys.has(modelEditKey) || !modelId;
                                  const visiblePreviewCapabilities = visibleCapabilities.length
                                    ? visibleCapabilities
                                    : supportedParameters.includes('tools')
                                      ? ['tools']
                                      : ['basic_text'];

                                  return (
                                    <div key={modelIndex} className="rounded-md border bg-card p-3">
                                      <div className="flex items-start gap-2">
                                        <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border bg-emerald-500/10 text-emerald-600 dark:text-emerald-300">
                                          <Server className="size-3.5" />
                                        </div>
                                        <div className="min-w-0 flex-1 space-y-1.5">
                                          <div className="min-w-0">
                                            <div className="truncate text-sm font-semibold">
                                              {model.name || modelId || '未命名模型'}
                                            </div>
                                            <div className="truncate font-mono text-xs text-muted-foreground">
                                              {modelId || 'model-id'}
                                            </div>
                                          </div>
                                          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
                                            <span>{formatTokenCount(model.contextWindow)} ctx</span>
                                            <span>{formatTokenCount(model.maxOutputTokens)} out</span>
                                            <span className="inline-flex items-center gap-1">
                                              <CircleDollarSign className="size-3" />
                                              {formatPricePerMillion(promptPrice)} in /{' '}
                                              {formatPricePerMillion(completionPrice)} out per 1M
                                            </span>
                                          </div>
                                          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                            <ModelMetadataPreviewBadges
                                              label="输入"
                                              values={visibleInputModalities}
                                              options={MODEL_MODALITY_OPTIONS}
                                              getLabel={modalityLabel}
                                            />
                                            <ModelMetadataPreviewBadges
                                              label="输出"
                                              values={visibleOutputModalities}
                                              options={MODEL_MODALITY_OPTIONS}
                                              getLabel={modalityLabel}
                                            />
                                            <ModelMetadataPreviewBadges
                                              label="能力"
                                              values={visiblePreviewCapabilities}
                                              options={MODEL_CAPABILITY_PREVIEW_OPTIONS}
                                              getLabel={capabilityLabel}
                                            />
                                            <ModelMetadataPreviewBadges
                                              label="参数"
                                              values={supportedParameters}
                                              options={MODEL_PARAMETER_OPTIONS}
                                              getLabel={(value) =>
                                                MODEL_PARAMETER_OPTIONS.find((option) => option.value === value)
                                                  ?.label ?? value
                                              }
                                            />
                                          </div>
                                        </div>
                                        <div className="flex shrink-0 items-center gap-1">
                                          <Button
                                            variant="ghost"
                                            size="icon-xs"
                                            className="size-7 text-muted-foreground"
                                            onClick={() => void handleTestModelConnection(provider, index, model.id)}
                                            disabled={isTestingModel}
                                            title="测试这个模型"
                                          >
                                            <CheckCircle2
                                              className={`size-3 ${isTestingModel ? 'animate-pulse' : ''}`}
                                            />
                                          </Button>
                                          <Button
                                            variant="ghost"
                                            size="icon-xs"
                                            className="size-7 text-muted-foreground"
                                            onClick={() => toggleModelEditing(modelEditKey)}
                                            title={isEditingModel ? '收起详情' : '编辑详情'}
                                          >
                                            <Settings2 className="size-3" />
                                          </Button>
                                          <Button
                                            variant="ghost"
                                            size="icon-xs"
                                            className="size-7 text-muted-foreground"
                                            onClick={() => removeProviderModel(index, modelIndex)}
                                            title="删除模型"
                                          >
                                            <Trash2 className="size-3" />
                                          </Button>
                                        </div>
                                      </div>

                                      {isEditingModel ? (
                                        <div className="mt-3 space-y-2 rounded-md border bg-background/70 p-3">
                                          <div className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] gap-2">
                                            <label className="space-y-1">
                                              <span className="text-[10px] text-muted-foreground">模型 ID</span>
                                              <Input
                                                value={model.id}
                                                onChange={(event) =>
                                                  updateProviderModel(index, modelIndex, { id: event.target.value })
                                                }
                                                placeholder="model-id"
                                                className="h-7 px-2 font-mono text-[11px]"
                                              />
                                            </label>
                                            <label className="space-y-1">
                                              <span className="text-[10px] text-muted-foreground">显示名</span>
                                              <Input
                                                value={model.name ?? ''}
                                                onChange={(event) =>
                                                  updateProviderModel(index, modelIndex, {
                                                    name: event.target.value || null,
                                                  })
                                                }
                                                placeholder="可选"
                                                className="h-7 px-2 text-[11px]"
                                              />
                                            </label>
                                          </div>
                                          <div className="grid grid-cols-2 gap-2">
                                            <label className="space-y-1">
                                              <span className="text-[10px] text-muted-foreground">上下文</span>
                                              <Input
                                                type="number"
                                                min={1}
                                                value={model.contextWindow ?? ''}
                                                onChange={(event) =>
                                                  updateProviderModel(index, modelIndex, {
                                                    contextWindow: event.target.value
                                                      ? Number(event.target.value)
                                                      : null,
                                                  })
                                                }
                                                className="h-7 px-2 text-right font-mono text-[11px]"
                                              />
                                            </label>
                                            <label className="space-y-1">
                                              <span className="text-[10px] text-muted-foreground">最大输出</span>
                                              <Input
                                                type="number"
                                                min={1}
                                                value={model.maxOutputTokens ?? ''}
                                                onChange={(event) =>
                                                  updateProviderModel(index, modelIndex, {
                                                    maxOutputTokens: event.target.value
                                                      ? Number(event.target.value)
                                                      : null,
                                                  })
                                                }
                                                className="h-7 px-2 text-right font-mono text-[11px]"
                                              />
                                            </label>
                                          </div>
                                          <div className="grid grid-cols-2 gap-2">
                                            <label className="space-y-1">
                                              <span className="text-[10px] text-muted-foreground">输入类型</span>
                                              <ModelMetadataTagSelect
                                                values={inputModalities}
                                                options={MODEL_MODALITY_OPTIONS}
                                                getLabel={modalityLabel}
                                                placeholder="选择输入类型"
                                                onChange={(values) =>
                                                  updateProviderModel(index, modelIndex, {
                                                    inputModalities: values,
                                                  })
                                                }
                                              />
                                            </label>
                                            <label className="space-y-1">
                                              <span className="text-[10px] text-muted-foreground">输出类型</span>
                                              <ModelMetadataTagSelect
                                                values={outputModalities}
                                                options={MODEL_MODALITY_OPTIONS}
                                                getLabel={modalityLabel}
                                                placeholder="选择输出类型"
                                                onChange={(values) =>
                                                  updateProviderModel(index, modelIndex, {
                                                    outputModalities: values,
                                                  })
                                                }
                                              />
                                            </label>
                                          </div>
                                          <div className="grid grid-cols-2 gap-2">
                                            <label className="space-y-1">
                                              <span className="text-[10px] text-muted-foreground">能力</span>
                                              <ModelMetadataTagSelect
                                                values={capabilities}
                                                options={MODEL_CAPABILITY_OPTIONS}
                                                getLabel={capabilityLabel}
                                                placeholder="选择模型能力"
                                                onChange={(values) =>
                                                  updateProviderModel(index, modelIndex, {
                                                    capabilities: values,
                                                  })
                                                }
                                              />
                                            </label>
                                            <label className="space-y-1">
                                              <span className="text-[10px] text-muted-foreground">支持参数</span>
                                              <ModelMetadataTagSelect
                                                values={supportedParameters}
                                                options={MODEL_PARAMETER_OPTIONS}
                                                getLabel={(value) =>
                                                  MODEL_PARAMETER_OPTIONS.find((option) => option.value === value)
                                                    ?.label ?? value
                                                }
                                                placeholder="选择支持参数"
                                                onChange={(values) =>
                                                  updateProviderModel(index, modelIndex, {
                                                    supportedParameters: values,
                                                  })
                                                }
                                              />
                                            </label>
                                          </div>
                                        </div>
                                      ) : null}

                                      {testResult ? (
                                        <div
                                          className={`mt-3 flex items-start gap-2 rounded-md border px-2.5 py-2 text-[11px] ${
                                            testResult.ok
                                              ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                                              : 'border-destructive/25 bg-destructive/5 text-destructive'
                                          }`}
                                        >
                                          {testResult.ok ? (
                                            <CheckCircle2 className="mt-0.5 size-3 shrink-0" />
                                          ) : (
                                            <XCircle className="mt-0.5 size-3 shrink-0" />
                                          )}
                                          <div className="min-w-0">
                                            <div className="break-words">{testResult.message}</div>
                                            {testResult.responsePreview ? (
                                              <div className="mt-1 truncate font-mono opacity-80">
                                                {testResult.responsePreview}
                                              </div>
                                            ) : null}
                                          </div>
                                        </div>
                                      ) : null}
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })()
                )}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="mcp" className="mt-0 min-h-0 flex-1 overflow-hidden px-6 py-4">
            <div className="flex h-full gap-0 -mx-6 px-6">
              <div className="flex w-40 shrink-0 flex-col border-r pr-0">
                <div className="flex items-center justify-between pb-2">
                  <span className="text-xs font-medium text-muted-foreground">MCP Servers</span>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    className="size-5"
                    onClick={handleAddMcpServer}
                    title="添加 MCP server"
                  >
                    <Plus className="size-3" />
                  </Button>
                </div>
                <div className="flex-1 overflow-y-auto">
                  {draftMcpServers.length === 0 ? (
                    <div className="px-2 py-6 text-center text-xs text-muted-foreground">
                      暂无 MCP server
                    </div>
                  ) : (
                    draftMcpServers.map((server, index) => {
                      const key = server.id ?? `draft-mcp-${index}`;
                      const isSelected = selectedMcpIndex === index;
                      const statusState = server.status?.state ?? 'unknown';
                      const dotClass =
                        statusState === 'ok'
                          ? 'bg-emerald-500'
                          : statusState === 'error'
                            ? 'bg-destructive'
                            : 'bg-muted-foreground/40';
                      return (
                        <button
                          key={key}
                          type="button"
                          onClick={() => setSelectedMcpIndex(index)}
                          className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs transition-colors ${
                            isSelected
                              ? 'bg-primary/10 font-medium text-primary'
                              : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                          }`}
                        >
                          <span className={`size-1.5 shrink-0 rounded-full ${dotClass}`} />
                          <Server className="size-3 shrink-0" />
                          <span className="truncate">{server.name || `MCP ${index + 1}`}</span>
                          {!server.enabled ? (
                            <Badge variant="outline" className="ml-auto shrink-0 px-1 py-0 text-[10px]">
                              off
                            </Badge>
                          ) : server.status?.toolCount != null ? (
                            <Badge variant="secondary" className="ml-auto shrink-0 px-1 py-0 text-[10px]">
                              {server.status.toolCount}
                            </Badge>
                          ) : null}
                        </button>
                      );
                    })
                  )}
                </div>
              </div>

              <div className="flex min-w-0 flex-1 flex-col overflow-y-auto pl-4">
                {draftMcpServers.length === 0 ? (
                  <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed bg-muted/20 text-sm text-muted-foreground">
                    点击左侧 + 添加一个 MCP server
                  </div>
                ) : (
                  (() => {
                    const index = Math.min(selectedMcpIndex, draftMcpServers.length - 1);
                    const server = draftMcpServers[index];
                    const key = server.id ?? `draft-mcp-${index}`;
                    const bearerKey = `${key}-bearer`;
                    const isBearerVisible = visibleKeys.has(bearerKey);
                    const isTesting = mcpTestingId === key;
                    const isConfirmingDelete = deleteMcpConfirmId === key;
                    const testResult = mcpTestResults[key];
                    const statusState = server.status?.state ?? 'unknown';
                    const statusText =
                      server.status?.message ||
                      (statusState === 'ok'
                        ? '连接可用'
                        : statusState === 'error'
                          ? '连接失败'
                          : '尚未测试');

                    return (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <Switch
                                checked={server.enabled}
                                onCheckedChange={(enabled) => updateMcpServer(index, { enabled })}
                              />
                              <span className="text-sm font-medium">
                                {server.enabled ? '已启用' : '已停用'}
                              </span>
                              <Badge
                                variant={statusState === 'ok' ? 'secondary' : statusState === 'error' ? 'destructive' : 'outline'}
                                className="text-[10px]"
                              >
                                {statusText}
                              </Badge>
                            </div>
                          </div>
                          <div className="flex shrink-0 items-center gap-1.5">
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 gap-1.5 text-xs"
                              onClick={() => void handleTestMcpServer(server, index)}
                              disabled={isTesting}
                            >
                              <RefreshCcw className={`size-3 ${isTesting ? 'animate-spin' : ''}`} />
                              {isTesting ? '测试中...' : '测试连接'}
                            </Button>
                            {isConfirmingDelete ? (
                              <div className="flex items-center gap-1">
                                <Button
                                  variant="destructive"
                                  size="sm"
                                  className="h-7 px-2 text-xs"
                                  onClick={() => handleDeleteMcpServer(index)}
                                >
                                  确认
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="h-7 px-2 text-xs"
                                  onClick={() => setDeleteMcpConfirmId(null)}
                                >
                                  取消
                                </Button>
                              </div>
                            ) : (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 gap-1 text-xs text-muted-foreground"
                                onClick={() => setDeleteMcpConfirmId(key)}
                              >
                                <Trash2 className="size-3" />
                                删除
                              </Button>
                            )}
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                              <Server className="size-2.5" />
                              名称
                            </label>
                            <Input
                              value={server.name}
                              onChange={(e) => updateMcpServer(index, { name: e.target.value })}
                              placeholder="filesystem"
                              className="h-7 text-xs"
                            />
                          </div>
                          <div className="space-y-1">
                            <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                              <Globe className="size-2.5" />
                              传输
                            </label>
                            <Select
                              value={server.transport}
                              onValueChange={(transport) =>
                                updateMcpServer(index, {
                                  transport: transport as 'stdio' | 'streamable_http',
                                })
                              }
                            >
                              <SelectTrigger className="h-7 text-xs">
                                <SelectValue placeholder="选择传输方式" />
                              </SelectTrigger>
                              <SelectContent align="start">
                                <SelectItem value="stdio">stdio 本地进程</SelectItem>
                                <SelectItem value="streamable_http">Streamable HTTP</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                        </div>

                        {server.transport === 'stdio' ? (
                          <>
                            <div className="space-y-1">
                              <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                                <CodeXml className="size-2.5" />
                                Command
                              </label>
                              <Input
                                value={server.command}
                                onChange={(e) => updateMcpServer(index, { command: e.target.value })}
                                placeholder="npx"
                                className="h-7 font-mono text-xs"
                              />
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                              <div className="space-y-1">
                                <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                                  <List className="size-2.5" />
                                  Args
                                </label>
                                <Textarea
                                  value={server.argsText}
                                  onChange={(e) => updateMcpServer(index, { argsText: e.target.value })}
                                  className="min-h-[80px] font-mono text-[11px] leading-snug"
                                  placeholder={'每行一个参数\n-y\n@modelcontextprotocol/server-filesystem\nD:\\\\workspace'}
                                />
                              </div>
                              <div className="space-y-1">
                                <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                                  <Key className="size-2.5" />
                                  Env
                                </label>
                                <Textarea
                                  value={server.envText}
                                  onChange={(e) => updateMcpServer(index, { envText: e.target.value })}
                                  className="min-h-[80px] font-mono text-[11px] leading-snug"
                                  placeholder={'KEY=value\nTOKEN=...'}
                                />
                              </div>
                            </div>
                          </>
                        ) : (
                          <>
                            <div className="space-y-1">
                              <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                                <Globe className="size-2.5" />
                                URL
                              </label>
                              <Input
                                value={server.url}
                                onChange={(e) => updateMcpServer(index, { url: e.target.value })}
                                placeholder="https://example.com/mcp"
                                className="h-7 text-xs"
                              />
                            </div>
                            <div className="space-y-1">
                              <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                                <Key className="size-2.5" />
                                Bearer Token
                              </label>
                              <div className="relative">
                                <Input
                                  type={isBearerVisible ? 'text' : 'password'}
                                  value={server.bearerToken}
                                  onChange={(e) => updateMcpServer(index, { bearerToken: e.target.value })}
                                  placeholder="可选"
                                  className="h-7 pr-8 text-xs"
                                />
                                <Button
                                  variant="ghost"
                                  size="icon-xs"
                                  className="absolute top-1/2 right-1 size-5 -translate-y-1/2"
                                  onClick={() => toggleKeyVisibility(bearerKey)}
                                >
                                  {isBearerVisible ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
                                </Button>
                              </div>
                            </div>
                            <div className="space-y-1">
                              <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                                <List className="size-2.5" />
                                Headers
                              </label>
                              <Textarea
                                value={server.headersText}
                                onChange={(e) => updateMcpServer(index, { headersText: e.target.value })}
                                className="min-h-[72px] font-mono text-[11px] leading-snug"
                                placeholder={'X-API-Key=value\nX-Org=team'}
                              />
                            </div>
                          </>
                        )}

                        {(testResult?.tools?.length ?? 0) > 0 ? (
                          <div className="rounded-lg border bg-card p-3">
                            <div className="mb-2 flex items-center justify-between">
                              <span className="text-xs font-medium">发现的工具</span>
                              <Badge variant="secondary" className="text-[10px]">
                                {testResult.toolCount}
                              </Badge>
                            </div>
                            <div className="space-y-1.5">
                              {testResult.tools.slice(0, 8).map((tool) => (
                                <div key={tool.name} className="flex items-start gap-2 text-xs">
                                  <code className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px]">
                                    {tool.name}
                                  </code>
                                  <span className="line-clamp-2 text-muted-foreground">
                                    {tool.description || '无描述'}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}

                        {mcpConfigPath ? (
                          <div className="flex items-center gap-2 rounded-lg border bg-card p-3">
                            <Server className="size-3.5 text-muted-foreground" />
                            <span className="truncate text-xs text-muted-foreground">{mcpConfigPath}</span>
                          </div>
                        ) : null}
                      </div>
                    );
                  })()
                )}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="memory" className="mt-0 min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <div className="space-y-4">
              <div className="flex items-center gap-6">
                <label className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={draftSettings.memory?.enabled ?? true}
                    onCheckedChange={(enabled) =>
                      setDraftSettings((prev) => ({
                        ...prev,
                        memory: {
                          enabled,
                          autoLearn: prev.memory?.autoLearn ?? true,
                          global: prev.memory?.global ?? [],
                          workspaces: prev.memory?.workspaces ?? {},
                        },
                      }))
                    }
                  />
                  <span className="font-medium">启用记忆</span>
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={draftSettings.memory?.autoLearn ?? true}
                    onCheckedChange={(autoLearn) =>
                      setDraftSettings((prev) => ({
                        ...prev,
                        memory: {
                          enabled: prev.memory?.enabled ?? true,
                          autoLearn,
                          global: prev.memory?.global ?? [],
                          workspaces: prev.memory?.workspaces ?? {},
                        },
                      }))
                    }
                  />
                  <span className="font-medium">自动学习</span>
                </label>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">全局</h3>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 gap-1 px-2 text-xs text-muted-foreground"
                    onClick={() => addMemoryItem('global')}
                  >
                    <Plus className="size-3" />
                    添加
                  </Button>
                </div>
                {(draftSettings.memory?.global ?? []).length === 0 ? (
                  <div className="rounded-md border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">
                    暂无全局记忆
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {(draftSettings.memory?.global ?? []).map((item) => (
                      <div
                        key={item.id}
                        className={`group relative rounded-md border px-3 py-2 transition-colors ${
                          item.enabled ? 'bg-card' : 'bg-muted/30 opacity-60'
                        }`}
                      >
                        <div className="flex items-start gap-2">
                          <Textarea
                            value={item.content}
                            onChange={(e) => updateMemoryItem('global', item.id, { content: e.target.value })}
                            placeholder="例如：除非明确允许，不要主动运行 pnpm build。"
                            className="min-h-[20px] flex-1 resize-none overflow-hidden border-0 bg-transparent p-0 text-xs leading-relaxed shadow-none focus-visible:ring-0"
                            rows={1}
                            onInput={(e) => {
                              const el = e.currentTarget;
                              el.style.height = 'auto';
                              el.style.height = el.scrollHeight + 'px';
                            }}
                          />
                        </div>
                        <div className="mt-1 flex items-center justify-between">
                          <span className="text-[10px] text-muted-foreground/60">
                            {item.sourcePreview || '手动添加'}
                          </span>
                          <div className="flex items-center gap-1.5 opacity-0 transition-opacity group-hover:opacity-100">
                            <Switch
                              checked={item.enabled}
                              onCheckedChange={(enabled) => updateMemoryItem('global', item.id, { enabled })}
                              className="scale-75"
                            />
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              className="size-5 text-muted-foreground"
                              onClick={() => deleteMemoryItem('global', item.id)}
                              title="删除"
                            >
                              <Trash2 className="size-2.5" />
                            </Button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <Separator />

              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0 flex items-center gap-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">工作区</h3>
                    <span className="truncate text-[10px] text-muted-foreground/60" title={currentWorkspaceKey}>
                      {currentWorkspaceKey || '未选择'}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 gap-1 px-2 text-xs text-muted-foreground"
                    onClick={() => addMemoryItem('workspace')}
                    disabled={!currentWorkspaceKey}
                  >
                    <Plus className="size-3" />
                    添加
                  </Button>
                </div>
                {workspaceMemoryItems.length === 0 ? (
                  <div className="rounded-md border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">
                    暂无工作区记忆
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {workspaceMemoryItems.map((item) => (
                      <div
                        key={item.id}
                        className={`group relative rounded-md border px-3 py-2 transition-colors ${
                          item.enabled ? 'bg-card' : 'bg-muted/30 opacity-60'
                        }`}
                      >
                        <div className="flex items-start gap-2">
                          <Textarea
                            value={item.content}
                            onChange={(e) => updateMemoryItem('workspace', item.id, { content: e.target.value })}
                            placeholder="例如：这个项目里优先沿用现有 shadcn 风格。"
                            className="min-h-[20px] flex-1 resize-none overflow-hidden border-0 bg-transparent p-0 text-xs leading-relaxed shadow-none focus-visible:ring-0"
                            rows={1}
                            onInput={(e) => {
                              const el = e.currentTarget;
                              el.style.height = 'auto';
                              el.style.height = el.scrollHeight + 'px';
                            }}
                          />
                        </div>
                        <div className="mt-1 flex items-center justify-between">
                          <span className="text-[10px] text-muted-foreground/60">
                            {item.sourcePreview || '手动添加'}
                          </span>
                          <div className="flex items-center gap-1.5 opacity-0 transition-opacity group-hover:opacity-100">
                            <Switch
                              checked={item.enabled}
                              onCheckedChange={(enabled) => updateMemoryItem('workspace', item.id, { enabled })}
                              className="scale-75"
                            />
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              className="size-5 text-muted-foreground"
                              onClick={() => deleteMemoryItem('workspace', item.id)}
                              title="删除"
                            >
                              <Trash2 className="size-2.5" />
                            </Button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="data" className="mt-0 min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold">Session 数据</h3>
                  <p className="text-xs text-muted-foreground">
                    {sessionStorage
                      ? `更新于 ${formatStorageTime(sessionStorage.generatedAt)}`
                      : '统计 Session 历史、消息、工具调用和产物'}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-1.5 text-xs"
                  onClick={() => void loadSessionStorage()}
                  disabled={isLoadingSessionStorage}
                >
                  <RefreshCcw className={`size-3 ${isLoadingSessionStorage ? 'animate-spin' : ''}`} />
                  刷新
                </Button>
              </div>

              <div className="grid grid-cols-4 gap-2">
                {[
                  { label: 'Session', value: sessionStorage?.totalSessions ?? 0, icon: Database },
                  { label: '消息', value: sessionStorage?.totalMessages ?? 0, icon: FileText },
                  { label: '工具调用', value: sessionStorage?.totalToolCalls ?? 0, icon: Wrench },
                  { label: '产物', value: sessionStorage?.totalArtifacts ?? 0, icon: HardDrive },
                ].map((item) => {
                  const Icon = item.icon;
                  return (
                    <div key={item.label} className="rounded-lg border bg-card p-3">
                      <div className="mb-2 flex items-center justify-between">
                        <span className="text-[11px] text-muted-foreground">{item.label}</span>
                        <Icon className="size-3 text-muted-foreground" />
                      </div>
                      <div className="text-xl font-semibold tabular-nums">{item.value.toLocaleString()}</div>
                    </div>
                  );
                })}
              </div>

              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                <div className="space-y-4">
                  <div className="rounded-lg border bg-card p-4">
                    <div className="mb-4 flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-1.5 text-sm font-medium">
                          <PieChart className="size-3.5" />
                          数据占比
                        </div>
                        <div className="text-xs text-muted-foreground">
                          DB {formatStorageBytes(sessionStorage?.databaseBytes)} · Artifacts {formatStorageBytes(sessionStorage?.totalArtifactBytes)}
                        </div>
                      </div>
                      <Badge variant="secondary" className="text-[10px]">
                        {sessionStorage?.activeSessions ?? 0} 活跃
                      </Badge>
                    </div>
                    <div className="grid gap-4 sm:grid-cols-[180px_minmax(0,1fr)]">
                      <div className="relative mx-auto size-40 rounded-full border bg-muted">
                        <div
                          className="absolute inset-0 rounded-full"
                          style={{ background: buildSessionPieGradient(storageDataKinds) }}
                        />
                        <div className="absolute inset-7 rounded-full border bg-background shadow-sm" />
                        <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                          <span className="text-xl font-semibold tabular-nums">
                            {(sessionStorage?.totalSessions ?? 0).toLocaleString()}
                          </span>
                          <span className="text-[11px] text-muted-foreground">sessions</span>
                        </div>
                      </div>
                      <div className="space-y-2">
                        {storageDataKinds.map((item, index) => {
                          const percent = storageWeightTotal
                            ? Math.round((item.weight / storageWeightTotal) * 100)
                            : 0;
                          return (
                            <div key={item.key} className="flex items-center gap-2 text-xs">
                              <span
                                className="size-2.5 rounded-full"
                                style={{ backgroundColor: SESSION_CHART_COLORS[index % SESSION_CHART_COLORS.length] }}
                              />
                              <span className="min-w-0 flex-1 truncate">{item.label}</span>
                              <span className="text-muted-foreground tabular-nums">{item.records.toLocaleString()}</span>
                              <span className="w-9 text-right tabular-nums">{percent}%</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="rounded-lg border bg-card p-4">
                      <div className="mb-3 flex items-center gap-1.5 text-sm font-medium">
                        <CalendarClock className="size-3.5" />
                        时间分布
                      </div>
                      <div className="space-y-2">
                        {(sessionStorage?.ageBuckets ?? []).map((bucket) => {
                          const total = Math.max(1, sessionStorage?.totalSessions ?? 0);
                          return (
                            <div key={bucket.key} className="space-y-1">
                              <div className="flex items-center justify-between text-xs">
                                <span>{bucket.label}</span>
                                <span className="text-muted-foreground tabular-nums">{bucket.count}</span>
                              </div>
                              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                                <div
                                  className="h-full rounded-full bg-primary"
                                  style={{ width: `${Math.round((bucket.count / total) * 100)}%` }}
                                />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    <div className="rounded-lg border bg-card p-4">
                      <div className="mb-3 flex items-center gap-1.5 text-sm font-medium">
                        <Globe className="size-3.5" />
                        工作区
                      </div>
                      <div className="space-y-2">
                        {topStorageWorkspaces.length === 0 ? (
                          <div className="text-xs text-muted-foreground">暂无 Session 数据</div>
                        ) : (
                          topStorageWorkspaces.map((item) => (
                            <div key={item.workspace} className="rounded-md bg-muted/60 px-2.5 py-2">
                              <div className="flex items-center justify-between gap-2 text-xs">
                                <span className="min-w-0 truncate font-medium">{item.workspace}</span>
                                <span className="shrink-0 tabular-nums">{item.sessionCount}</span>
                              </div>
                              <div className="mt-1 text-[10px] text-muted-foreground">
                                {item.messageCount.toLocaleString()} 消息 · {formatStorageTime(item.latestUpdatedAt)}
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="rounded-lg border bg-card p-4">
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5 text-sm font-medium">
                        <Eraser className="size-3.5" />
                        细分清理
                      </div>
                      {sessionStorage?.emptySessions ? (
                        <Badge variant="outline" className="text-[10px]">
                          {sessionStorage.emptySessions} 空 Session
                        </Badge>
                      ) : null}
                    </div>

                    <div className="space-y-3">
                      <div className="space-y-1.5">
                        <label className="text-[11px] font-medium text-muted-foreground">范围</label>
                        <Select
                          value={sessionCleanupMode}
                          onValueChange={(mode) => {
                            setSessionCleanupMode(mode as SessionCleanupRequest['mode']);
                            setSessionCleanupPreview(null);
                            setIsSessionCleanupArmed(false);
                          }}
                        >
                          <SelectTrigger className="h-8 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="older_than">按更新时间</SelectItem>
                            <SelectItem value="workspace">按工作区</SelectItem>
                            <SelectItem value="empty">空 Session</SelectItem>
                            <SelectItem value="all">全部历史 Session</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      {sessionCleanupMode === 'older_than' ? (
                        <div className="space-y-1.5">
                          <label className="text-[11px] font-medium text-muted-foreground">早于天数</label>
                          <Input
                            type="number"
                            min={1}
                            value={sessionCleanupDays}
                            onChange={(e) => {
                              setSessionCleanupDays(Math.max(1, Number(e.target.value) || 1));
                              setSessionCleanupPreview(null);
                              setIsSessionCleanupArmed(false);
                            }}
                            className="h-8 text-xs"
                          />
                        </div>
                      ) : null}

                      {sessionCleanupMode === 'workspace' ? (
                        <div className="space-y-1.5">
                          <label className="text-[11px] font-medium text-muted-foreground">工作区</label>
                          <Select
                            value={sessionCleanupWorkspace || undefined}
                            onValueChange={(workspace) => {
                              setSessionCleanupWorkspace(workspace);
                              setSessionCleanupPreview(null);
                              setIsSessionCleanupArmed(false);
                            }}
                          >
                            <SelectTrigger className="h-8 text-xs">
                              <SelectValue placeholder="选择工作区" />
                            </SelectTrigger>
                            <SelectContent>
                              {(sessionStorage?.workspaces ?? []).map((item) => (
                                <SelectItem key={item.workspace} value={item.workspace}>
                                  {item.workspace}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      ) : null}

                      <div className="rounded-md bg-muted/60 p-3">
                        {cleanupSummary ? (
                          <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                            <div>
                              <div className="text-muted-foreground">候选 Session</div>
                              <div className="font-semibold tabular-nums">{sessionCleanupPreview.candidateCount}</div>
                            </div>
                            <div>
                              <div className="text-muted-foreground">消息</div>
                              <div className="font-semibold tabular-nums">{cleanupSummary.messageCount.toLocaleString()}</div>
                            </div>
                            <div>
                              <div className="text-muted-foreground">工具调用</div>
                              <div className="font-semibold tabular-nums">{cleanupSummary.toolCallCount.toLocaleString()}</div>
                            </div>
                            <div>
                              <div className="text-muted-foreground">产物</div>
                              <div className="font-semibold tabular-nums">
                                {cleanupSummary.artifactCount.toLocaleString()} · {formatStorageBytes(cleanupSummary.artifactBytes)}
                              </div>
                            </div>
                          </div>
                        ) : (
                          <div className="text-xs text-muted-foreground">先预览候选，再执行清理</div>
                        )}
                      </div>

                      {sessionCleanupPreview?.protectedActiveCount ? (
                        <Alert className="py-2">
                          <AlertTriangle className="size-4" />
                          <AlertDescription className="text-xs">
                            已跳过 {sessionCleanupPreview.protectedActiveCount} 个活跃 Session
                          </AlertDescription>
                        </Alert>
                      ) : null}

                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-8 flex-1 gap-1.5 text-xs"
                          onClick={() => void handlePreviewSessionCleanup()}
                          disabled={isPreviewingSessionCleanup || isCleaningSessions}
                        >
                          <Search className={`size-3 ${isPreviewingSessionCleanup ? 'animate-pulse' : ''}`} />
                          预览
                        </Button>
                        <Button
                          variant={isSessionCleanupArmed ? 'destructive' : 'default'}
                          size="sm"
                          className="h-8 flex-1 gap-1.5 text-xs"
                          onClick={() => void handleRunSessionCleanup()}
                          disabled={
                            isPreviewingSessionCleanup ||
                            isCleaningSessions ||
                            Boolean(sessionCleanupPreview && sessionCleanupPreview.candidateCount <= 0)
                          }
                        >
                          <Trash2 className={`size-3 ${isCleaningSessions ? 'animate-pulse' : ''}`} />
                          {isCleaningSessions ? '清理中...' : isSessionCleanupArmed ? '确认清理' : '清理'}
                        </Button>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-lg border bg-card p-4">
                    <div className="mb-3 text-sm font-medium">候选预览</div>
                    <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
                      {(sessionCleanupPreview?.candidates ?? []).length === 0 ? (
                        <div className="text-xs text-muted-foreground">暂无候选</div>
                      ) : (
                        sessionCleanupPreview!.candidates.slice(0, 8).map((item) => (
                          <div key={item.sessionId} className="rounded-md border bg-background px-2.5 py-2">
                            <div className="flex items-center gap-2 text-xs">
                              <span className="min-w-0 flex-1 truncate font-medium">{item.title || item.sessionId}</span>
                              {item.isActive ? (
                                <Badge variant="secondary" className="text-[10px]">活跃</Badge>
                              ) : null}
                            </div>
                            <div className="mt-1 truncate text-[10px] text-muted-foreground">
                              {item.workspace} · {item.messageCount} 消息 · {formatStorageTime(item.updatedAt)}
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="general" className="mt-0 min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <div className="space-y-5">
              <div>
                <h3 className="mb-3 text-sm font-semibold">正文风格</h3>
                <div className="rounded-lg border bg-card p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-sky-500/10">
                      <Type className="size-4 text-sky-600 dark:text-sky-400" />
                    </div>
                    <div className="min-w-0 flex-1 space-y-3">
                      <div>
                        <div className="text-sm font-medium">全局正文字体</div>
                        <div className="text-xs text-muted-foreground">
                          影响聊天正文、面板正文和输入区域的基础字体观感
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1.5">
                          <label className="text-[11px] font-medium text-muted-foreground">
                            字体
                          </label>
                          <Select
                            value={draftSettings.bodyFontFamily}
                            onValueChange={(bodyFontFamily) =>
                              setDraftSettings((prev) => ({
                                ...prev,
                                bodyFontFamily,
                              }))
                            }
                          >
                            <SelectTrigger className="h-8 text-xs">
                              <SelectValue placeholder="选择字体" />
                            </SelectTrigger>
                            <SelectContent align="start">
                              {BODY_FONT_OPTIONS.map((option) => (
                                <SelectItem
                                  key={option.label}
                                  value={option.value}
                                  style={{ fontFamily: option.value }}
                                >
                                  {option.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-1.5">
                          <label className="text-[11px] font-medium text-muted-foreground">
                            字号
                          </label>
                          <Select
                            value={activeTextSize.label}
                            onValueChange={(label) => {
                              const nextSize =
                                BODY_TEXT_SIZE_OPTIONS.find(
                                  (option) => option.label === label,
                                ) ?? activeTextSize;
                              setDraftSettings((prev) => ({
                                ...prev,
                                bodyFontSize: nextSize.fontSize,
                                bodyLineHeight: nextSize.lineHeight,
                              }));
                            }}
                          >
                            <SelectTrigger className="h-8 text-xs">
                              <SelectValue placeholder="选择字号" />
                            </SelectTrigger>
                            <SelectContent align="start">
                              {BODY_TEXT_SIZE_OPTIONS.map((option) => (
                                <SelectItem key={option.label} value={option.label}>
                                  {option.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <div
                        className="rounded-md border bg-background/70 px-3 py-2 text-muted-foreground"
                        style={{
                          fontFamily: draftSettings.bodyFontFamily,
                          fontSize: draftSettings.bodyFontSize,
                          lineHeight: `${draftSettings.bodyLineHeight}px`,
                        }}
                      >
                        预览：SuperCode 正在使用这套正文风格。
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <Separator />

              <div>
                <h3 className="mb-3 text-sm font-semibold">代码 RAG 索引</h3>
                <div className="space-y-4 rounded-lg border bg-card p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3">
                      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-emerald-500/10">
                        <Brain className="size-4 text-emerald-600 dark:text-emerald-400" />
                      </div>
                      <div className="space-y-1">
                        <div className="text-sm font-medium">启用预索引语义检索</div>
                        <div className="text-xs text-muted-foreground">
                          启用后，后端会为工作区建立 embedding 索引，并把语义候选混入 grep_file 结果
                        </div>
                      </div>
                    </div>
                    <Switch
                      checked={draftSettings.embedding?.enabled ?? false}
                      onCheckedChange={(enabled) =>
                        setDraftSettings((prev) => ({
                          ...prev,
                          embedding: {
                            enabled,
                            baseUrl: prev.embedding?.baseUrl ?? '',
                            apiKey: prev.embedding?.apiKey ?? '',
                            model: prev.embedding?.model ?? '',
                          },
                        }))
                      }
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                        <Globe className="size-2.5" />
                        Embedding Base URL
                      </label>
                      <Input
                        value={draftSettings.embedding?.baseUrl ?? ''}
                        onChange={(e) =>
                          setDraftSettings((prev) => ({
                            ...prev,
                            embedding: {
                              enabled: prev.embedding?.enabled ?? false,
                              baseUrl: e.target.value,
                              apiKey: prev.embedding?.apiKey ?? '',
                              model: prev.embedding?.model ?? '',
                            },
                          }))
                        }
                        placeholder="https://api.openai.com/v1"
                        className="h-8 text-xs"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                        <Server className="size-2.5" />
                        Embedding Model
                      </label>
                      <Input
                        value={draftSettings.embedding?.model ?? ''}
                        onChange={(e) =>
                          setDraftSettings((prev) => ({
                            ...prev,
                            embedding: {
                              enabled: prev.embedding?.enabled ?? false,
                              baseUrl: prev.embedding?.baseUrl ?? '',
                              apiKey: prev.embedding?.apiKey ?? '',
                              model: e.target.value,
                            },
                          }))
                        }
                        placeholder="text-embedding-3-small"
                        className="h-8 text-xs"
                      />
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                      <Key className="size-2.5" />
                      Embedding API Key
                    </label>
                    <div className="relative">
                      <Input
                        type={isEmbeddingKeyVisible ? 'text' : 'password'}
                        value={draftSettings.embedding?.apiKey ?? ''}
                        onChange={(e) =>
                          setDraftSettings((prev) => ({
                            ...prev,
                            embedding: {
                              enabled: prev.embedding?.enabled ?? false,
                              baseUrl: prev.embedding?.baseUrl ?? '',
                              apiKey: e.target.value,
                              model: prev.embedding?.model ?? '',
                            },
                          }))
                        }
                        placeholder="sk-..."
                        className="h-8 pr-8 text-xs"
                      />
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        className="absolute top-1/2 right-1 size-5 -translate-y-1/2"
                        onClick={() => toggleKeyVisibility(embeddingKey)}
                      >
                        {isEmbeddingKeyVisible ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
                      </Button>
                    </div>
                  </div>

                  <div className="flex items-center justify-between gap-3 rounded-md border bg-background/60 px-3 py-2">
                    <div className="text-xs text-muted-foreground">
                      测试会请求一次 embeddings 接口，不会写入索引
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 gap-1.5 text-xs"
                      onClick={() => void handleTestEmbedding()}
                      disabled={isTestingEmbedding}
                    >
                      <RefreshCcw className={`size-3 ${isTestingEmbedding ? 'animate-spin' : ''}`} />
                      {isTestingEmbedding ? '测试中...' : '测试配置'}
                    </Button>
                  </div>
                </div>
              </div>

              <Separator />

              <div>
                <h3 className="mb-3 text-sm font-semibold">图片生成工具</h3>
                <div className="space-y-4 rounded-lg border bg-card p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3">
                      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-fuchsia-500/10">
                        <ImageIcon className="size-4 text-fuchsia-600 dark:text-fuchsia-400" />
                      </div>
                      <div className="space-y-1">
                        <div className="text-sm font-medium">启用 generate_image</div>
                        <div className="text-xs text-muted-foreground">
                          编码智能体可按 OpenAI Images API 协议生成图片，并保存到当前工作区
                        </div>
                      </div>
                    </div>
                    <Switch
                      checked={draftSettings.imageGeneration?.enabled ?? false}
                      onCheckedChange={(enabled) => updateImageGenerationSettings({ enabled })}
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                        <Globe className="size-2.5" />
                        Images Base URL
                      </label>
                      <Input
                        value={draftSettings.imageGeneration?.baseUrl ?? ''}
                        onChange={(e) => updateImageGenerationSettings({ baseUrl: e.target.value })}
                        placeholder="https://api.openai.com/v1"
                        className="h-8 text-xs"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                        <Server className="size-2.5" />
                        Image Model
                      </label>
                      <Input
                        value={draftSettings.imageGeneration?.model ?? ''}
                        onChange={(e) => updateImageGenerationSettings({ model: e.target.value })}
                        placeholder="gpt-image-1"
                        className="h-8 text-xs"
                      />
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                      <Key className="size-2.5" />
                      Images API Key
                    </label>
                    <div className="relative">
                      <Input
                        type={isImageGenerationKeyVisible ? 'text' : 'password'}
                        value={draftSettings.imageGeneration?.apiKey ?? ''}
                        onChange={(e) => updateImageGenerationSettings({ apiKey: e.target.value })}
                        placeholder="sk-..."
                        className="h-8 pr-8 text-xs"
                      />
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        className="absolute top-1/2 right-1 size-5 -translate-y-1/2"
                        onClick={() => toggleKeyVisibility(imageGenerationKey)}
                      >
                        {isImageGenerationKeyVisible ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
                      </Button>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                        <ImageIcon className="size-2.5" />
                        默认尺寸
                      </label>
                      <Input
                        value={draftSettings.imageGeneration?.size ?? '1024x1024'}
                        onChange={(e) => updateImageGenerationSettings({ size: e.target.value })}
                        placeholder="2048x2048"
                        className="h-8 text-xs"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                        <ShieldCheck className="size-2.5" />
                        默认质量
                      </label>
                      <Select
                        value={draftSettings.imageGeneration?.quality ?? 'auto'}
                        onValueChange={(quality) => updateImageGenerationSettings({ quality })}
                      >
                        <SelectTrigger className="h-8 text-xs">
                          <SelectValue placeholder="选择质量" />
                        </SelectTrigger>
                        <SelectContent align="start">
                          {IMAGE_QUALITY_OPTIONS.map((quality) => (
                            <SelectItem key={quality} value={quality}>
                              {quality}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </div>
              </div>

              <Separator />

              <div>
                <h3 className="mb-3 text-sm font-semibold">Tinyfish 联网工具</h3>
                <div className="space-y-4 rounded-lg border bg-card p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3">
                      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-cyan-500/10">
                        <Search className="size-4 text-cyan-600 dark:text-cyan-400" />
                      </div>
                      <div className="space-y-1">
                        <div className="text-sm font-medium">优先使用设置里的 Tinyfish</div>
                        <div className="text-xs text-muted-foreground">
                          启用后，plan agent 的 search_web / fetch_url_content 会使用这里的配置
                        </div>
                      </div>
                    </div>
                    <Switch
                      checked={draftSettings.tinyfish?.enabled ?? false}
                      onCheckedChange={(enabled) => updateTinyfishSettings({ enabled })}
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                        <Globe className="size-2.5" />
                        Search URL
                      </label>
                      <Input
                        value={draftSettings.tinyfish?.searchUrl ?? 'https://api.search.tinyfish.ai'}
                        onChange={(e) => updateTinyfishSettings({ searchUrl: e.target.value })}
                        placeholder="https://api.search.tinyfish.ai"
                        className="h-8 text-xs"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                        <Server className="size-2.5" />
                        Fetch URL
                      </label>
                      <Input
                        value={draftSettings.tinyfish?.fetchUrl ?? 'https://api.fetch.tinyfish.ai'}
                        onChange={(e) => updateTinyfishSettings({ fetchUrl: e.target.value })}
                        placeholder="https://api.fetch.tinyfish.ai"
                        className="h-8 text-xs"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-[1fr_140px] gap-3">
                    <div className="space-y-1.5">
                      <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                        <Key className="size-2.5" />
                        Tinyfish API Key
                      </label>
                      <div className="relative">
                        <Input
                          type={isTinyfishKeyVisible ? 'text' : 'password'}
                          value={draftSettings.tinyfish?.apiKey ?? ''}
                          onChange={(e) => updateTinyfishSettings({ apiKey: e.target.value })}
                          placeholder="sk-tinyfish-..."
                          className="h-8 pr-8 text-xs"
                        />
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          className="absolute top-1/2 right-1 size-5 -translate-y-1/2"
                          onClick={() => toggleKeyVisibility(tinyfishKey)}
                        >
                          {isTinyfishKeyVisible ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      <label className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                        <ShieldCheck className="size-2.5" />
                        超时秒数
                      </label>
                      <Input
                        type="number"
                        min={5}
                        value={draftSettings.tinyfish?.timeout ?? 30}
                        onChange={(e) =>
                          updateTinyfishSettings({
                            timeout: Math.max(5, Number(e.target.value) || 30),
                          })
                        }
                        className="h-8 text-xs"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <Separator />

              <div>
                <h3 className="mb-3 text-sm font-semibold">安全与确认</h3>
                <div className="space-y-4">
                  <div className="flex items-start justify-between gap-4 rounded-lg border bg-card p-4">
                    <div className="flex items-start gap-3">
                      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-amber-500/10">
                        <ShieldCheck className="size-4 text-amber-600 dark:text-amber-400" />
                      </div>
                      <div className="space-y-1">
                        <div className="text-sm font-medium">自动同意危险操作</div>
                        <div className="text-xs text-muted-foreground">
                          启用后，删除文件、提交代码、创建标签等操作将自动执行，无需人工审查确认
                        </div>
                      </div>
                    </div>
                    <Switch
                      checked={draftSettings.autoApprove}
                      onCheckedChange={(checked) =>
                        setDraftSettings((prev) => ({ ...prev, autoApprove: checked }))
                      }
                    />
                  </div>

                  {draftSettings.autoApprove && (
                    <Alert variant="destructive" className="border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-400">
                      <AlertTriangle className="size-4" />
                      <AlertDescription className="text-xs">
                        危险操作将自动执行，可能造成不可逆的文件删除或代码变更。请确保你信任当前 AI 代理的操作行为。
                      </AlertDescription>
                    </Alert>
                  )}
                </div>
              </div>

              <Separator />

              <div>
                <h3 className="mb-3 text-sm font-semibold">答复渲染</h3>
                <div className="space-y-4">
                  <div className="flex items-start justify-between gap-4 rounded-lg border bg-card p-4">
                    <div className="flex items-start gap-3">
                      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-sky-500/10">
                        <CodeXml className="size-4 text-sky-600 dark:text-sky-400" />
                      </div>
                      <div className="space-y-1">
                        <div className="text-sm font-medium">最终答复渲染方式</div>
                        <div className="text-xs text-muted-foreground">
                          HTML Artifacts 会在适合可视化或交互时嵌入独立预览，默认仍使用 Markdown
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Button
                        variant={draftSettings.finalAnswerRendering === 'markdown' ? 'default' : 'outline'}
                        size="sm"
                        className="h-7 px-2.5 text-xs"
                        onClick={() =>
                          setDraftSettings((prev) => ({ ...prev, finalAnswerRendering: 'markdown' }))
                        }
                      >
                        Markdown
                      </Button>
                      <Button
                        variant={draftSettings.finalAnswerRendering === 'html' ? 'default' : 'outline'}
                        size="sm"
                        className="h-7 px-2.5 text-xs"
                        onClick={() =>
                          setDraftSettings((prev) => ({ ...prev, finalAnswerRendering: 'html' }))
                        }
                      >
                        HTML
                      </Button>
                    </div>
                  </div>

                  <div className="flex items-start justify-between gap-4 rounded-lg border bg-card p-4">
                    <div className="flex items-start gap-3">
                      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-violet-500/10">
                        <Brain className="size-4 text-violet-600 dark:text-violet-400" />
                      </div>
                      <div className="space-y-1">
                        <div className="text-sm font-medium">思考过程渲染方式</div>
                        <div className="text-xs text-muted-foreground">
                          Markdown 模式支持代码高亮、数学公式等，但可能造成卡顿；纯文本模式更轻快
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Button
                        variant={draftSettings.thinkingRendering === 'text' ? 'default' : 'outline'}
                        size="sm"
                        className="h-7 px-2.5 text-xs"
                        onClick={() =>
                          setDraftSettings((prev) => ({ ...prev, thinkingRendering: 'text' }))
                        }
                      >
                        纯文本
                      </Button>
                      <Button
                        variant={draftSettings.thinkingRendering === 'markdown' ? 'default' : 'outline'}
                        size="sm"
                        className="h-7 px-2.5 text-xs"
                        onClick={() =>
                          setDraftSettings((prev) => ({ ...prev, thinkingRendering: 'markdown' }))
                        }
                      >
                        Markdown
                      </Button>
                    </div>
                  </div>
                </div>
              </div>

              <Separator />

              <div>
                <h3 className="mb-3 text-sm font-semibold">配置文件</h3>
                {configPath ? (
                  <div className="flex items-center gap-2 rounded-lg border bg-card p-3">
                    <Server className="size-3.5 text-muted-foreground" />
                    <span className="truncate text-xs text-muted-foreground">{configPath}</span>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">尚未生成可视化配置文件</p>
                )}
              </div>
            </div>
          </TabsContent>
        </Tabs>

        <Separator />

        <DialogFooter className="shrink-0 px-6 py-3">
          <div className="flex flex-1 items-center gap-3">
            {error ? (
              <span className="text-sm text-destructive">{error}</span>
            ) : feedback ? (
              <span className="text-sm text-emerald-600 dark:text-emerald-400">{feedback}</span>
            ) : null}
          </div>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
          <Button onClick={() => void handleSave()} disabled={isSaving} className="min-w-20">
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
