import { Database, KeyRound, ShieldCheck, Workflow } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useAuth } from "../auth";
import { Logo } from "../components/Logo";
import { Button, ErrorNote, inputClass } from "../components/ui";

const DEV_ACCOUNTS = [
  ["admin", "admin123", "Full control"],
  ["analyst", "analyst123", "Security analyst (read-only)"],
  ["agent", "agent123", "Agent identity"],
];

const FEATURES = [
  { icon: ShieldCheck, title: "Prompt-injection firewall", text: "Screens user input, documents and tool output." },
  { icon: Workflow, title: "Zero-trust tool gateway", text: "Every tool call passes policy, domain and trust checks." },
  { icon: Database, title: "Guarded RAG", text: "Poisoned documents are quarantined before agents see them." },
];

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden flex-col justify-between overflow-hidden bg-nav p-12 text-white lg:flex">
        <div
          className="pointer-events-none absolute -top-40 -right-40 h-[480px] w-[480px] rounded-full opacity-30 blur-3xl"
          style={{ background: "var(--brand)" }}
        />
        <div className="relative flex items-center gap-3">
          <Logo className="h-10 w-10" />
          <span className="text-xl font-semibold">AegisAI</span>
        </div>
        <div className="relative space-y-8">
          <h1 className="max-w-md text-4xl leading-tight font-semibold tracking-tight">
            A zero-trust security layer for autonomous AI agents.
          </h1>
          <ul className="space-y-5">
            {FEATURES.map((f) => (
              <li key={f.title} className="flex gap-4">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/10">
                  <f.icon className="h-5 w-5" />
                </span>
                <div>
                  <div className="font-medium">{f.title}</div>
                  <div className="text-sm text-nav-ink-2">{f.text}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="relative text-xs text-nav-ink-2">Local development build</div>
      </div>

      <div className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <Logo className="h-10 w-10" />
            <span className="text-xl font-semibold">AegisAI</span>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 mb-6 text-sm text-ink-2">Use one of the development accounts below.</p>
          <form onSubmit={submit} className="space-y-4">
            <label className="block text-sm">
              <span className="mb-1.5 block font-medium text-ink-2">Username</span>
              <input
                className={inputClass}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1.5 block font-medium text-ink-2">Password</span>
              <input
                className={inputClass}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </label>
            <ErrorNote message={error} />
            <Button type="submit" disabled={busy || !username || !password} className="w-full py-2.5">
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>
          <div className="mt-6 rounded-xl border border-edge bg-surface p-4 shadow-card">
            <p className="mb-3 flex items-center gap-2 text-sm font-medium text-ink">
              <KeyRound className="h-4 w-4 text-muted" /> Development accounts
            </p>
            <div className="space-y-1.5">
              {DEV_ACCOUNTS.map(([u, p, desc]) => (
                <button
                  key={u}
                  type="button"
                  className="flex w-full items-center justify-between rounded-lg border border-edge px-3 py-2 text-left text-sm hover:bg-surface-2"
                  onClick={() => {
                    setUsername(u);
                    setPassword(p);
                  }}
                >
                  <span className="font-mono text-ink">
                    {u} / {p}
                  </span>
                  <span className="text-xs text-muted">{desc}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
