import type { ButtonHTMLAttributes, ComponentType, ReactNode } from "react";
import type { TokenUsage } from "../types";

// ------------------------------------------------------------------ tones
// Status colors never carry meaning alone: every badge pairs an icon + label,
// and the label stays in ink (text never wears the data color).

export type Tone = "good" | "warning" | "serious" | "critical" | "neutral" | "accent";

const TONE_VAR: Record<Tone, string> = {
  good: "var(--good)",
  warning: "var(--warning)",
  serious: "var(--serious)",
  critical: "var(--critical)",
  neutral: "var(--muted)",
  accent: "var(--series-1)",
};

const TONE_ICON: Record<Tone, string> = {
  good: "✓",
  warning: "!",
  serious: "!",
  critical: "✕",
  neutral: "–",
  accent: "•",
};

export function toneVar(tone: Tone): string {
  return TONE_VAR[tone];
}

export function actionTone(action: string): Tone {
  switch (action) {
    case "ALLOW":
    case "EXECUTED":
    case "COMPLETED":
    case "passed":
    case "executed":
    case "ACTIVE":
      return "good";
    case "FLAG":
    case "flagged":
    case "redacted":
    case "PENDING":
    case "pending":
    case "partial":
    case "weak":
      return "warning";
    case "FAILED":
    case "failed":
      return "serious";
    case "BLOCK":
    case "DENIED":
    case "blocked":
    case "denied":
    case "CANCELLED":
      return "critical";
    case "APPROVED":
    case "PARSING":
    case "SCREENING":
    case "EMBEDDING":
    case "INDEXING":
      return "accent";
    default:
      return "neutral";
  }
}

export function severityTone(severity: string): Tone {
  return ({ MEDIUM: "warning", HIGH: "serious", CRITICAL: "critical" } as Record<string, Tone>)[severity] ?? "neutral";
}

export function trustTone(level: string): Tone {
  return (
    (
      { VERIFIED: "good", HIGH: "good", MEDIUM: "warning", LOW: "serious", UNTRUSTED: "critical" } as Record<
        string,
        Tone
      >
    )[level] ?? "neutral"
  );
}

export function riskTone(risk: string): Tone {
  return (
    ({ LOW: "neutral", MEDIUM: "warning", HIGH: "serious", CRITICAL: "critical" } as Record<string, Tone>)[risk] ??
    "neutral"
  );
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

export function formatNumber(n: number): string {
  return n.toLocaleString();
}

/** "1,234 tokens" — prefixed with "~" when estimated, with the cost when there is one. */
export function formatTokens(usage: TokenUsage): string {
  const tokens = `${usage.estimated ? "~" : ""}${formatNumber(usage.total_tokens)} tokens`;
  return usage.cost_usd > 0 ? `${tokens} · $${usage.cost_usd.toFixed(4)}` : tokens;
}

type Icon = ComponentType<{ className?: string; strokeWidth?: number }>;

// ------------------------------------------------------------------ atoms
export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap text-ink"
      style={{ background: `color-mix(in srgb, ${TONE_VAR[tone]} 15%, transparent)` }}
    >
      <span aria-hidden style={{ color: TONE_VAR[tone] }} className="font-bold">
        {TONE_ICON[tone]}
      </span>
      {children}
    </span>
  );
}

export function Chip({ children, struck = false }: { children: ReactNode; struck?: boolean }) {
  return (
    <span
      className={`inline-block rounded-md border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-xs ${
        struck ? "text-muted line-through" : "text-ink-2"
      }`}
    >
      {children}
    </span>
  );
}

/** A colored icon tile (the icon carries no meaning on its own — always labelled). */
export function IconTile({ icon: I, tone = "accent", size = "md" }: { icon: Icon; tone?: Tone; size?: "sm" | "md" }) {
  const box = size === "sm" ? "h-8 w-8 rounded-lg" : "h-10 w-10 rounded-xl";
  return (
    <span
      aria-hidden
      className={`inline-flex shrink-0 items-center justify-center ${box}`}
      style={{ background: `color-mix(in srgb, ${TONE_VAR[tone]} 14%, transparent)`, color: TONE_VAR[tone] }}
    >
      <I className={size === "sm" ? "h-4 w-4" : "h-5 w-5"} strokeWidth={2} />
    </span>
  );
}

export function Card({
  title,
  subtitle,
  icon,
  actions,
  children,
  className = "",
  bodyClassName = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  icon?: Icon;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`flex min-w-0 flex-col rounded-xl border border-edge bg-surface p-5 shadow-card ${className}`}>
      {(title || actions) && (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            {icon && <IconTile icon={icon} size="sm" />}
            <div className="min-w-0">
              {title && <h2 className="text-[15px] font-semibold text-ink">{title}</h2>}
              {subtitle && <p className="mt-0.5 text-xs leading-relaxed text-ink-2">{subtitle}</p>}
            </div>
          </div>
          {actions}
        </header>
      )}
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

export function StatTile({
  label,
  value,
  note,
  icon,
  tone = "accent",
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  icon?: Icon;
  tone?: Tone;
}) {
  return (
    <div className="flex min-w-0 items-start gap-3 rounded-xl border border-edge bg-surface p-4 shadow-card">
      {icon && <IconTile icon={icon} tone={tone} />}
      <div className="min-w-0">
        <div className="text-xs font-medium text-ink-2">{label}</div>
        <div className="mt-0.5 text-2xl font-semibold tracking-tight text-ink">{value}</div>
        {note && <div className="mt-1 text-xs leading-relaxed text-muted">{note}</div>}
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        <p className="mt-1 text-sm leading-relaxed text-ink-2">{description}</p>
      </div>
      {actions}
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string; icon?: Icon; count?: number }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-edge">
      {tabs.map((t) => {
        const active = t.id === value;
        const I = t.icon;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            className={`-mb-px flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium whitespace-nowrap transition ${
              active ? "border-accent text-ink" : "border-transparent text-ink-2 hover:text-ink"
            }`}
          >
            {I && <I className="h-4 w-4" />}
            {t.label}
            {t.count !== undefined && (
              <span className="tabular rounded-full bg-surface-2 px-1.5 text-xs text-ink-2">{t.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger" | "subtle";
  size?: "sm" | "md";
};

export function Button({ variant = "primary", size = "md", className = "", ...props }: ButtonProps) {
  const styles = {
    primary: "bg-accent text-white shadow-sm hover:brightness-110",
    ghost: "border border-edge bg-surface text-ink hover:bg-surface-2",
    danger: "bg-critical text-white hover:brightness-110",
    subtle: "text-ink-2 hover:bg-surface-2 hover:text-ink",
  }[variant];
  const sizes = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm";
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${sizes} ${styles} ${className}`}
    />
  );
}

export const inputClass =
  "w-full rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/20 focus:outline-none";

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="rounded-lg border border-edge bg-surface-2 px-3 py-2 text-sm text-ink">
      <span aria-hidden className="mr-1.5 font-bold" style={{ color: "var(--critical)" }}>
        ✕
      </span>
      {message}
    </div>
  );
}

export function Empty({ children, icon: I }: { children: ReactNode; icon?: Icon }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center text-sm text-muted">
      {I && <I className="h-8 w-8 opacity-50" strokeWidth={1.5} />}
      {children}
    </div>
  );
}

/** Horizontal 0–1 meter. The fill carries severity; the track is a lighter step. */
export function Meter({
  value,
  tone = "accent",
  markers = [],
  label,
}: {
  value: number;
  tone?: Tone;
  markers?: { at: number; label: string }[];
  label: string;
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={1}
      aria-valuenow={value}
      className="relative h-2 w-full rounded-full"
      style={{ background: `color-mix(in srgb, ${TONE_VAR[tone]} 18%, transparent)` }}
    >
      <div className="h-2 rounded-full transition-[width]" style={{ width: `${pct}%`, background: TONE_VAR[tone] }} />
      {markers.map((m) => (
        <div
          key={m.label}
          title={m.label}
          className="absolute -top-1 h-4 w-0.5 rounded"
          style={{ left: `${m.at * 100}%`, background: "var(--ink-2)" }}
        />
      ))}
    </div>
  );
}

// -------------------------------------------------------------- rich text
// Renders the small markdown subset the agents produce — **bold**, `code`,
// headings, bullets and pipe tables — as React elements. No HTML injection.

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|_[^_\s][^_]*_|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) out.push(<strong key={m.index}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`"))
      out.push(
        <code key={m.index} className="rounded bg-surface-2 px-1 font-mono text-[0.85em]">
          {tok.slice(1, -1)}
        </code>,
      );
    else out.push(<em key={m.index}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function RichText({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.includes(" | ")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes(" | ")) rows.push(lines[i++].split(" | ").map((c) => c.trim()));
      const [head, ...body] = rows;
      blocks.push(
        <div key={`t${i}`} className="my-2 overflow-x-auto rounded-lg border border-edge">
          <table className="tabular w-full text-xs">
            <thead className="bg-surface-2">
              <tr>
                {head.map((c, j) => (
                  <th key={j} className="px-2.5 py-1.5 text-left font-semibold text-ink-2">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((r, k) => (
                <tr key={k} className="border-t border-edge">
                  {r.map((c, j) => (
                    <td key={j} className="px-2.5 py-1.5 text-ink">
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^#{1,6}\s/.test(line)) {
      blocks.push(
        <p key={i} className="mt-2 font-semibold">
          {inline(line.replace(/^#+\s*/, ""))}
        </p>,
      );
    } else if (/^\s*[-*]\s/.test(line)) {
      blocks.push(
        <p key={i} className="pl-4 -indent-3">
          • {inline(line.replace(/^\s*[-*]\s/, ""))}
        </p>,
      );
    } else if (line.trim()) {
      blocks.push(<p key={i}>{inline(line)}</p>);
    } else {
      blocks.push(<div key={i} className="h-2" />);
    }
    i++;
  }
  return <div className="space-y-0.5 text-sm leading-relaxed break-words">{blocks}</div>;
}
