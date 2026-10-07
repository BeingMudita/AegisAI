import {
  Activity,
  Bot,
  Database,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  GitBranch,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Network,
  Radar,
  ScanLine,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  Sun,
  UserCheck,
  X,
} from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";

import { isStaff, useAuth } from "./auth";
import { Logo } from "./components/Logo";
import { useApi } from "./hooks";
import Login from "./pages/Login";
import { PageBoundary } from "./components/PageBoundary";

const AgentConsole = lazy(() => import("./pages/AgentConsole"));
const Events = lazy(() => import("./pages/Events"));
const FirewallLab = lazy(() => import("./pages/FirewallLab"));
const KnowledgeBase = lazy(() => import("./pages/KnowledgeBase"));
const Overview = lazy(() => import("./pages/Overview"));
const Policies = lazy(() => import("./pages/Policies"));
const Trust = lazy(() => import("./pages/Trust"));
const Architecture = lazy(() => import("./pages/Architecture"));
const Sessions = lazy(() => import("./pages/Sessions"));
const Approvals = lazy(() => import("./pages/Approvals"));
const RedTeam = lazy(() => import("./pages/RedTeam"));
const ThreatCoverage = lazy(() => import("./pages/ThreatCoverage"));
const AttackReplay = lazy(() => import("./pages/AttackReplay"));
const Scanner = lazy(() => import("./pages/Scanner"));

interface Route {
  id: string;
  label: string;
  group: "Monitor" | "Operate" | "Assure" | "Govern";
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
    staffOnly: false,
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
    id: "sessions",
    label: "Attack reconstruction",
    group: "Monitor",
    icon: GitBranch,
    staffOnly: false,
    render: () => <Sessions />,
  },
  {
    id: "replay",
    label: "Attack replay",
    group: "Monitor",
    icon: Radar,
    staffOnly: false,
    render: () => <AttackReplay />,
  },
  {
    id: "knowledge",
    label: "Knowledge base",
    group: "Operate",
    icon: Database,
    staffOnly: false,
    render: () => <KnowledgeBase />,
  },
  {
    id: "console",
    label: "Agent workspace",
    group: "Operate",
    icon: Bot,
    staffOnly: false,
    render: () => <AgentConsole />,
  },
  {
    id: "approvals",
    label: "Approvals",
    group: "Operate",
    icon: UserCheck,
    staffOnly: true,
    render: () => <Approvals />,
  },
  {
    id: "scanner",
    label: "Security scanner",
    group: "Assure",
    icon: ScanLine,
    staffOnly: false,
    render: () => <Scanner />,
  },
  {
    id: "redteam",
    label: "Red-team lab",
    group: "Assure",
    icon: FlaskConical,
    staffOnly: true,
    render: () => <RedTeam />,
  },
  {
    id: "coverage",
    label: "Threat coverage",
    group: "Assure",
    icon: ShieldCheck,
    staffOnly: false,
    render: () => <ThreatCoverage />,
  },
  {
    id: "architecture", label: "Architecture", group: "Govern", icon: Network,
    staffOnly: false, render: () => <Architecture />,
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
      const stored = localStorage.getItem("aegisai.theme");
      return THEME_ORDER.includes(stored as Theme) ? stored as Theme : "light";
    } catch {
      return "light";
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
  const drawer = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const runtime = useApi<{ brain: string }>(user ? "/api/agents/runtime" : null);
  const approvals = useApi<{ pending: number }>(isStaff(user) ? "/api/approvals/pending-count" : null, 5000);
  const pendingApprovals = approvals.data?.pending ?? 0;

  useEffect(() => {
    if (!menuOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const elements = () => Array.from(drawer.current?.querySelectorAll<HTMLElement>("button, a[href]") ?? []);
    elements()[0]?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
      if (event.key !== "Tab") return;
      const items = elements();
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", key);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", key); menuButton.current?.focus(); };
  }, [menuOpen]);

  useEffect(() => {
    document.title = `AegisAI · ${ROUTES.find(r => r.id === route)?.label ?? "Workspace"}`;
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [route]);

  if (!ready) return <div className="flex min-h-screen items-center justify-center text-sm text-ink-2" role="status">Restoring your workspace…</div>;
  if (!user) return <Login />;

  const routes = ROUTES.filter((r) => staff || !r.staffOnly);
  const current = routes.find((r) => r.id === route) ?? routes[0];
  const ThemeIcon = THEME_ICON[theme];
  const nextTheme = THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length];
  const role = user.role.replace("_", " ").toLowerCase();

  const nav = (
    <nav className="workspace-nav flex h-full flex-col" aria-label="Main navigation">
      <div className="flex items-center gap-3 px-5 py-5">
        <Logo />
        <div>
          <div className="text-[17px] font-semibold tracking-tight text-nav-ink">AegisAI<span className="ml-2 rounded border border-edge px-1 py-0.5 text-[9px] font-medium tracking-wide text-nav-ink-2">CONSOLE</span></div>
          <div className="mt-1 text-[11px] text-nav-ink-2">Agent security workspace</div>
        </div>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-3 py-2">
        {(["Monitor", "Operate", "Assure", "Govern"] as const).map((group) => {
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
                      active ? "font-semibold text-nav-ink" : "text-nav-ink hover:bg-[var(--nav-hover)]"
                    }`}
                    style={active ? { background: "var(--nav-active)" } : undefined}
                  >
                    {active && <span className="absolute top-1.5 bottom-1.5 left-0 w-0.5 rounded-full bg-accent" />}
                    <I
                      className={`h-[18px] w-[18px] ${active ? "text-accent" : "text-nav-ink-2 group-hover:text-nav-ink"}`}
                    />
                    {r.label}
                    {r.id === "approvals" && pendingApprovals > 0 && (
                      <span
                        className="ml-auto rounded-full px-1.5 text-[11px] font-semibold text-white"
                        style={{ background: "var(--warning)" }}
                        aria-label={`${pendingApprovals} waiting`}
                      >
                        {pendingApprovals}
                      </span>
                    )}
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
            <div className="truncate text-sm font-medium text-nav-ink">{user.username}</div>
            <div className="truncate text-xs text-nav-ink-2 capitalize">{role}</div>
          </div>
        </div>
        <button
          onClick={logout}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-edge px-3 py-1.5 text-sm text-nav-ink transition hover:bg-surface-2"
        >
          <LogOut className="h-4 w-4" /> Log out
        </button>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen">
      <a className="skip-link" href="#main-content" onClick={e => { e.preventDefault(); document.getElementById("main-content")?.focus(); }}>Skip to content</a>
      {/* desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-edge bg-nav lg:block">{nav}</aside>

      {/* mobile drawer */}
      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMenuOpen(false)} />
          <aside ref={drawer} role="dialog" aria-modal="true" aria-label="Navigation menu" className="absolute inset-y-0 left-0 w-72 max-w-[85%] bg-nav shadow-xl">
            <button
              onClick={() => setMenuOpen(false)}
              className="absolute top-5 right-3 rounded-md p-1 text-nav-ink-2 hover:text-ink"
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
              ref={menuButton}
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
                  {runtime.data.brain === "rule_based" ? "Rule-based planner" : runtime.data.brain}
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
            </div>
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="mx-auto max-w-[1600px] px-4 py-6 md:px-8 md:py-8"><PageBoundary key={current.id}><Suspense fallback={<p className="py-12 text-sm text-ink-2" role="status">Loading {current.label.toLowerCase()}…</p>}>{current.render()}</Suspense></PageBoundary></main>
      </div>
    </div>
  );
}
