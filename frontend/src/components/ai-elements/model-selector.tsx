import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { cn } from "@/lib/utils";
import type { ComponentProps, ReactNode } from "react";
import { useState } from "react";

export type ModelSelectorProps = ComponentProps<typeof Dialog>;

export const ModelSelector = (props: ModelSelectorProps) => (
  <Dialog {...props} />
);

export type ModelSelectorTriggerProps = ComponentProps<typeof DialogTrigger>;

export const ModelSelectorTrigger = (props: ModelSelectorTriggerProps) => (
  <DialogTrigger {...props} />
);

export type ModelSelectorContentProps = ComponentProps<typeof DialogContent> & {
  title?: ReactNode;
};

export const ModelSelectorContent = ({
  className,
  children,
  title = "Model Selector",
  ...props
}: ModelSelectorContentProps) => (
  <DialogContent
    aria-describedby={undefined}
    className={cn(
      "outline! border-none! p-0 outline-border! outline-solid!",
      className
    )}
    {...props}
  >
    <DialogTitle className="sr-only">{title}</DialogTitle>
    <Command className="**:data-[slot=command-input-wrapper]:h-auto">
      {children}
    </Command>
  </DialogContent>
);

export type ModelSelectorDialogProps = ComponentProps<typeof CommandDialog>;

export const ModelSelectorDialog = (props: ModelSelectorDialogProps) => (
  <CommandDialog {...props} />
);

export type ModelSelectorInputProps = ComponentProps<typeof CommandInput>;

export const ModelSelectorInput = ({
  className,
  ...props
}: ModelSelectorInputProps) => (
  <CommandInput className={cn("h-auto py-3.5", className)} {...props} />
);

export type ModelSelectorListProps = ComponentProps<typeof CommandList>;

export const ModelSelectorList = (props: ModelSelectorListProps) => (
  <CommandList {...props} />
);

export type ModelSelectorEmptyProps = ComponentProps<typeof CommandEmpty>;

export const ModelSelectorEmpty = (props: ModelSelectorEmptyProps) => (
  <CommandEmpty {...props} />
);

export type ModelSelectorGroupProps = ComponentProps<typeof CommandGroup>;

export const ModelSelectorGroup = (props: ModelSelectorGroupProps) => (
  <CommandGroup {...props} />
);

export type ModelSelectorItemProps = ComponentProps<typeof CommandItem> & {
  hoverPreview?: {
    icon?: ReactNode;
    modelName?: string;
    provider?: string;
    contextWindow?: string | number;
    description?: string;
  };
};

export const ModelSelectorItem = ({ hoverPreview, ...props }: ModelSelectorItemProps) => {
  const [open, setOpen] = useState(false);

  if (!hoverPreview) {
    return <CommandItem {...props} />;
  }

  return (
    <HoverCard open={open} onOpenChange={setOpen} openDelay={200}>
      <HoverCardTrigger asChild>
        <CommandItem
          {...props}
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
        />
      </HoverCardTrigger>
      <HoverCardContent
        side="right"
        align="start"
        className="w-80 p-4"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        <div className="space-y-3">
          {hoverPreview.icon && (
            <div className="flex items-center gap-2">
              {hoverPreview.icon}
            </div>
          )}
          {hoverPreview.modelName && (
            <div>
              <h4 className="text-sm font-semibold">{hoverPreview.modelName}</h4>
            </div>
          )}
          {hoverPreview.provider && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="font-medium">提供商:</span>
              <span>{hoverPreview.provider}</span>
            </div>
          )}
          {hoverPreview.contextWindow && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="font-medium">上下文长度:</span>
              <span>{hoverPreview.contextWindow}</span>
            </div>
          )}
          {hoverPreview.description && (
            <div className="text-xs text-muted-foreground">
              {hoverPreview.description}
            </div>
          )}
        </div>
      </HoverCardContent>
    </HoverCard>
  );
};

export type ModelSelectorShortcutProps = ComponentProps<typeof CommandShortcut>;

export const ModelSelectorShortcut = (props: ModelSelectorShortcutProps) => (
  <CommandShortcut {...props} />
);

export type ModelSelectorSeparatorProps = ComponentProps<
  typeof CommandSeparator
>;

export const ModelSelectorSeparator = (props: ModelSelectorSeparatorProps) => (
  <CommandSeparator {...props} />
);

export function inferProviderFromModelName(modelName: string): string {
  const lower = modelName.toLowerCase();
  if (lower.includes("claude") || lower.includes("anthropic")) return "anthropic";
  if (lower.includes("gpt") || lower.includes("o1") || lower.includes("o3") || lower.includes("o4") || lower.includes("chatgpt")) return "openai";
  if (lower.includes("deepseek")) return "deepseek";
  if (lower.includes("gemini") || lower.includes("gemma")) return "google";
  if (lower.includes("qwen") || lower.includes("dashscope") || lower.includes("alibaba")) return "alibaba-cn";
  if (lower.includes("llama")) return "llama";
  if (lower.includes("mistral") || lower.includes("codestral") || lower.includes("pixtral")) return "mistral";
  if (lower.includes("grok") || lower.includes("xai")) return "xai";
  if (lower.includes("groq")) return "groq";
  if (lower.includes("perplexity") || lower.includes("sonar")) return "perplexity";
  if (lower.includes("cerebras")) return "cerebras";
  if (lower.includes("together")) return "togetherai";
  if (lower.includes("fireworks")) return "fireworks-ai";
  if (lower.includes("moonshot") || lower.includes("kimi")) return "moonshotai";
  if (lower.includes("zhipu") || lower.includes("glm")) return "zhipuai";
  if (lower.includes("nvidia")) return "nvidia";
  if (lower.includes("huggingface")) return "huggingface";
  return "";
}

export type ModelSelectorLogoProps = Omit<
  ComponentProps<"img">,
  "src" | "alt"
> & {
  provider:
    | "moonshotai-cn"
    | "lucidquery"
    | "moonshotai"
    | "zai-coding-plan"
    | "alibaba"
    | "xai"
    | "vultr"
    | "nvidia"
    | "upstage"
    | "groq"
    | "github-copilot"
    | "mistral"
    | "vercel"
    | "nebius"
    | "deepseek"
    | "alibaba-cn"
    | "google-vertex-anthropic"
    | "venice"
    | "chutes"
    | "cortecs"
    | "github-models"
    | "togetherai"
    | "azure"
    | "baseten"
    | "huggingface"
    | "opencode"
    | "fastrouter"
    | "google"
    | "google-vertex"
    | "cloudflare-workers-ai"
    | "inception"
    | "wandb"
    | "openai"
    | "zhipuai-coding-plan"
    | "perplexity"
    | "openrouter"
    | "zenmux"
    | "v0"
    | "iflowcn"
    | "synthetic"
    | "deepinfra"
    | "zhipuai"
    | "submodel"
    | "zai"
    | "inference"
    | "requesty"
    | "morph"
    | "lmstudio"
    | "anthropic"
    | "aihubmix"
    | "fireworks-ai"
    | "modelscope"
    | "llama"
    | "scaleway"
    | "amazon-bedrock"
    | "cerebras"
    // oxlint-disable-next-line typescript-eslint(ban-types) -- intentional pattern for autocomplete-friendly string union
    | (string & {});
  model?: string;
};

export const ModelSelectorLogo = ({
  provider,
  model,
  className,
  ...props
}: ModelSelectorLogoProps) => {
  const effectiveProvider = (provider === "openrouter" && model)
    ? inferProviderFromModelName(model) || provider
    : provider;
  return (
    <img
      {...props}
      alt={`${effectiveProvider} logo`}
      className={cn("size-3 dark:invert", className)}
      height={12}
      src={`https://models.dev/logos/${effectiveProvider}.svg`}
      width={12}
    />
  );
};

export type ModelSelectorLogoGroupProps = ComponentProps<"div">;

export const ModelSelectorLogoGroup = ({
  className,
  ...props
}: ModelSelectorLogoGroupProps) => (
  <div
    className={cn(
      "flex shrink-0 items-center -space-x-1 [&>img]:rounded-full [&>img]:bg-background [&>img]:p-px [&>img]:ring-1 dark:[&>img]:bg-foreground",
      className
    )}
    {...props}
  />
);

export type ModelSelectorNameProps = ComponentProps<"span">;

export const ModelSelectorName = ({
  className,
  ...props
}: ModelSelectorNameProps) => (
  <span className={cn("flex-1 truncate text-left", className)} {...props} />
);
