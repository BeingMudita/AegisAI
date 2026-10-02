import { ChevronRight } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

import { IconTile, type Tone } from "./ui";

export interface Stage {
  id: string;
  label: string;
  icon: ComponentType<{ className?: string; strokeWidth?: number }>;
  value: ReactNode;
  detail: ReactNode;
  tone?: Tone;
  active?: boolean;
}

/** A left-to-right flow of stages; the active stage and its connectors animate. */
export function PipelineFlow({ stages }: { stages: Stage[] }) {
  return (
    <ol className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:flex xl:items-stretch xl:gap-0">
      {stages.map((s, i) => (
        <li key={s.id} className="flex min-w-0 items-stretch xl:flex-1">
          <div
            className={`flex w-full min-w-0 flex-col gap-3 rounded-xl border p-3.5 transition ${
              s.active ? "border-accent bg-surface shadow-card ring-2 ring-accent/20" : "border-edge bg-surface-2/60"
            }`}
          >
            <div className="flex items-center gap-2.5">
              <IconTile icon={s.icon} tone={s.tone ?? "accent"} size="sm" />
              <span className="min-w-0 text-xs leading-tight font-semibold text-ink">{s.label}</span>
            </div>
            <div className="min-w-0">
              <div className="truncate text-lg font-semibold tracking-tight text-ink">{s.value}</div>
              <div className="mt-0.5 text-[11px] leading-snug text-ink-2">{s.detail}</div>
            </div>
          </div>
          {i < stages.length - 1 && (
            <div className="hidden w-6 shrink-0 items-center justify-center xl:flex" aria-hidden>
              {s.active || stages[i + 1].active ? (
                <span className="flow-active h-0.5 w-full" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted" />
              )}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}
