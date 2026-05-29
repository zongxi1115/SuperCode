"use client";

import { useControllableState } from "@radix-ui/react-use-controllable-state";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";
import { BrainIcon, ChevronDownIcon, DotIcon, AlertTriangleIcon, RefreshCwIcon, XCircleIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { createContext, memo, useContext, useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";

interface ChainOfThoughtContextValue {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
}

const ChainOfThoughtContext = createContext<ChainOfThoughtContextValue | null>(
  null
);

const useChainOfThought = () => {
  const context = useContext(ChainOfThoughtContext);
  if (!context) {
    throw new Error(
      "ChainOfThought components must be used within ChainOfThought"
    );
  }
  return context;
};

export type ChainOfThoughtProps = ComponentProps<"div"> & {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  autoOpen?: boolean;
  autoCloseDelay?: number;
};

export const ChainOfThought = memo(
  ({
    className,
    open,
    defaultOpen = false,
    onOpenChange,
    autoOpen = false,
    autoCloseDelay = 0,
    children,
    ...props
  }: ChainOfThoughtProps) => {
    const [isOpen, setIsOpen] = useControllableState({
      defaultProp: defaultOpen,
      onChange: onOpenChange,
      prop: open,
    });
    const hasAutoOpenedRef = useRef(autoOpen);
    const [hasAutoClosed, setHasAutoClosed] = useState(false);

    useEffect(() => {
      if (!autoOpen) {
        return;
      }
      hasAutoOpenedRef.current = true;
      setHasAutoClosed(false);
    }, [autoOpen]);

    useEffect(() => {
      if (!autoOpen || isOpen) {
        return;
      }
      setIsOpen(true);
    }, [autoOpen, isOpen, setIsOpen]);

    useEffect(() => {
      if (
        autoOpen ||
        !hasAutoOpenedRef.current ||
        !isOpen ||
        hasAutoClosed ||
        autoCloseDelay <= 0
      ) {
        return;
      }
      const timer = window.setTimeout(() => {
        setIsOpen(false);
        setHasAutoClosed(true);
      }, autoCloseDelay);
      return () => window.clearTimeout(timer);
    }, [autoCloseDelay, autoOpen, hasAutoClosed, isOpen, setIsOpen]);

    const chainOfThoughtContext = useMemo(
      () => ({ isOpen, setIsOpen }),
      [isOpen, setIsOpen]
    );

    return (
      <ChainOfThoughtContext.Provider value={chainOfThoughtContext}>
        <div className={cn("not-prose w-full space-y-4", className)} {...props}>
          {children}
        </div>
      </ChainOfThoughtContext.Provider>
    );
  }
);

export type ChainOfThoughtHeaderProps = ComponentProps<
  typeof CollapsibleTrigger
>;

export const ChainOfThoughtHeader = memo(
  ({ className, children, ...props }: ChainOfThoughtHeaderProps) => {
    const { isOpen, setIsOpen } = useChainOfThought();

    return (
      <Collapsible onOpenChange={setIsOpen} open={isOpen}>
        <CollapsibleTrigger
          className={cn(
            "flex w-full items-center gap-2 text-muted-foreground text-sm transition-colors hover:text-foreground",
            className
          )}
          {...props}
        >
          <BrainIcon className="size-4" />
          <span className="flex-1 text-left">
            {children ?? "Chain of Thought"}
          </span>
          <ChevronDownIcon
            className={cn(
              "size-4 transition-transform",
              isOpen ? "rotate-180" : "rotate-0"
            )}
          />
        </CollapsibleTrigger>
      </Collapsible>
    );
  }
);

export type ChainOfThoughtStepProps = ComponentProps<"div"> & {
  icon?: LucideIcon;
  label: ReactNode;
  description?: ReactNode;
  status?: "complete" | "active" | "pending";
};

const stepStatusStyles = {
  active: "text-muted-foreground",
  complete: "text-muted-foreground",
  pending: "text-muted-foreground/50",
};

export const ChainOfThoughtStep = memo(
  ({
    className,
    icon: Icon = DotIcon,
    label,
    description,
    status = "complete",
    children,
    ...props
  }: ChainOfThoughtStepProps) => (
    <div
      className={cn(
        "flex gap-2 text-sm",
        stepStatusStyles[status],
        "fade-in-0 slide-in-from-top-2 animate-in",
        className
      )}
      {...props}
    >
      <div className="relative mt-0.5">
        <Icon className="size-4" />
        <div className="absolute top-7 bottom-0 left-1/2 -mx-px w-px bg-border" />
      </div>
      <div className="flex-1 space-y-2 overflow-hidden">
        <div className={status === "active" ? "fade-edge-r" : ""}>{label}</div>
        {description && (
          <div className="text-muted-foreground text-xs">{description}</div>
        )}
        {children}
      </div>
    </div>
  )
);

export type ChainOfThoughtSearchResultsProps = ComponentProps<"div">;

export const ChainOfThoughtSearchResults = memo(
  ({ className, ...props }: ChainOfThoughtSearchResultsProps) => (
    <div
      className={cn("flex flex-wrap items-center gap-2", className)}
      {...props}
    />
  )
);

export type ChainOfThoughtSearchResultProps = ComponentProps<typeof Badge>;

export const ChainOfThoughtSearchResult = memo(
  ({ className, children, ...props }: ChainOfThoughtSearchResultProps) => (
    <Badge
      className={cn("gap-1 px-2 py-0.5 font-normal text-xs", className)}
      variant="secondary"
      {...props}
    >
      {children}
    </Badge>
  )
);

export type ChainOfThoughtContentProps = ComponentProps<
  typeof CollapsibleContent
>;

export const ChainOfThoughtContent = memo(
  ({ className, children, ...props }: ChainOfThoughtContentProps) => {
    const { isOpen } = useChainOfThought();

    return (
      <Collapsible open={isOpen}>
        <CollapsibleContent
          className={cn(
            "mt-2 space-y-3",
            "data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-2 data-[state=open]:slide-in-from-top-2 text-popover-foreground outline-none data-[state=closed]:animate-out data-[state=open]:animate-in",
            className
          )}
          {...props}
        >
          {children}
        </CollapsibleContent>
      </Collapsible>
    );
  }
);

export type ChainOfThoughtImageProps = ComponentProps<"div"> & {
  caption?: string;
};

export const ChainOfThoughtImage = memo(
  ({ className, children, caption, ...props }: ChainOfThoughtImageProps) => (
    <div className={cn("mt-2 space-y-2", className)} {...props}>
      <div className="relative flex max-h-[22rem] items-center justify-center overflow-hidden rounded-lg bg-muted p-3">
        {children}
      </div>
      {caption && <p className="text-muted-foreground text-xs">{caption}</p>}
    </div>
  )
);

ChainOfThought.displayName = "ChainOfThought";
ChainOfThoughtHeader.displayName = "ChainOfThoughtHeader";
ChainOfThoughtStep.displayName = "ChainOfThoughtStep";
ChainOfThoughtSearchResults.displayName = "ChainOfThoughtSearchResults";
ChainOfThoughtSearchResult.displayName = "ChainOfThoughtSearchResult";
ChainOfThoughtContent.displayName = "ChainOfThoughtContent";
ChainOfThoughtImage.displayName = "ChainOfThoughtImage";

export type ErrorChainBlockProps = {
  errors: string[];
  retryCount?: number;
  maxRetries?: number;
  retrying?: boolean;
};

const RollingDigit = memo(function RollingDigit({
  digit,
  className,
}: {
  digit: string;
  className?: string;
}) {
  const numericDigit = parseInt(digit, 10);
  const isNumeric = !isNaN(numericDigit);

  if (!isNumeric) {
    return <span className={className}>{digit}</span>;
  }

  return (
    <AnimatePresence mode="popLayout" initial={false}>
      <motion.span
        key={numericDigit}
        className={cn("inline-block tabular-nums", className)}
        layout
        initial={{ y: 14, opacity: 0, filter: "blur(2px)" }}
        animate={{ y: 0, opacity: 1, filter: "blur(0px)" }}
        exit={{ y: -14, opacity: 0, filter: "blur(2px)" }}
        transition={{ type: "spring", stiffness: 500, damping: 28 }}
      >
        {digit}
      </motion.span>
    </AnimatePresence>
  );
});

const RollingNumber = memo(function RollingNumber({
  value,
  className,
}: {
  value: number;
  className?: string;
}) {
  const digits = String(value).split("");
  return (
    <span className={cn("inline tabular-nums", className)}>
      {digits.map((d, i) => (
        <RollingDigit key={`${i}-${d}`} digit={d} />
      ))}
    </span>
  );
});

export const ErrorChainBlock = memo(
  ({ errors, retryCount, maxRetries, retrying }: ErrorChainBlockProps) => {
    const isRetrying = retrying ?? (retryCount != null && maxRetries != null && retryCount < maxRetries);
    const latestError = errors[errors.length - 1] ?? "";

    return (
      <motion.div
        layout
        className={cn(
          "rounded-lg border overflow-hidden",
          isRetrying
            ? "border-amber-500/30 bg-amber-500/5"
            : "border-destructive/30 bg-destructive/5",
        )}
        initial={false}
      >
        <div
          className={cn(
            "flex items-center gap-2 px-3 py-2 text-sm font-medium",
            isRetrying
              ? "text-amber-600 dark:text-amber-400 bg-amber-500/10"
              : "text-destructive bg-destructive/10",
          )}
        >
          {isRetrying ? (
            <RefreshCwIcon className="size-4 animate-spin shrink-0" />
          ) : (
            <XCircleIcon className="size-4 shrink-0" />
          )}
          <span>
            {isRetrying ? (
              <>
                请求出错，正在重试
                {retryCount != null && maxRetries != null && (
                  <>（<RollingNumber value={retryCount} />/<RollingNumber value={maxRetries} />）</>
                )}
              </>
            ) : retryCount != null ? (
              <>
                已重试 <RollingNumber value={retryCount} /> 次仍未成功
              </>
            ) : (
              "请求失败"
            )}
          </span>
        </div>
        <div className="px-3 py-2">
          <pre className="whitespace-pre-wrap break-words text-xs text-muted-foreground font-mono">
            {latestError}
          </pre>
          {errors.length > 1 && (
            <details className="mt-1.5">
              <summary className="text-[11px] text-muted-foreground/60 cursor-pointer hover:text-muted-foreground transition-colors">
                查看全部 {errors.length} 条错误
              </summary>
              <div className="mt-1.5 space-y-1">
                {errors.map((err, idx) => (
                  <pre key={idx} className="whitespace-pre-wrap break-words text-[11px] text-muted-foreground/70 font-mono border-l-2 border-muted-foreground/20 pl-2">
                    {err}
                  </pre>
                ))}
              </div>
            </details>
          )}
        </div>
        {isRetrying && retryCount != null && maxRetries != null && (
          <div className="px-3 pb-2">
            <div className="h-1 rounded-full bg-amber-500/10 overflow-hidden">
              <motion.div
                className="h-full rounded-full bg-amber-500/40"
                initial={false}
                animate={{ width: `${Math.min((retryCount / maxRetries) * 100, 100)}%` }}
                transition={{ type: "spring", stiffness: 300, damping: 25 }}
              />
            </div>
          </div>
        )}
      </motion.div>
    );
  }
);

ErrorChainBlock.displayName = "ErrorChainBlock";
