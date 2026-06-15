import { apiFetch } from '@/lib/api-client';
import type { ConfluxConfig, SpecialistTemplate } from './types';

async function readApiError(response: Response, fallback: string) {
  try {
    const text = await response.text();
    if (!text.trim()) return fallback;
    try {
      const payload = JSON.parse(text) as { detail?: unknown; error?: unknown; message?: unknown };
      const detail = payload.detail ?? payload.error ?? payload.message;
      if (typeof detail === 'string' && detail.trim()) {
        return detail;
      }
      if (Array.isArray(detail)) {
        return detail.map((item) => String(item?.msg ?? item)).join('；');
      }
    } catch {
      return text;
    }
  } catch {
    // ignore read errors
  }
  return fallback;
}

export async function getConfluxConfig(): Promise<{ configured: boolean; config: ConfluxConfig | null }> {
  const response = await apiFetch('/api/conflux/config');
  if (!response.ok) {
    throw new Error(await readApiError(response, '读取 Conflux 配置失败'));
  }
  return response.json();
}

export async function putConfluxConfig(cfg: ConfluxConfig): Promise<{ ok: boolean }> {
  const response = await apiFetch('/api/conflux/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, '保存 Conflux 配置失败'));
  }
  return response.json();
}

export async function getSpecialistTemplates(): Promise<SpecialistTemplate[]> {
  const response = await apiFetch('/api/conflux/specialist-templates');
  if (!response.ok) {
    throw new Error(await readApiError(response, '读取 Specialist 模板失败'));
  }
  return response.json();
}
