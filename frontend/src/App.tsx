import type { ReactNode } from "react";
import { navigate, useRoute } from "./router";
import { Alerts } from "./screens/Alerts";
import { BriefScreen } from "./screens/Brief";
import { ResearchScreen } from "./screens/Research";
import { Search } from "./screens/Search";

export function App() {
  const route = useRoute();
  return (
    <div className="flex min-h-dvh flex-col">
      <main className="flex-1 pb-[calc(72px+env(safe-area-inset-bottom))]">
        {route.name === "brief" && <BriefScreen />}
        {route.name === "search" && <Search />}
        {route.name === "research" && <ResearchScreen key={route.ticker} ticker={route.ticker} section={route.section} />}
        {route.name === "alerts" && <Alerts />}
      </main>
      <TabBar active={route.name === "search" ? "research" : route.name} />
    </div>
  );
}

function TabBar({ active }: { active: string }) {
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-30 mx-auto flex max-w-[480px] border-t border-line bg-base/95 pb-[env(safe-area-inset-bottom)] backdrop-blur"
    >
      <Tab to="/" label="Brief" on={active === "brief"} icon={<BriefIcon />} />
      <Tab to="/research" label="Research" on={active === "research"} icon={<SearchIcon />} />
      <Tab to="/alerts" label="Alerts" on={active === "alerts"} icon={<BellIcon />} />
    </nav>
  );
}

function Tab({ to, label, on, icon }: { to: string; label: string; on: boolean; icon: ReactNode }) {
  return (
    <a
      href={to}
      onClick={(e) => {
        e.preventDefault();
        navigate(to);
      }}
      aria-current={on ? "page" : undefined}
      className={`flex h-16 flex-1 flex-col items-center justify-center gap-1 text-xs font-medium ${on ? "text-ink" : "text-muted"}`}
    >
      <span className={on ? "text-accent-ink" : ""}>{icon}</span>
      {label}
    </a>
  );
}

const iconProps = {
  width: 22,
  height: 22,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  "aria-hidden": true,
};

function BriefIcon() {
  return (
    <svg {...iconProps}>
      <path d="M5 7h14M5 12h10M5 17h6" />
    </svg>
  );
}
function SearchIcon() {
  return (
    <svg {...iconProps}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </svg>
  );
}
function BellIcon() {
  return (
    <svg {...iconProps}>
      <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" />
      <path d="M10 20.5a2 2 0 0 0 4 0" />
    </svg>
  );
}
