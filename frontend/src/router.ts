import { useEffect, useState } from "react";

// Five screens and one parameter do not need a routing library.

export type Route =
  | { name: "brief" }
  | { name: "search" }
  | { name: "research"; ticker: string; section: string | null }
  | { name: "alerts" }
  | { name: "settings" };

export function parse(path: string, hash: string): Route {
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "research" && parts[1]) {
    return { name: "research", ticker: decodeURIComponent(parts[1]).toUpperCase(), section: hash.slice(1) || null };
  }
  if (parts[0] === "research") return { name: "search" };
  if (parts[0] === "alerts") return { name: "alerts" };
  if (parts[0] === "settings") return { name: "settings" };
  return { name: "brief" };
}

export function navigate(to: string): void {
  if (to === location.pathname + location.hash) return;
  history.pushState(null, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo(0, 0);
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(location.pathname, location.hash));
  useEffect(() => {
    const on = () => setRoute(parse(location.pathname, location.hash));
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
  return route;
}
