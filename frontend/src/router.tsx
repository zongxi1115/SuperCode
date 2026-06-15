import { useEffect, useState } from "react";
import App from "./App";
import { LandingPage } from "@/components/landing/landing-page";
import { ConfluxModePage } from "@/conflux/ConfluxModePage";

function getPathname() {
  return window.location.pathname || "/";
}

function isLandingRoute(pathname: string) {
  return pathname === "/landing" || pathname === "/landing/";
}

function isConfluxRoute(pathname: string) {
  return pathname === "/conflux" || pathname === "/conflux/";
}

export default function Router() {
  const [pathname, setPathname] = useState(getPathname);

  useEffect(() => {
    const handleNavigation = () => setPathname(getPathname());

    window.addEventListener("popstate", handleNavigation);

    return () => {
      window.removeEventListener("popstate", handleNavigation);
    };
  }, []);

  if (isLandingRoute(pathname)) {
    return <LandingPage />;
  }

  if (isConfluxRoute(pathname)) {
    return <ConfluxModePage />;
  }

  return <App />;
}
