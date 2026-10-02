import {
  Activity,
  Bot,
  Database,
  Gauge,
  LayoutDashboard,
  LogOut,
  Menu,
  Monitor,
  Moon,
  ScrollText,
  ShieldAlert,
  Sun,
  X,
} from "lucide-react";
import { useEffect, useState, type ComponentType, type ReactNode } from "react";

import { isStaff, useAuth } from "./auth";
import { Logo } from "./components/Logo";
import { useApi } from "./hooks";
import AgentConsole from "./pages/AgentConsole";
import Events from "./pages/Events";
import FirewallLab from "./pages/FirewallLab";
import KnowledgeBase from "./pages/KnowledgeBase";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Policies from "./pages/Policies";
import Trust from "./pages/Trust";

interface Route {
  id: string;
  label: string;
  group: "Monitor" | "Operate" | "Govern";
  icon: ComponentType<{ className?: string }>;
  staffOnly: boolean;
  render: () => ReactNode;
}

const ROUTES: Route[] = [
  {
    id: "overview",
    label: "Overview",
    group: "Monitor",
    icon: LayoutDashboard,
    staffOnly: true,
    render: () => <Overview />,
  },
  {
    id: "events",
    label: "Security events",
    group: "Monitor",
    icon: Activity,
    staffOnly: true,
    render: () => <Events />,
  },
  { id: "trust", label: "Trust", group: "Monitor", icon: Gauge, staffOnly: true, render: () => <Trust /> },
  {
    id: "knowledge",
    label: "Data & RAG",
    group: "Operate",
    icon: Database,
    staffOnly: false,
    render: () => <KnowledgeBase />,
  },
  {
    id: "console",
    label: "Agent console",
    group: "Operate",
    icon: Bot,
    staffOnly: false,
    render: () => <AgentConsole />,
  },
  {
    id: "firewall",
    label: "Firewall lab",
    group: "Operate",
    icon: ShieldAlert,
    staffOnly: false,
    render: () => <FirewallLab />,
  },
  {
    id: "policies",
    label: "Policies & tools",
    group: "Govern",
    icon: ScrollText,
    staffOnly: false,
    render: () => <Policies />,
  },
];

/** The route id in the URL hash ("" when none — the caller picks the default). */
function useHashRoute(): [string, (id: string) => void] {
  const read = () => window.location.hash.replace(/^#\/?/, "");
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onHash = () => setRoute(read());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return [route, (id) => (window.location.hash = `/${id}`)];
}

type Theme = "light" | "dark" | "system";
const THEME_ORDER: Theme[] = ["system", "light", "dark"];
const THEME_ICON = { system: Monitor, light: Sun, dark: Moon };

function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem("aegisai.theme") as Theme) || "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("aegisai.theme", theme);
    } catch {
      /* preference just won't persist */
    }
  }, [theme]);
  return [theme, setTheme];
}

function initials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}

export default function App() {
  const { user, ready, logout } = useAuth();
  const staff = isStaff(user);
  const [route, go] = useHashRoute();
  const [theme, setTheme] = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const runtime = useApi<{ brain: string }>(user ? "/api/agents/runtime" : null);

  if (!ready) return null;
  if (!user) return <Login />;

  const routes = ROUTES.filter((r) => staff || !r.staffOnly);
  const current = routes.find((r) => r.id === route) ?? routes[0];
  const ThemeIcon = THEME_ICON[theme];
  const nextTheme = THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length];
  const role = user.role.replace("_", " ").toLowerCase();

  const nav = (
    <nav className="flex h-full flex-col">
      <div className="flex items-center gap-3 px-5 py-5">
        <Logo />
        <div>
          <div className="text-[15px] font-semibold text-white">AegisAI</div>
          <div className="text-[11px] text-nav-ink-2">Zero-trust agent security</div>
        </div>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-3 py-2">
        {(["Monitor", "Operate", "Govern"] as const).map((group) => {
          const items = routes.filter((r) => r.group === group);
          if (!items.length) return null;
          return (
            <div key={group}>
              <div className="px-3 pb-1.5 text-[11px] font-semibold tracking-wider text-nav-ink-2 uppercase">
                {group}
              </div>
              {items.map((r) => {
                const active = current.id === r.id;
                const I = r.icon;
                return (
                  <button
                    key={r.id}
                    onClick={() => {
                      go(r.id);
                      setMenuOpen(false);
                    }}
                    aria-current={active ? "page" : undefined}
                    className={`group relative mb-0.5 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition ${
                      active ? "font-medium text-white" : "text-nav-ink hover:bg-[var(--nav-hover)]"
                    }`}
                    style={active ? { background: "var(--nav-active)" } : undefined}
                  >
                    {active && <span className="absolute top-1.5 bottom-1.5 left-0 w-0.5 rounded-full bg-accent" />}
                    <I
                      className={`h-[18px] w-[18px] ${active ? "text-accent" : "text-nav-ink-2 group-hover:text-nav-ink"}`}
                    />
                    {r.label}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
      <div className="m-3 rounded-xl p-3" style={{ background: "var(--nav-hover)" }}>
        <div className="flex items-center gap-3">
          <span className="brand-gradient flex h-9 w-9 items-center justify-center rounded-full text-xs font-semibold text-white">
            {initials(user.username)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-white">{user.username}</div>
            <div className="truncate text-xs text-nav-ink-2 capitalize">{role}</div>
          </div>
        </div>
        <button
          onClick={logout}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-white/10 px-3 py-1.5 text-sm text-nav-ink transition hover:bg-white/10"
        >
          <LogOut className="h-4 w-4" /> Log out
        </button>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen">
      {/* desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 bg-nav lg:block">{nav}</aside>

      {/* mobile drawer */}
      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMenuOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85%] bg-nav shadow-xl">
            <button
              onClick={() => setMenuOpen(false)}
              className="absolute top-5 right-3 rounded-md p-1 text-nav-ink-2 hover:text-white"
              aria-label="Close menu"
            >
              <X className="h-5 w-5" />
            </button>
            {nav}
          </aside>
        </div>
      )}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 border-b border-edge bg-surface/85 backdrop-blur">
          <div className="flex h-14 items-center gap-3 px-4 md:px-8">
            <button
              className="rounded-lg p-1.5 text-ink-2 hover:bg-surface-2 lg:hidden"
              onClick={() => setMenuOpen(true)}
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div className="flex min-w-0 items-center gap-2 text-sm">
              <span className="hidden text-muted sm:inline">AegisAI</span>
              <span className="hidden text-muted sm:inline">/</span>
              <span className="truncate font-medium text-ink">{current.label}</span>
            </div>
            <div className="ml-auto flex items-center gap-2">
              {runtime.data && (
                <span
                  className="hidden items-center gap-1.5 rounded-full border border-edge px-2.5 py-1 text-xs text-ink-2 md:inline-flex"
                  title="The model that plans and answers for the agents"
                >
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--good)" }} />
                  brain: <span className="font-mono text-ink">{runtime.data.brain}</span>
                </span>
              )}
              <button
                onClick={() => setTheme(nextTheme)}
                className="rounded-lg p-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
                title={`Theme: ${theme} (click for ${nextTheme})`}
                aria-label={`Theme: ${theme}`}
              >
                <ThemeIcon className="h-[18px] w-[18px]" />
              </button>
              <div className="hidden items-center gap-2 border-l border-edge pl-3 sm:flex">
                <span className="brand-gradient flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold text-white">
                  {initials(user.username)}
                </span>
                <div className="leading-tight">
                  <div className="text-sm font-medium text-ink">{user.username}</div>
                  <div className="text-[11px] text-muted capitalize">{role}</div>
                </div>
              </div>
              <button
                onClick={logout}
                className="ml-1 inline-flex items-center gap-1.5 rounded-lg border border-edge px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-2"
              >
                <LogOut className="h-4 w-4" />
                <span>Log out</span>
              </button>
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-4 py-6 md:px-8 md:py-8">{current.render()}</main>
      </div>
    </div>
  );
}
