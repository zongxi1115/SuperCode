import { type DragEvent, useCallback, useEffect, useRef, useState } from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import type {
  AppSettings,
  MCPServerConfig,
  MCPServerTestResult,
  ModelOption,
  UIModelProvider,
} from '@/lib/app-types';
import {
  AlertTriangle,
  Brain,
  CodeXml,
  Eye,
  EyeOff,
  Globe,
  GripVertical,
  ImageIcon,
  Key,
  List,
  Lock,
  MemoryStick,
  Plus,
  RefreshCcw,
  Server,
  Settings2,
  Shield,
  ShieldCheck,
  Trash2,
  Type,
} from 'lucide-react';

type EditableProvider = UIModelProvider;

type EditableMCPServer = MCPServerConfig & {
  argsText: string;
  envText: string;
  headersText: string;
};

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

type SettingsDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  providers: UIModelProvider[];
  envConfigs: ModelOption[];
  configPath: string | null;
  mcpServers: MCPServerConfig[];
  mcpConfigPath: string | null;
  settings: AppSettings;
  currentWorkspace: string;
  onSaveProviders: (providers: UIModelProvider[]) => Promise<void>;
  onDiscoverModels: (provider: UIModelProvider) => Promise<{
    models: UIModelProvider['models'];
  }>;
  onSaveMcpServers: (servers: MCPServerConfig[]) => Promise<void>;
  onTestMcpServer: (server: MCPServerConfig) => Promise<MCPServerTestResult>;
  onTestEmbedding: (embedding: AppSettings['embedding']) => Promise<string>;
  onSaveSettings: (settings: AppSettings) => Promise<void>;
};

function createModelRecord() {
  return {
    id: '',
    contextWindow: 32_000,
  };
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

export function SettingsDialog({
  open,
  onOpenChange,
  providers,
  envConfigs,
  configPath,
  mcpServers,
  mcpConfigPath,
  settings,
  currentWorkspace,
  onSaveProviders,
  onDiscoverModels,
  onSaveMcpServers,
  onTestMcpServer,
  onTestEmbedding,
  onSaveSettings,
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
  const [mcpTestingId, setMcpTestingId] = useState<string | null>(null);
  const [isTestingEmbedding, setIsTestingEmbedding] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visibleKeys, setVisibleKeys] = useState<Set<string>>(new Set());
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [deleteMcpConfirmId, setDeleteMcpConfirmId] = useState<string | null>(null);
  const [selectedProviderIndex, setSelectedProviderIndex] = useState(0);
  const [selectedMcpIndex, setSelectedMcpIndex] = useState(0);
  const [draggingProviderIndex, setDraggingProviderIndex] = useState<number | null>(null);
  const [mcpTestResults, setMcpTestResults] = useState<Record<string, MCPServerTestResult>>({});
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
  const currentWorkspaceKey = currentWorkspace.trim();
  const workspaceMemoryItems =
    currentWorkspaceKey && draftSettings.memory?.workspaces
      ? draftSettings.memory.workspaces[currentWorkspaceKey] ?? []
      : [];

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
    setDeleteConfirmId(null);
    setDeleteMcpConfirmId(null);
    setMcpTestResults({});
    setIsSaving(false);
    setRefreshingId(null);
    setMcpTestingId(null);
    setIsTestingEmbedding(false);
    setFeedback(null);
    setError(null);
  }, [open, providers, mcpServers, settings]);

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

  const addProviderModel = (providerIndex: number) => {
    setDraftProviders((prev) =>
      prev.map((provider, index) =>
        index === providerIndex
          ? { ...provider, models: [...provider.models, createModelRecord()] }
          : provider,
      ),
    );
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
        id: provider.id ?? null,
        name: provider.name,
        baseUrl: provider.baseUrl,
        apiKey: provider.apiKey,
        models: provider.models,
        provider: provider.provider ?? null,
        apiMode: provider.apiMode ?? 'chat_completions',
      });
      if (!canUpdateAsyncState()) return;
      updateProvider(index, {
        models: catalog.models,
      });
      const contextCount = catalog.models.filter((model) => model.contextWindow).length;
      setFeedback(`已拉取 ${catalog.models.length} 个模型，缓存 ${contextCount} 个上下文窗口`);
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      setError(e instanceof Error ? e.message : '拉取模型失败');
    } finally {
      if (canUpdateAsyncState()) {
        setRefreshingId(null);
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
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      setError(e instanceof Error ? e.message : 'Embedding 测试失败');
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
      setFeedback(`MCP 连接成功，发现 ${result.toolCount} 个工具`);
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      const message = e instanceof Error ? e.message : 'MCP 连接测试失败';
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
      await onSaveProviders(
        draftProviders.map((p) => ({
          id: p.id ?? null,
          name: p.name.trim() || '未命名供应商',
          baseUrl: p.baseUrl.trim(),
          apiKey: p.apiKey.trim(),
          models: p.models
            .map((model) => ({
              id: model.id.trim(),
              contextWindow: model.contextWindow ?? null,
            }))
            .filter((model) => model.id),
          provider: p.provider ?? null,
          apiMode: p.apiMode ?? 'chat_completions',
        })),
      );
      await onSaveMcpServers(draftMcpServers.map((server) => serializeMcpServer(server)));
      await onSaveSettings(draftSettings);
      if (!canUpdateAsyncState()) return;
      setFeedback('设置已保存');
    } catch (e) {
      if (!canUpdateAsyncState()) return;
      setError(e instanceof Error ? e.message : '保存设置失败');
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
        className="flex max-h-[90vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-[720px]"
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
              <TabsTrigger value="env" className="flex-1 gap-1.5">
                <Lock className="size-3.5" />
                .env 来源
              </TabsTrigger>
              <TabsTrigger value="mcp" className="flex-1 gap-1.5">
                <Server className="size-3.5" />
                MCP
              </TabsTrigger>
              <TabsTrigger value="memory" className="flex-1 gap-1.5">
                <MemoryStick className="size-3.5" />
                记忆
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
                              placeholder="https://api.openai.com/v1"
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
                            value={provider.apiMode ?? 'chat_completions'}
                            onValueChange={(value) =>
                              updateProvider(index, {
                                apiMode: value as 'chat_completions' | 'responses',
                              })
                            }
                          >
                            <SelectTrigger className="h-7 w-full text-xs">
                              <SelectValue placeholder="选择接口模式" />
                            </SelectTrigger>
                            <SelectContent align="start">
                              <SelectItem value="chat_completions">OpenAI 兼容 /chat/completions</SelectItem>
                              <SelectItem value="responses">OpenAI /responses</SelectItem>
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
                          <div className="overflow-hidden rounded-md border bg-background">
                            {provider.models.length === 0 ? (
                              <div className="flex h-20 items-center justify-center text-xs text-muted-foreground">
                                暂无模型，点击添加或拉取模型
                              </div>
                            ) : (
                              <div className="divide-y">
                                {provider.models.map((model, modelIndex) => (
                                  <div
                                    key={`${model.id || 'draft'}-${modelIndex}`}
                                    className="grid grid-cols-[minmax(0,1fr)_120px_32px] items-center gap-2 px-2 py-2"
                                  >
                                    <div className="flex min-w-0 items-center gap-2">
                                      <div className="flex size-6 shrink-0 items-center justify-center rounded-full border bg-muted/40">
                                        <Server className="size-3 text-muted-foreground" />
                                      </div>
                                      <Input
                                        value={model.id}
                                        onChange={(event) =>
                                          updateProviderModel(index, modelIndex, { id: event.target.value })
                                        }
                                        placeholder="model-id"
                                        className="h-7 min-w-0 border-0 bg-transparent px-0 font-mono text-xs shadow-none focus-visible:ring-0"
                                      />
                                    </div>
                                    <div className="flex items-center gap-1.5">
                                      <span className="shrink-0 text-[10px] text-muted-foreground">上下文</span>
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
                                    </div>
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
                                ))}
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

          <TabsContent value="env" className="mt-0 min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <div className="space-y-3">
              <div className="flex items-start gap-3 rounded-lg border border-dashed bg-muted/30 p-4">
                <Lock className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div className="text-sm text-muted-foreground">
                  .env* 模型检测已禁用，当前仅使用这里配置的供应商模型
                </div>
              </div>

              {envConfigs.length === 0 ? (
                <div className="py-8 text-center text-sm text-muted-foreground">
                  当前未启用 .env 模型来源
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  {envConfigs.map((item) => (
                    <div key={item.id} className="rounded-lg border bg-card p-4">
                      <div className="flex items-center gap-2">
                        <Globe className="size-3.5 text-muted-foreground" />
                        <span className="text-sm font-medium">{item.name}</span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <Badge variant="secondary" className="text-xs">
                          {item.provider}
                        </Badge>
                        <Badge variant="outline" className="text-xs">
                          {item.sourceLabel ?? item.envFile}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>
              )}
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
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3">
                <div className="flex items-start justify-between gap-3 rounded-lg border bg-card p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-cyan-500/10">
                      <MemoryStick className="size-4 text-cyan-600 dark:text-cyan-400" />
                    </div>
                    <div className="space-y-1">
                      <div className="text-sm font-medium">启用长期记忆</div>
                      <div className="text-xs text-muted-foreground">
                        开启后，智能体会在后续对话中参考启用的记忆
                      </div>
                    </div>
                  </div>
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
                </div>

                <div className="flex items-start justify-between gap-3 rounded-lg border bg-card p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-lime-500/10">
                      <Brain className="size-4 text-lime-700 dark:text-lime-400" />
                    </div>
                    <div className="space-y-1">
                      <div className="text-sm font-medium">自动学习偏好</div>
                      <div className="text-xs text-muted-foreground">
                        从“以后、记住、不要、尽量”等表达中提取偏好
                      </div>
                    </div>
                  </div>
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
                </div>
              </div>

              <Separator />

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold">全局记忆</h3>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      跨工作区生效的交互偏好和工作方式
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1.5 text-xs"
                    onClick={() => addMemoryItem('global')}
                  >
                    <Plus className="size-3" />
                    添加
                  </Button>
                </div>

                {(draftSettings.memory?.global ?? []).length === 0 ? (
                  <div className="rounded-lg border border-dashed bg-muted/20 px-4 py-5 text-center text-sm text-muted-foreground">
                    暂无全局记忆
                  </div>
                ) : (
                  <div className="space-y-2">
                    {(draftSettings.memory?.global ?? []).map((item) => (
                      <div key={item.id} className="rounded-lg border bg-card p-3">
                        <div className="flex items-start gap-3">
                          <Switch
                            checked={item.enabled}
                            onCheckedChange={(enabled) => updateMemoryItem('global', item.id, { enabled })}
                            className="mt-1"
                          />
                          <div className="min-w-0 flex-1 space-y-2">
                            <Textarea
                              value={item.content}
                              onChange={(e) => updateMemoryItem('global', item.id, { content: e.target.value })}
                              placeholder="例如：除非明确允许，不要主动运行 pnpm build。"
                              className="min-h-[62px] resize-y text-xs leading-relaxed"
                            />
                            <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                              <span className="truncate">
                                {item.sourcePreview || '手动添加'}
                              </span>
                              <span className="shrink-0">
                                {new Date(item.updatedAt).toLocaleString()}
                              </span>
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            className="mt-0.5 size-7 text-muted-foreground"
                            onClick={() => deleteMemoryItem('global', item.id)}
                            title="删除记忆"
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <Separator />

              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold">当前工作区记忆</h3>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground" title={currentWorkspaceKey}>
                      {currentWorkspaceKey || '尚未选择工作区'}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1.5 text-xs"
                    onClick={() => addMemoryItem('workspace')}
                    disabled={!currentWorkspaceKey}
                  >
                    <Plus className="size-3" />
                    添加
                  </Button>
                </div>

                {workspaceMemoryItems.length === 0 ? (
                  <div className="rounded-lg border border-dashed bg-muted/20 px-4 py-5 text-center text-sm text-muted-foreground">
                    暂无当前工作区记忆
                  </div>
                ) : (
                  <div className="space-y-2">
                    {workspaceMemoryItems.map((item) => (
                      <div key={item.id} className="rounded-lg border bg-card p-3">
                        <div className="flex items-start gap-3">
                          <Switch
                            checked={item.enabled}
                            onCheckedChange={(enabled) => updateMemoryItem('workspace', item.id, { enabled })}
                            className="mt-1"
                          />
                          <div className="min-w-0 flex-1 space-y-2">
                            <Textarea
                              value={item.content}
                              onChange={(e) => updateMemoryItem('workspace', item.id, { content: e.target.value })}
                              placeholder="例如：这个项目里优先沿用现有 shadcn 风格。"
                              className="min-h-[62px] resize-y text-xs leading-relaxed"
                            />
                            <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                              <span className="truncate">
                                {item.sourcePreview || '手动添加'}
                              </span>
                              <span className="shrink-0">
                                {new Date(item.updatedAt).toLocaleString()}
                              </span>
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            className="mt-0.5 size-7 text-muted-foreground"
                            onClick={() => deleteMemoryItem('workspace', item.id)}
                            title="删除记忆"
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
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
