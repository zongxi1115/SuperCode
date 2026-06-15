import { useEffect, useMemo, useState } from 'react';
import { Plus, Save, Trash2, Workflow } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { message as appMessage } from '@/components/ui/message';
import type { ModelOption } from '@/lib/app-types';
import { cn } from '@/lib/utils';
import { getSpecialistTemplates, putConfluxConfig } from './api';
import type { ConfluxConfig, ConfluxSpecialistConfig, SpecialistTemplate } from './types';

const NO_MODEL = '__no_model__';
const TEMPLATE_PICKER = '__template_picker__';

function newSpecialist(modelRef = ''): ConfluxSpecialistConfig {
  return {
    id: crypto.randomUUID(),
    name: '',
    model_ref: modelRef,
    specialty: '',
    token_budget: 50_000,
  };
}

export function createDraftConfluxConfig(modelRef = ''): ConfluxConfig {
  return {
    orchestrator: {
      model_ref: modelRef,
      token_budget: 100_000,
    },
    specialists: [newSpecialist(modelRef)],
    require_user_review_per_step: false,
    require_orchestrator_diff_review: true,
    max_dispatch_depth: 2,
  };
}

function getModelLabel(option: ModelOption) {
  const provider = option.sourceLabel || option.provider || 'provider';
  const model = option.model || option.name || option.id;
  return `${provider} · ${model}`;
}

function ModelSelect({
  value,
  modelOptions,
  onChange,
}: {
  value: string;
  modelOptions: ModelOption[];
  onChange: (value: string) => void;
}) {
  return (
    <Select value={value || NO_MODEL} onValueChange={(next) => onChange(next === NO_MODEL ? '' : next)}>
      <SelectTrigger className="h-9 text-xs">
        <SelectValue placeholder="选择模型" />
      </SelectTrigger>
      <SelectContent align="start">
        <SelectItem value={NO_MODEL}>选择模型</SelectItem>
        {modelOptions.map((option) => (
          <SelectItem key={option.id} value={option.id}>
            {getModelLabel(option)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

type ConfluxConfigPanelProps = {
  initialConfig: ConfluxConfig | null;
  modelOptions: ModelOption[];
  onSaved?: (config: ConfluxConfig) => void;
};

export function ConfluxConfigPanel({
  initialConfig,
  modelOptions,
  onSaved,
}: ConfluxConfigPanelProps) {
  const defaultModelRef = modelOptions[0]?.id ?? '';
  const [config, setConfig] = useState<ConfluxConfig>(() => initialConfig ?? createDraftConfluxConfig(defaultModelRef));
  const [templates, setTemplates] = useState<SpecialistTemplate[]>([]);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setConfig(initialConfig ?? createDraftConfluxConfig(defaultModelRef));
  }, [defaultModelRef, initialConfig]);

  useEffect(() => {
    getSpecialistTemplates()
      .then(setTemplates)
      .catch((error) => {
        appMessage.error(error instanceof Error ? error.message : '读取 Specialist 模板失败');
      });
  }, []);

  const canSave = useMemo(() => {
    if (!config.orchestrator.model_ref.trim()) return false;
    if (config.orchestrator.token_budget <= 0) return false;
    if (config.specialists.length < 1) return false;
    return config.specialists.every(
      (specialist) =>
        specialist.name.trim() &&
        specialist.model_ref.trim() &&
        specialist.specialty.trim() &&
        specialist.token_budget > 0,
    );
  }, [config]);

  const updateSpecialist = (id: string, patch: Partial<ConfluxSpecialistConfig>) => {
    setConfig((prev) => ({
      ...prev,
      specialists: prev.specialists.map((specialist) =>
        specialist.id === id ? { ...specialist, ...patch } : specialist,
      ),
    }));
  };

  const saveConfig = async () => {
    if (!canSave || isSaving) return;
    setIsSaving(true);
    const payload: ConfluxConfig = {
      ...config,
      require_orchestrator_diff_review: true,
      max_dispatch_depth: 2,
      specialists: config.specialists.map((specialist) => ({
        ...specialist,
        name: specialist.name.trim(),
        model_ref: specialist.model_ref.trim(),
        specialty: specialist.specialty.trim(),
      })),
    };
    try {
      await putConfluxConfig(payload);
      setConfig(payload);
      appMessage.success('配置已保存');
      onSaved?.(payload);
    } catch (error) {
      appMessage.error(error instanceof Error ? error.message : '保存 Conflux 配置失败');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6">
      <div className="flex items-start gap-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-md border bg-background">
          <Workflow className="size-5 text-primary" />
        </div>
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-normal text-foreground">Conflux Agents 配置</h1>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Conflux 模式让多个智能体协作完成长任务，每一步都可观测、可审批。
          </p>
        </div>
      </div>

      <section className="rounded-lg border bg-card p-4">
        <div className="grid gap-4 md:grid-cols-[1fr_280px]">
          <div>
            <h2 className="text-sm font-semibold text-foreground">协调者 Orchestrator</h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              协调者负责拆分任务、派发、审计 diff、合并代码。建议选能力较强的模型。
            </p>
          </div>
          <div className="grid gap-3">
            <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
              模型
              <ModelSelect
                value={config.orchestrator.model_ref}
                modelOptions={modelOptions}
                onChange={(model_ref) =>
                  setConfig((prev) => ({
                    ...prev,
                    orchestrator: { ...prev.orchestrator, model_ref },
                  }))
                }
              />
            </label>
            <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
              Token 预算
              <Input
                type="number"
                min={1}
                value={config.orchestrator.token_budget}
                onChange={(event) =>
                  setConfig((prev) => ({
                    ...prev,
                    orchestrator: {
                      ...prev.orchestrator,
                      token_budget: Number(event.target.value) || 0,
                    },
                  }))
                }
              />
            </label>
          </div>
        </div>
      </section>

      <section className="grid gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">子智能体 Specialists</h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              请详细描述每个子智能体的专长，描述得越具体，协调者派发越准。反例：“很厉害”。好例：“精通 React 19 + Tailwind v4，写组件库，不熟 Vue”。
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={() =>
              setConfig((prev) => ({
                ...prev,
                specialists: [...prev.specialists, newSpecialist(defaultModelRef)],
              }))
            }
          >
            <Plus className="size-4" />
            添加 Specialist
          </Button>
        </div>

        <div className="grid gap-3">
          {config.specialists.map((specialist, index) => (
            <div key={specialist.id} className="rounded-lg border bg-card p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="text-xs font-semibold text-muted-foreground">Specialist {index + 1}</div>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-8 gap-1.5 text-destructive hover:text-destructive"
                  onClick={() => {
                    if (!window.confirm('确定删除这个 Specialist 吗？')) return;
                    setConfig((prev) => ({
                      ...prev,
                      specialists: prev.specialists.filter((item) => item.id !== specialist.id),
                    }));
                  }}
                >
                  <Trash2 className="size-3.5" />
                  删除
                </Button>
              </div>

              <div className="grid gap-3 md:grid-cols-[1fr_1fr_160px]">
                <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                  名称
                  <Input
                    value={specialist.name}
                    placeholder="比如: 前端专家"
                    onChange={(event) => updateSpecialist(specialist.id, { name: event.target.value })}
                  />
                </label>
                <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                  模型
                  <ModelSelect
                    value={specialist.model_ref}
                    modelOptions={modelOptions}
                    onChange={(model_ref) => updateSpecialist(specialist.id, { model_ref })}
                  />
                </label>
                <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                  Token 预算
                  <Input
                    type="number"
                    min={1}
                    value={specialist.token_budget}
                    onChange={(event) =>
                      updateSpecialist(specialist.id, {
                        token_budget: Number(event.target.value) || 0,
                      })
                    }
                  />
                </label>
              </div>

              <div className="mt-3 grid gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <label className="text-xs font-medium text-muted-foreground">专长描述</label>
                  <Select
                    value={TEMPLATE_PICKER}
                    onValueChange={(value) => {
                      const template = templates.find((item) => item.label === value);
                      if (template) {
                        updateSpecialist(specialist.id, { specialty: template.template });
                      }
                    }}
                  >
                    <SelectTrigger className="h-8 w-[150px] text-xs">
                      <SelectValue placeholder="使用模板" />
                    </SelectTrigger>
                    <SelectContent align="end">
                      <SelectItem value={TEMPLATE_PICKER}>使用模板</SelectItem>
                      {templates.map((template) => (
                        <SelectItem key={template.label} value={template.label}>
                          {template.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Textarea
                  className="min-h-28 resize-y"
                  value={specialist.specialty}
                  placeholder="例如: 精通 React 19 + Tailwind v4，擅长设计设置面板、表单状态和响应式布局；不负责 Python 后端。"
                  onChange={(event) => updateSpecialist(specialist.id, { specialty: event.target.value })}
                />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-semibold text-foreground">行为开关</h2>
        <div className="mt-4 grid gap-3">
          <label className="flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              className="mt-1 size-4 rounded border-border accent-primary"
              checked={config.require_user_review_per_step}
              onChange={(event) =>
                setConfig((prev) => ({
                  ...prev,
                  require_user_review_per_step: event.target.checked,
                }))
              }
            />
            <span>
              <span className="block font-medium text-foreground">每个子智能体完成后弹窗让我审批</span>
              <span className="block text-xs leading-5 text-muted-foreground">
                勾选后，你将能在每一步合并前看到 diff 并决定是否通过
              </span>
            </span>
          </label>

          <label className="flex items-start gap-3 text-sm text-muted-foreground">
            <input type="checkbox" className="mt-1 size-4 rounded border-border" checked disabled readOnly />
            <span>
              <span className="block font-medium">协调者合并前必须 git diff review</span>
              <span className="block text-xs leading-5">安全底线，不可关闭</span>
            </span>
          </label>

          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium text-foreground">派发深度上限:</span>
            <span className="rounded-md border bg-muted/40 px-2 py-1 text-xs text-muted-foreground">
              2 (系统硬上限)
            </span>
          </div>
        </div>
      </section>

      <div className="sticky bottom-0 -mx-4 border-t bg-background/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3">
          <p className={cn('text-xs', canSave ? 'text-muted-foreground' : 'text-destructive')}>
            {canSave ? '配置完整，可以保存。' : '请至少配置 1 个完整 Specialist，并为所有角色选择模型。'}
          </p>
          <Button type="button" className="gap-1.5" disabled={!canSave || isSaving} onClick={() => void saveConfig()}>
            <Save className="size-4" />
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </div>
      </div>
    </div>
  );
}
