import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
  type ReactNode,
} from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  AlertCircle,
  CheckCircle2,
  Info,
  LoaderCircle,
  TriangleAlert,
  X,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/utils';

export type MessageType = 'info' | 'success' | 'warning' | 'error' | 'loading';
export type MessageVariant = 'glass' | 'status';

export type MessageOptions = {
  id?: string;
  key?: string;
  type?: MessageType;
  variant?: MessageVariant;
  title?: ReactNode;
  content?: ReactNode;
  html?: string;
  duration?: number;
  className?: string;
  action?: {
    label: ReactNode;
    onClick: () => void;
  };
  onClose?: () => void;
};

type MessageInput = ReactNode | MessageOptions;
type MessageShortcutOptions = Omit<MessageOptions, 'content' | 'type'>;
type InternalMessage = Required<Pick<MessageOptions, 'id' | 'type'>> & MessageOptions;
type MessageEvent =
  | { action: 'open'; message: InternalMessage }
  | { action: 'destroy'; id?: string };
type MessageListener = (event: MessageEvent) => void;
type PromiseMessage<T> = ReactNode | ((value: T) => ReactNode);

export type MessagePromiseOptions<T> = {
  key?: string;
  loading: ReactNode;
  success?: PromiseMessage<T>;
  error?: PromiseMessage<unknown>;
};

export type MessageApi = {
  open: (input: MessageInput) => string;
  info: (content: MessageInput, options?: MessageShortcutOptions) => string;
  success: (content: MessageInput, options?: MessageShortcutOptions) => string;
  warning: (content: MessageInput, options?: MessageShortcutOptions) => string;
  error: (content: MessageInput, options?: MessageShortcutOptions) => string;
  loading: (content: MessageInput, options?: MessageShortcutOptions) => string;
  destroy: (id?: string) => void;
  promise: <T>(promiseLike: Promise<T>, options: MessagePromiseOptions<T>) => Promise<T>;
};

const DEFAULT_DURATION_BY_TYPE: Record<MessageType, number> = {
  info: 3200,
  success: 3000,
  warning: 4200,
  error: 5600,
  loading: 0,
};

const TONE_BY_TYPE: Record<
  MessageType,
  {
    icon: LucideIcon;
    iconClassName: string;
    statusClassName: string;
  }
> = {
  info: {
    icon: Info,
    iconClassName: 'text-sky-500 dark:text-sky-300',
    statusClassName:
      'border-sky-200/70 bg-sky-50/90 text-sky-950 shadow-[0_0_0_1px_rgba(14,165,233,0.08),0_12px_30px_-8px_rgba(14,165,233,0.26)] dark:border-sky-800/70 dark:bg-sky-950/85 dark:text-sky-50 dark:shadow-[0_0_0_1px_rgba(125,211,252,0.12),0_16px_36px_-10px_rgba(14,165,233,0.34)]',
  },
  success: {
    icon: CheckCircle2,
    iconClassName: 'text-emerald-500',
    statusClassName:
      'border-emerald-200/70 bg-emerald-50/90 text-emerald-950 shadow-[0_0_0_1px_rgba(16,185,129,0.08),0_12px_30px_-8px_rgba(16,185,129,0.26)] dark:border-emerald-800/70 dark:bg-emerald-950/85 dark:text-emerald-50 dark:shadow-[0_0_0_1px_rgba(110,231,183,0.12),0_16px_36px_-10px_rgba(16,185,129,0.34)]',
  },
  warning: {
    icon: TriangleAlert,
    iconClassName: 'text-amber-500',
    statusClassName:
      'border-amber-200/80 bg-amber-50/90 text-amber-950 shadow-[0_0_0_1px_rgba(245,158,11,0.08),0_12px_30px_-8px_rgba(245,158,11,0.28)] dark:border-amber-800/70 dark:bg-amber-950/85 dark:text-amber-50 dark:shadow-[0_0_0_1px_rgba(252,211,77,0.12),0_16px_36px_-10px_rgba(245,158,11,0.34)]',
  },
  error: {
    icon: AlertCircle,
    iconClassName: 'text-rose-500',
    statusClassName:
      'border-rose-200/80 bg-rose-50/90 text-rose-950 shadow-[0_0_0_1px_rgba(244,63,94,0.08),0_12px_30px_-8px_rgba(244,63,94,0.28)] dark:border-rose-800/70 dark:bg-rose-950/85 dark:text-rose-50 dark:shadow-[0_0_0_1px_rgba(251,113,133,0.12),0_16px_36px_-10px_rgba(244,63,94,0.34)]',
  },
  loading: {
    icon: LoaderCircle,
    iconClassName: 'animate-spin text-zinc-500 dark:text-zinc-400',
    statusClassName:
      'border-zinc-200/80 bg-zinc-100/90 text-zinc-950 shadow-[0_0_0_1px_rgba(39,39,42,0.06),0_12px_30px_-8px_rgba(39,39,42,0.22)] dark:border-zinc-800 dark:bg-zinc-900/90 dark:text-zinc-50 dark:shadow-[0_0_0_1px_rgba(255,255,255,0.08),0_16px_36px_-10px_rgba(0,0,0,0.54)]',
  },
};

const MESSAGE_GLASS_CLASS =
  'border-white/60 bg-white/70 text-zinc-900 shadow-[0_0_0_1px_rgba(255,255,255,0.48),0_2px_4px_0_rgba(0,0,0,0.025),0_16px_36px_-8px_rgba(0,0,0,0.16)] backdrop-blur-2xl backdrop-saturate-150 supports-[backdrop-filter]:bg-white/60 dark:border-white/10 dark:bg-zinc-950/70 dark:text-zinc-100 dark:shadow-[0_0_0_1px_rgba(255,255,255,0.08),0_2px_4px_0_rgba(0,0,0,0.22),0_18px_42px_-8px_rgba(0,0,0,0.72)] dark:supports-[backdrop-filter]:bg-zinc-950/60';

const listeners = new Set<MessageListener>();
const pendingEvents: MessageEvent[] = [];
let messageSeed = 0;

function createMessageId() {
  messageSeed += 1;
  return `message-${Date.now()}-${messageSeed}`;
}

function isMessageOptions(input: MessageInput): input is MessageOptions {
  return Boolean(
    input &&
      typeof input === 'object' &&
      ('content' in input || 'html' in input),
  );
}

function emitMessageEvent(event: MessageEvent) {
  if (listeners.size === 0) {
    pendingEvents.push(event);
    return;
  }
  listeners.forEach((listener) => listener(event));
}

function subscribeMessage(listener: MessageListener) {
  listeners.add(listener);
  if (pendingEvents.length > 0) {
    const events = pendingEvents.splice(0, pendingEvents.length);
    events.forEach((event) => listener(event));
  }
  return () => listeners.delete(listener);
}

function normalizeMessage(input: MessageInput, type: MessageType = 'info'): InternalMessage {
  const options = isMessageOptions(input) ? input : { content: input };
  const resolvedType = options.type ?? type;
  const id = options.id ?? options.key ?? createMessageId();

  return {
    ...options,
    id,
    type: resolvedType,
    duration: options.duration ?? DEFAULT_DURATION_BY_TYPE[resolvedType],
  };
}

function openMessage(input: MessageInput) {
  const nextMessage = normalizeMessage(input, isMessageOptions(input) ? input.type ?? 'info' : 'info');
  emitMessageEvent({ action: 'open', message: nextMessage });
  return nextMessage.id;
}

function shortcutMessage(type: MessageType, input: MessageInput, options?: MessageShortcutOptions) {
  const base = isMessageOptions(input) ? input : { content: input };
  return openMessage({
    ...base,
    ...options,
    type,
    content: base.content,
  });
}

function resolvePromiseMessage<T>(message: PromiseMessage<T> | undefined, value: T, fallback: ReactNode) {
  if (typeof message === 'function') {
    return message(value);
  }
  return message ?? fallback;
}

export const message: MessageApi = {
  open: openMessage,
  info: (content, options) => shortcutMessage('info', content, options),
  success: (content, options) => shortcutMessage('success', content, options),
  warning: (content, options) => shortcutMessage('warning', content, options),
  error: (content, options) => shortcutMessage('error', content, options),
  loading: (content, options) => shortcutMessage('loading', content, options),
  destroy: (id) => emitMessageEvent({ action: 'destroy', id }),
  promise: async <T,>(promiseLike: Promise<T>, options: MessagePromiseOptions<T>) => {
    const key = options.key ?? createMessageId();
    message.loading({ key, content: options.loading, duration: 0 });
    try {
      const value = await promiseLike;
      message.success({
        key,
        content: resolvePromiseMessage(options.success, value, '操作成功'),
      });
      return value;
    } catch (error) {
      message.error({
        key,
        content: resolvePromiseMessage(options.error, error, error instanceof Error ? error.message : '操作失败'),
      });
      throw error;
    }
  },
};

const MessageContext = createContext<MessageApi>(message);

export function useMessage() {
  return useContext(MessageContext);
}

export function MessageProvider({
  children,
  maxCount = 5,
}: PropsWithChildren<{ maxCount?: number }>) {
  const [items, setItems] = useState<InternalMessage[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const timersRef = useRef(new Map<string, number>());
  const itemsRef = useRef(items);

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  const clearTimer = useCallback((id: string) => {
    const timerId = timersRef.current.get(id);
    if (timerId !== undefined) {
      window.clearTimeout(timerId);
      timersRef.current.delete(id);
    }
  }, []);

  const closeMessage = useCallback(
    (id: string) => {
      const current = itemsRef.current.find((item) => item.id === id);
      clearTimer(id);
      setItems((prev) => prev.filter((item) => item.id !== id));
      current?.onClose?.();
    },
    [clearTimer],
  );

  const scheduleClose = useCallback(
    (item: InternalMessage) => {
      clearTimer(item.id);
      if (!item.duration || item.duration <= 0) {
        return;
      }
      const timerId = window.setTimeout(() => closeMessage(item.id), item.duration);
      timersRef.current.set(item.id, timerId);
    },
    [clearTimer, closeMessage],
  );

  useEffect(() => {
    const unsubscribe = subscribeMessage((event) => {
      if (event.action === 'destroy') {
        if (event.id) {
          closeMessage(event.id);
          return;
        }
        timersRef.current.forEach((timerId) => window.clearTimeout(timerId));
        timersRef.current.clear();
        setItems([]);
        return;
      }

      const next = event.message;
      setItems((prev) => {
        const matchedIndex = prev.findIndex(
          (item) => item.id === next.id || (next.key && item.key === next.key),
        );
        const merged =
          matchedIndex >= 0
            ? prev.map((item, index) => (index === matchedIndex ? { ...item, ...next } : item))
            : [...prev, next];
        const visible = merged.slice(-maxCount);
        const visibleIds = new Set(visible.map((item) => item.id));
        merged.forEach((item) => {
          if (!visibleIds.has(item.id)) {
            clearTimer(item.id);
          }
        });
        return visible;
      });
      scheduleClose(next);
    });

    return () => {
      unsubscribe();
      timersRef.current.forEach((timerId) => window.clearTimeout(timerId));
      timersRef.current.clear();
    };
  }, [clearTimer, closeMessage, maxCount, scheduleClose]);

  const contextValue = useMemo(() => message, []);

  return (
    <MessageContext.Provider value={contextValue}>
      {children}
      <div
        aria-live="polite"
        aria-relevant="additions text"
        className="pointer-events-none fixed left-1/2 top-12 z-[100] flex w-full -translate-x-1/2 flex-col items-center gap-2 px-3"
      >
        <AnimatePresence initial={false}>
          {items.map((item) => {
            const tone = TONE_BY_TYPE[item.type];
            const Icon = tone.icon;
            const isExpanded = expandedId === item.id;
            const isStatusVariant = item.variant === 'status';
            return (
              <motion.div
                key={item.id}
                layout
                role={item.type === 'error' || item.type === 'warning' ? 'alert' : 'status'}
                initial={{ opacity: 0, y: -14, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -10, scale: 0.96 }}
                transition={{
                  duration: 0.3,
                  ease: [0.16, 1, 0.3, 1],
                  layout: { duration: 0.28, ease: [0.16, 1, 0.3, 1] },
                }}
                onMouseEnter={() => setExpandedId(item.id)}
                onMouseLeave={() => setExpandedId((current) => (current === item.id ? null : current))}
                onFocus={() => setExpandedId(item.id)}
                onBlur={() => setExpandedId((current) => (current === item.id ? null : current))}
                className={cn(
                  'group pointer-events-auto flex select-none items-start gap-2.5 border px-4 py-2.5 text-xs font-medium backdrop-blur-xl backdrop-saturate-150 transition-colors',
                  isExpanded ? 'max-w-[min(94vw,40rem)] rounded-2xl' : 'max-w-[min(82vw,24rem)] rounded-full',
                  isStatusVariant ? tone.statusClassName : MESSAGE_GLASS_CLASS,
                  item.className,
                )}
              >
                <Icon className={cn('mt-[3px] size-3.5 shrink-0', tone.iconClassName)} />
                <div
                  className={cn(
                    'min-w-0 flex-1 leading-5 tracking-tight',
                    isExpanded
                      ? 'whitespace-normal break-words'
                      : 'overflow-hidden text-ellipsis whitespace-nowrap',
                  )}
                >
                  {item.title ? (
                    <span className={cn('mr-1.5 font-semibold', isStatusVariant ? 'text-current' : 'text-zinc-900 dark:text-zinc-50')}>
                      {item.title}
                    </span>
                  ) : null}
                  {item.html ? (
                    <span
                      className={isStatusVariant ? 'text-current' : 'text-zinc-700 dark:text-zinc-200'}
                      dangerouslySetInnerHTML={{ __html: item.html }}
                    />
                  ) : (
                    <span className={isStatusVariant ? 'text-current' : 'text-zinc-700 dark:text-zinc-200'}>
                      {item.content}
                    </span>
                  )}
                </div>
                {item.action ? (
                  <>
                    <span className="mx-0.5 h-3 w-px shrink-0 bg-zinc-300/80 dark:bg-zinc-700/80" aria-hidden />
                    <button
                      type="button"
                      onClick={() => {
                        item.action?.onClick();
                        closeMessage(item.id);
                      }}
                      className="shrink-0 font-semibold text-zinc-500 underline-offset-2 transition-colors hover:text-zinc-950 hover:underline active:scale-95 dark:text-zinc-400 dark:hover:text-white"
                    >
                      {item.action.label}
                    </button>
                  </>
                ) : null}
                <button
                  type="button"
                  aria-label="关闭提示"
                  onClick={() => closeMessage(item.id)}
                  className="-mr-1 inline-flex size-5 shrink-0 items-center justify-center rounded-full text-zinc-400 opacity-0 transition-all pointer-events-none hover:bg-zinc-100 hover:text-zinc-900 group-hover:pointer-events-auto group-hover:opacity-100 focus-visible:pointer-events-auto focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:hover:bg-zinc-800 dark:hover:text-white"
                >
                  <X className="size-3" />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </MessageContext.Provider>
  );
}
