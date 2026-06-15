import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';

type AppErrorBoundaryProps = {
  children: ReactNode;
};

type AppErrorBoundaryState = {
  error: Error | null;
  isPluginError: boolean;
};

const PLUGIN_SOURCE_RE = /(?:chrome|moz|safari|edge)-extension:\/\//i;

function getErrorText(error: unknown) {
  if (error instanceof Error) {
    return `${error.name}: ${error.message}\n${error.stack ?? ''}`;
  }
  return String(error ?? '');
}

function isLikelyPluginError(error: unknown, source?: string | null) {
  return PLUGIN_SOURCE_RE.test(`${source ?? ''}\n${getErrorText(error)}`);
}

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = {
    error: null,
    isPluginError: false,
  };

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return {
      error,
      isPluginError: isLikelyPluginError(error),
    };
  }

  componentDidMount() {
    window.addEventListener('error', this.handleWindowError);
    window.addEventListener('unhandledrejection', this.handleUnhandledRejection);
  }

  componentWillUnmount() {
    window.removeEventListener('error', this.handleWindowError);
    window.removeEventListener('unhandledrejection', this.handleUnhandledRejection);
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[AppErrorBoundary]', error, errorInfo);
  }

  handleWindowError = (event: ErrorEvent) => {
    if (!isLikelyPluginError(event.error ?? event.message, event.filename)) {
      return;
    }
    event.preventDefault();
    this.setState({
      error:
        event.error instanceof Error
          ? event.error
          : new Error(event.message || '浏览器插件脚本异常'),
      isPluginError: true,
    });
  };

  handleUnhandledRejection = (event: PromiseRejectionEvent) => {
    if (!isLikelyPluginError(event.reason)) {
      return;
    }
    event.preventDefault();
    this.setState({
      error:
        event.reason instanceof Error
          ? event.reason
          : new Error(String(event.reason ?? '浏览器插件异步异常')),
      isPluginError: true,
    });
  };

  render() {
    if (!this.state.error) {
      return this.props.children;
    }

    const title = this.state.isPluginError ? '插件导致页面异常' : '页面渲染异常';
    const description = this.state.isPluginError
      ? '检测到浏览器插件导致问题，请禁用相关插件后刷新页面重试。'
      : '页面遇到未捕获错误，请刷新页面重试；如果刚安装了插件，也可以先禁用插件排查。';

    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
        <div className="w-full max-w-md rounded-lg border bg-card p-5 shadow-sm">
          <div className="flex items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-destructive/10 text-destructive">
              <AlertTriangle className="size-4" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="text-base font-semibold">{title}</h1>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                {description}
              </p>
              <pre className="mt-3 max-h-32 overflow-auto rounded-md bg-muted/60 p-2 text-xs text-muted-foreground">
                {this.state.error.message}
              </pre>
              <Button
                className="mt-4 h-8 gap-1.5 text-xs"
                size="sm"
                onClick={() => window.location.reload()}
              >
                <RefreshCcw className="size-3" />
                刷新页面
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  }
}
