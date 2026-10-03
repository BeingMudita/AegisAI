import { ArrowRight, Database, KeyRound, ShieldCheck, Workflow } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { Logo } from "../components/Logo";
import { Button, ErrorNote, inputClass } from "../components/ui";

const DEV_ACCOUNTS = [["admin", "admin123", "Administrator"], ["analyst", "analyst123", "Security analyst"], ["agent", "agent123", "Agent operator"]];

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setError(null);
    try { await login(username, password); }
    catch (err) { setError(err instanceof Error ? err.message : "Sign-in failed. Please try again."); }
    finally { setBusy(false); }
  }
  return <div className="auth-shell">
    <section className="auth-story">
      <div className="flex items-center gap-3"><Logo className="h-9 w-9" /><span className="text-xl font-semibold tracking-tight">AegisAI</span><span className="ml-auto text-[10px] tracking-widest text-white/60">SECURITY WORKSPACE</span></div>
      <div>
        <h1>More capable agents.<br />Clearer boundaries.</h1>
        <p>A practical workspace to connect your knowledge, govern agent actions, and understand every security decision.</p>
        <ul className="auth-features">
          <li><Database className="h-5 w-5" /><span>Give agents knowledge you can trace.</span></li>
          <li><Workflow className="h-5 w-5" /><span>Control tools with policy and trust.</span></li>
          <li><ShieldCheck className="h-5 w-5" /><span>Follow every request from input to evidence.</span></li>
        </ul>
      </div>
      <footer className="text-[11px] text-white/60">BUILT AROUND ONE PRINCIPLE: VERIFY BEFORE YOU ACT.</footer>
    </section>
    <section className="auth-form" aria-label="Sign in">
      <div>
        <span className="eyebrow">Welcome to your workspace</span>
        <h2 className="mt-3 text-3xl font-semibold tracking-tight">Sign in to AegisAI</h2>
        <p className="mt-3 mb-8 text-sm leading-relaxed text-ink-2">Use your organization’s credentials to continue.</p>
        <form onSubmit={submit} className="space-y-5">
          <label className="block text-sm"><span className="mb-2 block font-medium">Username</span><input className={inputClass} value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} required disabled={busy} placeholder="Enter your username" /></label>
          <label className="block text-sm"><span className="mb-2 block font-medium">Password</span><input className={inputClass} type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required disabled={busy} placeholder="Enter your password" /></label>
          <ErrorNote message={error} />
          <Button type="submit" disabled={busy || !username || !password} className="w-full py-3">{busy ? "Signing in…" : "Continue to workspace"}<ArrowRight className="ml-auto h-4 w-4" /></Button>
        </form>
        <p className="mt-5 text-xs leading-relaxed text-ink-2">Need access? Contact the administrator responsible for your deployment.</p>
        {import.meta.env.DEV && <details className="mt-10 rounded-lg border border-edge p-4"><summary className="flex items-center gap-2 text-xs font-medium"><KeyRound className="h-4 w-4" /> Local development accounts</summary><p className="mt-3 text-xs text-ink-2">Only shown by the development server. Select an account to fill the form.</p><div className="mt-3 space-y-2">{DEV_ACCOUNTS.map(([u, p, desc]) => <button disabled={busy} key={u} type="button" onClick={() => { setUsername(u); setPassword(p); }} className="flex w-full justify-between gap-3 rounded border border-edge px-3 py-2 text-xs hover:bg-surface-2"><span>{desc}</span><code>{u}</code></button>)}</div></details>}
      </div>
    </section>
  </div>;
}
