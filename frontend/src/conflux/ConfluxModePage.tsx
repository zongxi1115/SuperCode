import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Loader2, Network, Pencil, Play, Workflow } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { message as appMessage } from '@/components/ui/message';
import { apiFetch } from '@/lib/api-client';
import type { ModelOption } from '@/lib/app-types';
import { getConfluxConfig } from './api';
import { ConfluxConfigPanel } from './ConfluxConfigPanel';
import type { ConfluxConfig } from './types';

function readModelLabel(modelOptions: ModelOption[], modelRef: string) {
  const match = modelOptions.find((option) => option.id === modelRef || option.envFile === modelRef);
  if (!match) return modelRef || '未选择模型';
  return match.label || `${match.sourceLabel || match.provider} · ${match.model || match.name}`;
}

async function readApiError(response: Response, fallback: string) {
  try {
    const text = await response.text();
    if (!text.trim()) return fallback;
    try {
      const payload = JSON.parse(text) as { detail?: unknown; error?: unknown; message?: unknown };
      const detail = payload.detail ?? payload.error ?? payload.message;
      if (typeof detail === 'string' && detail.trim()) return detail;
    } catch {
      return text;
    }
  } catch {
    // ignore read errors
  }
  return fallback;
}

export function ConfluxModePage() {
  const [config, setConfig] = useState<ConfluxConfig | null>(null);
  const [configured, setConfigured] = useState(false);
  const [isConfigLoading, setIsConfigLoading] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [task, setTask] = useState('');
  const [startMessage, setStartMessage] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);

  const loadData = useCallback(async () => {
    setIsConfigLoading(true);
    try {
      const [configPayload, modelsResponse] = await Promise.all([
        getConfluxConfig(),
        apiFetch('/api/models'),
      ]);
      if (!modelsResponse.ok) {
        throw new Error(await readApiError(modelsResponse, '读取模型列表失败'));
      }
      const modelPayload = await modelsResponse.json() as { models?: ModelOption[] };
      setModelOptions(modelPayload.models ?? []);
      setConfigured(configPayload.configured);
      setConfig(configPayload.config);
      setIsEditing(!configPayload.configured);
    } catch (error) {
      const message = error instanceof Error ? error.message : '读取 Conflux 配置失败';
      appMessage.error(message);
      setStartMessage(message);
    } finally {
      setIsConfigLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const summary = useMemo(() => {
    if (!config) return null;
    return {
      specialistCount: config.specialists.length,
      orchestrator: readModelLabel(modelOptions, config.orchestrator.model_ref),
    };
  }, [config, modelOptions]);

  const startConflux = async () => {
    if (!config || !task.trim() || isStarting) return;
    setIsStarting(true);
    setStartMessage(null);
    try {
      const response = await apiFetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_type: 'conflux',
          message: task.trim(),
        }),
      });
      if (response.status === 501) {
        setStartMessage('功能开发中: 协调者将在下一步实现');
        appMessage.info('功能开发中: 协调者将在下一步实现');
        return;
      }
      if (!response.ok) {
        throw new Error(await readApiError(response, '启动 Conflux 失败'));
      }
      setStartMessage('功能开发中: 协调者将在下一步实现');
    } catch (error) {
      const raw = error instanceof Error ? error.message : '启动 Conflux 失败';
      const friendly = raw.includes('Conflux orchestrator not yet implemented')
        ? '功能开发中: 协调者将在下一步实现'
        : raw;
      setStartMessage(friendly);
      appMessage.error(friendly);
    } finally {
      setIsStarting(false);
    }
  };

  if (isConfigLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        正在加载 Conflux 配置...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4">
          <div className="flex min-w-0 items-center gap-2">
            <Button type="button" size="sm" variant="ghost" className="gap-1.5" onClick={() => { window.location.href = '/app'; }}>
              <ArrowLeft className="size-4" />
              返回
            </Button>
            <div className="h-5 w-px bg-border" />
            <div className="flex min-w-0 items-center gap-2">
              <Workflow className="size-4 text-primary" />
              <span className="truncate text-sm font-semibold">Conflux</span>
            </div>
          </div>
          {configured && config ? (
            <Button type="button" size="sm" variant="outline" className="gap-1.5" onClick={() => setIsEditing(true)}>
              <Pencil className="size-3.5" />
              编辑配置
            </Button>
          ) : null}
        </div>
      </header>

      {isEditing ? (
        <ConfluxConfigPanel
          initialConfig={config}
          modelOptions={modelOptions}
          onSaved={(nextConfig) => {
            setConfig(nextConfig);
            setConfigured(true);
            setIsEditing(false);
            setStartMessage(null);
          }}
        />
      ) : configured && config && summary ? (
        <main className="mx-auto flex max-w-5xl flex-col gap-5 px-4 py-6">
          <section className="rounded-lg border bg-card p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <h1 className="text-xl font-semibold tracking-normal">Conflux Agents</h1>
                <p className="mt-1 truncate text-sm text-muted-foreground">
                  {summary.specialistCount} 个 specialists, Orchestrator: {summary.orchestrator}
                </p>
              </div>
              <Button type="button" variant="outline" className="gap-1.5" onClick={() => setIsEditing(true)}>
                <Pencil className="size-4" />
                编辑配置
              </Button>
            </div>
          </section>

          {startMessage ? (
            <Alert>
              <Network className="size-4" />
              <AlertTitle>Conflux 状态</AlertTitle>
              <AlertDescription>{startMessage}</AlertDescription>
            </Alert>
          ) : null}

          <section className="grid gap-3 rounded-lg border bg-card p-4">
            <div>
              <h2 className="text-sm font-semibold">任务</h2>
              <p className="mt-1 text-sm text-muted-foreground">执行视图将在 Step 6/7 实现。</p>
            </div>
            <Textarea
              className="min-h-32 resize-y"
              value={task}
              placeholder="写下要交给 Conflux 协作完成的任务..."
              onChange={(event) => setTask(event.target.value)}
            />
            <div className="flex justify-end">
              <Button type="button" className="gap-1.5" disabled={!task.trim() || isStarting} onClick={() => void startConflux()}>
                {isStarting ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
                开始
              </Button>
            </div>
          </section>
        </main>
      ) : (
        <main className="mx-auto flex min-h-[calc(100vh-56px)] max-w-3xl items-center px-4 py-10">
          <section className="w-full rounded-lg border bg-card p-6">
            <div className="flex items-start gap-4">
              <div className="flex size-12 shrink-0 items-center justify-center rounded-md border bg-background">
                <Workflow className="size-6 text-primary" />
              </div>
              <div className="min-w-0 flex-1">
                <h1 className="text-xl font-semibold tracking-normal">尚未配置 Conflux Agents</h1>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  Conflux 模式需要先配置协调者和子智能体。
                </p>
                <Button type="button" className="mt-5" onClick={() => setIsEditing(true)}>
                  立即配置
                </Button>
              </div>
            </div>
          </section>
        </main>
      )}
    </div>
  );
}
