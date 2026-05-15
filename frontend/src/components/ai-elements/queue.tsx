"use client";

import { cn } from "@/lib/utils";
import { CheckIcon, CircleIcon, LoaderIcon, XIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { createContext, useContext, useMemo } from "react";

import { Shimmer } from "./shimmer";

type QueueStatus = "pending" | "running" | "completed" | "error";

interface QueueContextValue {
  isStreaming: boolean;
}

const QueueContext = createContext<QueueContextValue | null>(null);

const useQueue = () => {
  const context = useContext(QueueContext);
  if (!context) {
    throw new Error("Queue components must be used within Queue");
  }
  return context;
};

export type QueueProps = ComponentProps<"div"> & {
  isStreaming?: boolean;
};

export const Queue = ({
  className,
  isStreaming = false,
  children,
  ...props
}: QueueProps) => {
  const contextValue = useMemo(() => ({ isStreaming }), [isStreaming]);

  return (
    <QueueContext.Provider value={contextValue}>
      <div
        data-slot="queue"
        className={cn("flex flex-col", className)}
        {...props}
      >
        {children}
      </div>
    </QueueContext.Provider>
  );
};

export type QueueItemProps = ComponentProps<"div"> & {
  status: QueueStatus;
};

export const QueueItem = ({
  className,
  status,
  children,
  ...props
}: QueueItemProps) => (
  <div
    data-slot="queue-item"
    data-status={status}
    className={cn("group/item relative flex gap-3", className)}
    {...props}
  >
    <div className="flex flex-col items-center">
      <QueueItemIndicator status={status} />
      <QueueItemSeparator />
    </div>
    <div className="flex-1 min-w-0 pb-4">{children}</div>
  </div>
);

export type QueueItemIndicatorProps = ComponentProps<"div"> & {
  status: QueueStatus;
};

const statusIconMap: Record<QueueStatus, ReactNode> = {
  pending: <CircleIcon className="size-3.5 text-muted-foreground/50" />,
  running: <LoaderIcon className="size-3.5 animate-spin text-primary" />,
  completed: <CheckIcon className="size-3.5 text-primary" />,
  error: <XIcon className="size-3.5 text-destructive" />,
};

export const QueueItemIndicator = ({
  className,
  status,
  ...props
}: QueueItemIndicatorProps) => {
  const { isStreaming } = useQueue();

  return (
    <div
      data-slot="queue-item-indicator"
      className={cn(
        "flex size-7 shrink-0 items-center justify-center rounded-full border",
        status === "pending" && "border-muted-foreground/25 bg-background",
        status === "running" && "border-primary/40 bg-primary/10",
        status === "completed" && "border-primary/30 bg-primary/10",
        status === "error" && "border-destructive/30 bg-destructive/10",
        className
      )}
      {...props}
    >
      {isStreaming && status === "running" ? (
        <Shimmer as="span" duration={1.5}>
          ●
        </Shimmer>
      ) : (
        statusIconMap[status]
      )}
    </div>
  );
};

export type QueueItemSeparatorProps = ComponentProps<"div">;

export const QueueItemSeparator = ({
  className,
  ...props
}: QueueItemSeparatorProps) => (
  <div
    data-slot="queue-item-separator"
    className={cn(
      "group-last/item:hidden w-px flex-1 bg-border",
      className
    )}
    {...props}
  />
);

export type QueueItemTitleProps = ComponentProps<"p"> & {
  children: string;
};

export const QueueItemTitle = ({
  className,
  children,
  ...props
}: QueueItemTitleProps) => {
  const { isStreaming } = useQueue();

  return (
    <p
      data-slot="queue-item-title"
      className={cn("text-sm font-medium leading-none", className)}
      {...props}
    >
      {isStreaming ? <Shimmer>{children}</Shimmer> : children}
    </p>
  );
};

export type QueueItemDescriptionProps = ComponentProps<"p"> & {
  children: string;
};

export const QueueItemDescription = ({
  className,
  children,
  ...props
}: QueueItemDescriptionProps) => {
  const { isStreaming } = useQueue();

  return (
    <p
      data-slot="queue-item-description"
      className={cn("mt-1 text-xs text-muted-foreground", className)}
      {...props}
    >
      {isStreaming ? <Shimmer>{children}</Shimmer> : children}
    </p>
  );
};
