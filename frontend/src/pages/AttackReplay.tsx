import {
  ArrowRight,
  Ban,
  CheckCircle2,
  FlaskConical,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  Badge,
  Button,
  Card,
  IconTile,
  Meter,
  PageHeader,
  toneVar,
  type Tone,
} from "../components/ui";
import {
  REPLAYS,
  STATUS_TONE,
  type AttackReplay,
  type GatewayCheck,
  type ReplayStep,
  type TrustReading,
} from "../replays";

const SPEEDS = [1, 1.6, 0.6] as const;
const BASE_MS = 1150;

function TrustMeter({ trust }: { trust: TrustReading }) {
  const tone: Tone = trust.below ? "critical" : "warning";
  return (
    <div className="mt-3 rounded-lg border border-edge bg-surface-2/50 p-3">
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-xs font-semibold text-ink-2">Source trust</span>
        <span className="tabular text-sm font-semibold" style={{ color: toneVar(tone) }}>
          {trust.score.toFixed(2)}
        </span>
      </div>
      <Meter value={trust.score} tone={tone} label="Source trust" markers={[{ at: trust.floor, label: trust.floorLabel }]} />
      <div className="mt-1.5 text-[11px] text-ink-2">
        {trust.below ? "Below" : "Above"} the {trust.floorLabel.toLowerCase()} —{" "}
        {trust.below ? "quarantined." : "sanitized and allowed through."}
      </div>
    </div>
  );
}

function CheckList({ checks }: { checks: GatewayCheck[] }) {
  return (
    <ul className="mt-3 space-y-1.5">
      {checks.map((c) => (
        <li key={c.checkpoint} className="flex items-start gap-2 text-xs">
          {c.passed ? (
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: "var(--good)" }} />
          ) : (
            <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: "var(--critical)" }} />
          )}
          <span className="min-w-0">
            <span className="font-mono font-semibold text-ink uppercase">{c.checkpoint}</span>
            <span className={c.passed ? "text-ink-2" : "font-semibold"} style={c.passed ? undefined : { color: "var(--critical)" }}>
              {" "}
              {c.passed ? "passed" : "FAILED"}
            </span>
            <span className="block text-ink-2">{c.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function ArtifactBlock({ artifact }: { artifact: NonNullable<ReplayStep["artifact"]> }) {
  return (
    <figure className="mt-3 overflow-hidden rounded-lg border border-edge bg-surface-2/60">
      <figcaption className="flex items-center justify-between border-b border-edge px-3 py-1.5 text-[11px]">
        <span className="font-semibold text-ink">{artifact.title}</span>
        <span className="text-muted">{artifact.meta}</span>
      </figcaption>
      <pre className="overflow-x-auto px-3 py-2.5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-ink-2">
        {artifact.body}
      </pre>
    </figure>
  );
}

/** One node in the vertical kill-chain: rail (icon + connector) on the left, card on the right. */
function TimelineNode({
  step,
  index,
  total,
  revealed,
  active,
  nextRevealed,
  severed,
}: {
  step: ReplayStep;
  index: number;
  total: number;
  revealed: boolean;
  active: boolean;
  nextRevealed: boolean;
  severed: boolean;
}) {
  const tone = STATUS_TONE[step.status];
  const color = toneVar(tone);
  const ghost = !!step.unreached;
  const isLast = index === total - 1;

  return (
    <li className="flex items-stretch gap-3 sm:gap-4">
      {/* rail */}
      <div className="flex w-10 shrink-0 flex-col items-center sm:w-11">
        <div
          className={`relative transition-opacity duration-500 ${revealed ? "opacity-100" : "opacity-0"} ${active ? "replay-active" : ""}`}
          style={active ? ({ ["--pulse" as string]: `color-mix(in srgb, ${color} 45%, transparent)`, borderRadius: "0.75rem" } as React.CSSProperties) : undefined}
        >
          <span className={ghost ? "opacity-40 grayscale" : undefined}>
            <IconTile icon={step.icon} tone={ghost ? "neutral" : tone} />
          </span>
        </div>
        {!isLast && (
          <div className="relative my-1 w-0.5 flex-1">
            <div className="absolute inset-0 rounded-full bg-edge" />
            {nextRevealed && !severed && (
              <div
                className="flow-active-v absolute inset-0 rounded-full"
                style={{ ["--flow" as string]: color } as React.CSSProperties}
              />
            )}
            {nextRevealed && severed && (
              <span
                className="absolute top-1/2 left-1/2 flex h-6 w-6 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border bg-surface"
                style={{ borderColor: "var(--critical)" }}
                title="Attack severed here"
              >
                <Ban className="h-3.5 w-3.5" style={{ color: "var(--critical)" }} />
              </span>
            )}
          </div>
        )}
      </div>

      {/* card */}
      <div
        className={`mb-4 min-w-0 flex-1 transition-all duration-500 ${revealed ? "replay-step-enter opacity-100" : "pointer-events-none translate-y-2 opacity-0"}`}
      >
        <div
          className={`rounded-xl border p-4 ${ghost ? "border-dashed" : ""}`}
          style={{
            borderColor: ghost ? "var(--border)" : active ? color : "var(--border)",
            background: ghost ? "transparent" : `color-mix(in srgb, ${color} ${active ? 9 : 5}%, var(--surface))`,
            opacity: ghost ? 0.7 : 1,
          }}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="eyebrow">{step.label}</span>
            <Badge tone={ghost ? "neutral" : tone}>
              {step.stopped ? "stopped here" : ghost ? "never reached" : step.status}
            </Badge>
          </div>
          <div className="mt-1 text-[15px] font-semibold tracking-tight text-ink">{step.headline}</div>
          <p className="mt-1 text-sm leading-relaxed text-ink-2">{step.detail}</p>
          {step.artifact && <ArtifactBlock artifact={step.artifact} />}
          {step.trust && <TrustMeter trust={step.trust} />}
          {step.checks && <CheckList checks={step.checks} />}
        </div>
      </div>
    </li>
  );
}

function OutcomeBanner({ replay, revealed }: { replay: AttackReplay; revealed: boolean }) {
  const tone = STATUS_TONE[replay.outcome.status];
  const color = toneVar(tone);
  return (
    <div
      className={`rounded-xl border-2 p-4 transition-all duration-500 ${revealed ? "opacity-100" : "translate-y-2 opacity-0"}`}
      style={{ borderColor: color, background: `color-mix(in srgb, ${color} 10%, var(--surface))` }}
    >
      <div className="flex items-center gap-3">
        <IconTile icon={replay.outcome.status === "safe" ? CheckCircle2 : Ban} tone={tone} />
        <div className="min-w-0">
          <div className="text-lg font-semibold tracking-tight" style={{ color }}>
            {replay.outcome.label}
          </div>
          <p className="mt-0.5 text-sm leading-relaxed text-ink-2">{replay.outcome.note}</p>
        </div>
      </div>
    </div>
  );
}

function ReplayStage({ replay }: { replay: AttackReplay }) {
  // cursor = index of the last revealed step; -1 before playback starts.
  const [cursor, setCursor] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(0);
  const timer = useRef<number | undefined>(undefined);
  const total = replay.steps.length;
  const done = cursor >= total - 1;

  // Reset whenever the selected simulation changes, then auto-start.
  useEffect(() => {
    setCursor(-1);
    setPlaying(true);
  }, [replay.id]);

  const advance = useCallback(() => setCursor((c) => Math.min(c + 1, total - 1)), [total]);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!playing) return;
    if (done) {
      setPlaying(false);
      return;
    }
    timer.current = window.setTimeout(advance, BASE_MS / SPEEDS[speed]);
    return () => window.clearTimeout(timer.current);
  }, [playing, cursor, done, advance, speed]);

  function restart() {
    setCursor(-1);
    setPlaying(true);
  }
  function toggle() {
    if (done) restart();
    else setPlaying((p) => !p);
  }

  return (
    <Card
      title={replay.title}
      subtitle={replay.summary}
      icon={FlaskConical}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="critical">{replay.owasp.split(" ")[0]}</Badge>
          <a
            className="inline-flex items-center gap-1 rounded-full border border-edge px-2 py-0.5 text-xs text-ink-2 hover:text-ink"
            href="#/redteam"
            title="Run this scenario live in the Red-team lab"
          >
            live: {replay.scenarioId} <ArrowRight className="h-3 w-3" />
          </a>
        </div>
      }
    >
      {/* transport */}
      <div className="mb-5 flex flex-wrap items-center gap-2 rounded-xl border border-edge bg-surface-2/50 p-2.5">
        <Button size="sm" variant="ghost" onClick={() => setCursor((c) => Math.max(c - 1, 0))} disabled={cursor <= 0} aria-label="Step back">
          <SkipBack className="h-4 w-4" />
        </Button>
        <Button size="sm" onClick={toggle} className="min-w-[104px]">
          {done ? <RotateCcw className="h-4 w-4" /> : playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          {done ? "Replay" : playing ? "Pause" : "Play"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setPlaying(false);
            advance();
          }}
          disabled={done}
          aria-label="Step forward"
        >
          <SkipForward className="h-4 w-4" />
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setSpeed((s) => (s + 1) % SPEEDS.length)} className="tabular" title="Playback speed">
          {SPEEDS[speed]}×
        </Button>
        <div className="ml-auto flex items-center gap-2">
          <span className="tabular text-xs text-ink-2">
            {Math.max(cursor + 1, 0)} / {total}
          </span>
          <div className="h-1.5 w-28 overflow-hidden rounded-full bg-edge">
            <div
              className="h-full rounded-full transition-[width] duration-500"
              style={{ width: `${((cursor + 1) / total) * 100}%`, background: "var(--accent)" }}
            />
          </div>
        </div>
      </div>

      {/* vertical kill-chain */}
      <ol className="list-none">
        {replay.steps.map((step, i) => (
          <TimelineNode
            key={step.id}
            step={step}
            index={i}
            total={total}
            revealed={i <= cursor}
            active={i === cursor && !done}
            nextRevealed={i + 1 <= cursor}
            severed={!!step.stopped || !!replay.steps[i + 1]?.unreached}
          />
        ))}
      </ol>

      <div className="mt-1 pl-[3.25rem] sm:pl-[3.75rem]">
        <OutcomeBanner replay={replay} revealed={done} />
      </div>
    </Card>
  );
}

export default function AttackReplay() {
  const [selectedId, setSelectedId] = useState(REPLAYS[0].id);
  const replay = useMemo(() => REPLAYS.find((r) => r.id === selectedId) ?? REPLAYS[0], [selectedId]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attack replay — digital twin"
        description="A safe mirror of the live pipeline, for the examiner. Replay a captured attack frame by frame and watch exactly how it travelled, what it tried to influence, what the agent proposed, and where AegisAI severed it. Every simulation maps to a real red-team scenario you can re-run live."
      />

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        <Card title="Simulations" subtitle={`${REPLAYS.length} captured attacks`}>
          <ul className="space-y-1.5">
            {REPLAYS.map((r) => {
              const active = r.id === selectedId;
              const tone = STATUS_TONE[r.outcome.status];
              return (
                <li key={r.id}>
                  <button
                    onClick={() => setSelectedId(r.id)}
                    aria-current={active ? "true" : undefined}
                    className={`w-full rounded-lg border p-3 text-left transition ${
                      active ? "border-accent bg-accent/5" : "border-edge hover:bg-surface-2"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[11px] text-muted">#{r.id}</span>
                      <Badge tone={tone}>{r.outcome.label.split(" ")[0]}</Badge>
                    </div>
                    <div className="mt-1 text-sm font-semibold text-ink">{r.title}</div>
                    <div className="mt-0.5 text-[11px] text-ink-2">{r.family}</div>
                  </button>
                </li>
              );
            })}
          </ul>
        </Card>

        <ReplayStage key={replay.id} replay={replay} />
      </div>
    </div>
  );
}
