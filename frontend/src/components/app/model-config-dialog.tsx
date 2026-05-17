import { useMemo, useState } from 'react';
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
import { Separator } from '@/components/ui/separator';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import type { ModelOption, UIModelProvider } from '@/lib/app-types';
import { Eye, EyeOff, Globe, Key, List, Lock, Plus, RefreshCcw, Server } from 'lucide-react';

type EditableProvider = UIModelProvider & {
  modelsText: string;
};

type ModelConfigDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  providers: UIModelProvider[];
  envConfigs: ModelOption[];
  configPath: string | null;
  onSaveProviders: (providers: UIModelProvider[]) => Promise<void>;
  onDiscoverModels: (provider: UIModelProvider) => Promise<string[]>;
};

function normalizeModels(text: string) {
  return Array.from(
    new Set(
      text
        .split(/[\n,]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

function toEditableProvider(provider?: UIModelProvider): EditableProvider {
  return {
    id: provider?.id ?? null,
    name: provider?.name ?? '',
    baseUrl: provider?.baseUrl ?? '',
    apiKey: provider?.apiKey ?? '',
    models: provider?.models ?? [],
    provider: provider?.provider ?? null,
    modelsText: (provider?.models ?? []).join('\n'),
  };
}

export function ModelConfigDialog({
  open,
  onOpenChange,
  providers,
  envConfigs,
  configPath,
  onSaveProviders,
  onDiscoverModels,
}: ModelConfigDialogProps) {
  const [draftProviders, setDraftProviders] = useState<EditableProvider[]>(
    providers.length > 0 ? providers.map((p) => toEditableProvider(p)) : [toEditableProvider()],
  );
  const [activeTab, setActiveTab] = useState('providers');
  const [isSaving, setIsSaving] = useState(false);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visibleKeys, setVisibleKeys] = useState<Set<string>>(new Set());

  const availableCount = useMemo(
    () => draftProviders.reduce((acc, p) => acc + p.models.length, 0),
    [draftProviders],
  );

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
        const next = { ...p, ...patch };
        if (patch.modelsText !== undefined) {
          next.models = normalizeModels(patch.modelsText);
        }
        return next;
      }),
    );
  };

  const handleAddProvider = () => {
    setDraftProviders((prev) => [...prev, toEditableProvider()]);
    setActiveTab('providers');
  };

  const handleDiscoverModels = async (provider: EditableProvider, index: number) => {
    setError(null);
    setFeedback(null);
    setRefreshingId(provider.id ?? `draft-${index}`);
    try {
      const models = await onDiscoverModels({
        id: provider.id ?? null,
        name: provider.name,
        baseUrl: provider.baseUrl,
        apiKey: provider.apiKey,
        models: provider.models,
        provider: provider.provider ?? null,
      });
      updateProvider(index, { models, modelsText: models.join('\n') });
      setFeedback(`已拉取 ${models.length} 个模型`);
    } catch (e) {
      setError(e instanceof Error ? e.message : '拉取模型失败');
    } finally {
      setRefreshingId(null);
    }
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
          models: normalizeModels(p.modelsText),
          provider: p.provider ?? null,
        })),
      );
      setFeedback('配置已保存');
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存配置失败');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="flex max-h-[90vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-[680px]"
      >
        <DialogHeader className="shrink-0 px-6 pt-6 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10">
              <Server className="size-4.5 text-primary" />
            </div>
            <div className="min-w-0 flex-1">
              <DialogTitle className="text-lg">模型与供应商设置</DialogTitle>
              <DialogDescription className="mt-0.5 text-sm">
                新配置写入可视化配置文件，原有 .env* 保持只读兼容
              </DialogDescription>
            </div>
            <div className="shrink-0 text-right">
              <div className="text-2xl font-semibold tabular-nums">{availableCount}</div>
              <div className="text-xs text-muted-foreground">可用模型</div>
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
                供应商配置
              </TabsTrigger>
              <TabsTrigger value="env" className="flex-1 gap-1.5">
                <Lock className="size-3.5" />
                .env 兼容来源
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="providers" className="mt-0 min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-sm text-muted-foreground">
                  按 OpenAI 兼容接口处理，支持手填或从 /models 拉取
                </p>
                <Button variant="outline" size="sm" className="gap-1.5" onClick={handleAddProvider}>
                  <Plus className="size-3.5" />
                  添加
                </Button>
              </div>

              {draftProviders.map((provider, index) => {
                const key = provider.id ?? `draft-${index}`;
                const isRefreshing = refreshingId === key;
                const isKeyVisible = visibleKeys.has(key);

                return (
                  <div key={key} className="rounded-lg border bg-card">
                    <div className="flex items-center justify-between px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Globe className="size-4 text-muted-foreground" />
                        <span className="text-sm font-medium">
                          {provider.name || `供应商 ${index + 1}`}
                        </span>
                      </div>
                      <Badge variant="secondary" className="text-xs">
                        {provider.models.length} 模型
                      </Badge>
                    </div>

                    <Separator />

                    <div className="space-y-3 p-4">
                      <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1.5">
                          <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                            <Server className="size-3" />
                            显示名称
                          </label>
                          <Input
                            value={provider.name}
                            onChange={(e) => updateProvider(index, { name: e.target.value })}
                            placeholder="OpenRouter 主账号"
                          />
                        </div>
                        <div className="space-y-1.5">
                          <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                            <Globe className="size-3" />
                            Base URL
                          </label>
                          <Input
                            value={provider.baseUrl}
                            onChange={(e) => updateProvider(index, { baseUrl: e.target.value })}
                            placeholder="https://openrouter.ai/api/v1"
                          />
                        </div>
                      </div>

                      <div className="space-y-1.5">
                        <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                          <Key className="size-3" />
                          API Key
                        </label>
                        <div className="relative">
                          <Input
                            type={isKeyVisible ? 'text' : 'password'}
                            value={provider.apiKey}
                            onChange={(e) => updateProvider(index, { apiKey: e.target.value })}
                            placeholder="sk-..."
                            className="pr-9"
                          />
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            className="absolute top-1/2 right-1.5 -translate-y-1/2"
                            onClick={() => toggleKeyVisibility(key)}
                          >
                            {isKeyVisible ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-1.5">
                        <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                          <List className="size-3" />
                          模型列表
                        </label>
                        <Textarea
                          value={provider.modelsText}
                          onChange={(e) => updateProvider(index, { modelsText: e.target.value })}
                          className="min-h-[100px] font-mono text-xs"
                          placeholder={'每行一个模型，或逗号分隔\nopenai/gpt-4.1\nanthropic/claude-sonnet-4'}
                        />
                      </div>

                      <div className="flex items-center gap-3">
                        <Button
                          variant="outline"
                          size="sm"
                          className="gap-1.5"
                          disabled={isRefreshing}
                          onClick={() => void handleDiscoverModels(provider, index)}
                        >
                          <RefreshCcw className={`size-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
                          拉取模型
                        </Button>
                        <span className="text-xs text-muted-foreground">
                          不支持 /models 端点时可手动填写
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </TabsContent>

          <TabsContent value="env" className="mt-0 min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <div className="space-y-3">
              <div className="flex items-start gap-3 rounded-lg border border-dashed bg-muted/30 p-4">
                <Lock className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div className="text-sm text-muted-foreground">
                  .env* 配置为只读，系统会继续读取用于兼容旧流程
                </div>
              </div>

              {envConfigs.length === 0 ? (
                <div className="py-8 text-center text-sm text-muted-foreground">
                  未检测到 .env 配置来源
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
        </Tabs>

        <Separator />

        <DialogFooter className="shrink-0 px-6 py-3">
          <div className="flex flex-1 items-center gap-3">
            {error ? (
              <span className="text-sm text-destructive">{error}</span>
            ) : feedback ? (
              <span className="text-sm text-emerald-600 dark:text-emerald-400">{feedback}</span>
            ) : configPath ? (
              <span className="truncate text-xs text-muted-foreground">{configPath}</span>
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
