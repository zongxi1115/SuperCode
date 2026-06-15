import React from "react";
import ReactDOM from "react-dom/client";
import { AppErrorBoundary } from "@/components/app/app-error-boundary";
import { MessageProvider } from "@/components/ui/message";
import { initializeBackendBaseUrl } from "@/lib/api-client";
import "./index.css";
import Router from "./router";

initializeBackendBaseUrl().finally(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <MessageProvider>
      <AppErrorBoundary>
        <Router />
      </AppErrorBoundary>
    </MessageProvider>,
  );
});
