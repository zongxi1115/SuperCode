import React from "react";
import ReactDOM from "react-dom/client";
import { initializeBackendBaseUrl } from "@/lib/api-client";
import "./index.css";
import Router from "./router";

initializeBackendBaseUrl().finally(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(<Router />);
});
