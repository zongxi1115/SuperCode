"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { EyeIcon, EyeOffIcon, SaveIcon, RotateCcwIcon } from "lucide-react";
import type { HTMLAttributes } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "supercode-deploy-connect-saved";

function loadSaved(): Record<string, string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {}
  return {};
}

function saveSaved(values: Record<string, string>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(values));
  } catch {}
}

type ConnectField = {
  name: string;
  label: string;
  type: string;
  required: boolean;
  default?: string;
  placeholder?: string;
};

type ConnectInputRequest = {
  id: string;
  kind: string;
  title: string;
  message: string;
  fields: ConnectField[];
};

export type DeployConnectFormProps = HTMLAttributes<HTMLDivElement> & {
  inputRequest: ConnectInputRequest;
  sessionId: string | null;
  onSubmit?: (values: Record<string, string>) => void;
  disabled?: boolean;
};

export function DeployConnectForm({
  inputRequest,
  sessionId,
  onSubmit,
  disabled = false,
  className,
  ...props
}: DeployConnectFormProps) {
  const fields = inputRequest.fields ?? [];
  const defaultValues = useMemo(() => {
    const vals: Record<string, string> = {};
    for (const f of fields) vals[f.name] = f.default ?? "";
    return vals;
  }, [fields]);

  const [values, setValues] = useState<Record<string, string>>(defaultValues);
  const [hydrated, setHydrated] = useState(false);
  const [showPasswords, setShowPasswords] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const saved = loadSaved();
    setValues((prev) => {
      const merged = { ...prev };
      for (const f of fields) {
        if (saved[f.name] !== undefined) merged[f.name] = saved[f.name];
      }
      return merged;
    });
    setHydrated(true);
  }, [fields]);

  const setFieldValue = useCallback((name: string, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
  }, []);

  const handleSave = useCallback(() => {
    saveSaved(values);
  }, [values]);

  const handleReset = useCallback(() => {
    setValues(defaultValues);
    setError(null);
  }, [defaultValues]);

  const handleSubmit = useCallback(async () => {
    for (const f of fields) {
      if (f.required && !values[f.name]?.trim()) {
        setError(`${f.label} 为必填项`);
        return;
      }
    }
    setError(null);
    setSubmitting(true);
    saveSaved(values);
    try {
      if (onSubmit) {
        onSubmit(values);
        return;
      }
      if (!sessionId) return;
      const res = await fetch(
        `http://localhost:8000/api/sessions/${sessionId}/tools/${inputRequest.id}/connect`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ values }),
        },
      );
      const data = await res.json();
      if (!res.ok) throw new Error(String(data.detail ?? "提交失败"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  }, [fields, values, onSubmit, sessionId, inputRequest.id]);

  if (!hydrated) return null;

  return (
    <div className={cn("rounded-lg border bg-background", className)} {...props}>
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h3 className="font-medium text-sm">
          {inputRequest.title || "连接部署目标"}
        </h3>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1.5 text-xs text-muted-foreground"
          onClick={handleSave}
        >
          <SaveIcon size={12} />
          保存
        </Button>
      </div>

      {inputRequest.message && (
        <div className="border-b px-4 py-2 text-muted-foreground text-xs">
          {inputRequest.message}
        </div>
      )}

      <div className="divide-y">
        {fields.map((field) => {
          const isPassword = field.type === "password";
          const isTextarea = field.type === "textarea";
          const val = values[field.name] ?? "";
          const hidden = isPassword && !showPasswords;
          return (
            <div key={field.name} className="flex items-center justify-between gap-4 px-4 py-3">
              <div className="flex items-center gap-2 shrink-0">
                <span className="font-mono text-sm">{field.label}</span>
                {field.required && <Badge variant="secondary" className="text-xs">必填</Badge>}
              </div>
              <div className="flex items-center gap-1 flex-1 min-w-0">
                {isTextarea ? (
                  <textarea
                    className="flex min-h-[60px] w-full rounded-md bg-muted/30 px-2 py-1.5 text-sm font-mono resize-none focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground"
                    placeholder={field.placeholder ?? ""}
                    value={val}
                    onChange={(e) => setFieldValue(field.name, e.target.value)}
                    disabled={disabled || submitting}
                  />
                ) : (
                  <input
                    type={hidden ? "password" : "text"}
                    className="h-7 w-full rounded-md bg-transparent px-2 text-sm font-mono text-right focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground"
                    placeholder={field.placeholder ?? ""}
                    value={val}
                    onChange={(e) => setFieldValue(field.name, e.target.value)}
                    disabled={disabled || submitting}
                  />
                )}
                {isPassword && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-6 shrink-0"
                    onClick={() => setShowPasswords((v) => !v)}
                    tabIndex={-1}
                  >
                    {showPasswords ? <EyeOffIcon size={14} /> : <EyeIcon size={14} />}
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {error && (
        <div className="border-t px-4 py-2 text-destructive text-xs">{error}</div>
      )}

      <div className="flex items-center justify-end gap-2 border-t px-4 py-3">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1.5 text-xs text-muted-foreground"
          disabled={submitting}
          onClick={handleReset}
        >
          <RotateCcwIcon size={12} />
          重置
        </Button>
        <Button size="sm" disabled={submitting} onClick={handleSubmit}>
          {submitting ? "连接中..." : "连接"}
        </Button>
      </div>
    </div>
  );
}
