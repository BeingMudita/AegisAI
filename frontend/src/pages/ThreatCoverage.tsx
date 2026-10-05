import {
  CheckCircle2,
  CircleDashed,
  ExternalLink,
  FileCode2,
  Layers,
  ShieldCheck,
  ShieldQuestion,
  Target,
} from "lucide-react";
import { useState } from "react";

import { Badge, Card, Empty, ErrorNote, PageHeader, StatTile, Tabs, type Tone } from "../components/ui";
import { useApi } from "../hooks";
import type { CoverageReport, CoverageStatus, Evidence, ThreatCoverage } from "../types";

const STATUS: Record<CoverageStatus, { tone: Tone; label: string }> = {
  mitigated: { tone: "good", label: "mitigated" },
  partial: { tone: "warning", label: "partial" },
  gap: { tone: "critical", label: "gap" },
};

const EVIDENCE: Record<Evidence["status"], { tone: Tone; label: string }> = {
  pass: { tone: "good", label: "passed" },
  weak: { tone: "warning", label: "partly detected" },
  fail: { tone: "critical", label: "failed" },
  not_run: { tone: "neutral", label: "not run yet" },
  static: { tone: "accent", label: "CI test" },
};

function go(page: string | null) {
  if (page) window.location.hash = `/${page}`;
}

function Verified({ value }: { value: boolean | null }) {
  if (value === null) return <Badge tone="neutral">evidence pending</Badge>;
  return value ? <Badge tone="good">verified by last run</Badge> : <Badge tone="warning">partly verified</Badge>;
}

function ThreatDetail({ threat, controls }: { threat: ThreatCoverage; controls: CoverageReport["controls"] }) {
  const byId = Object.fromEntries(controls.map((c) => [c.id, c]));
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm text-ink-2">{threat.id}</span>
        <Badge tone={STATUS[threat.status].tone}>{STATUS[threat.status].label}</Badge>
        <Verified value={threat.verified} />
      </div>
      <div>
        <h3 className="text-lg font-semibold tracking-tight">{threat.name}</h3>
        <p className="mt-1 text-sm text-ink-2">{threat.description}</p>
      </div>
      <div>
        <div className="eyebrow mb-2">Controls</div>
        <ul className="space-y-2">
          {threat.controls.map((id) => {
            const c = byId[id];
            return (
              <li key={id} className="rounded-lg border border-edge p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{c?.name ?? id}</span>
                  {c?.page && (
                    <button onClick={() => go(c.page)} className="action-link text-xs">
                      See it <ExternalLink className="h-3 w-3" />
                    </button>
                  )}
                </div>
                {c && <p className="mt-0.5 text-xs text-ink-2">{c.description}</p>}
              </li>
            );
          })}
        </ul>
      </div>
      <div>
        <div className="eyebrow mb-2">Evidence</div>
        <ul className="space-y-1.5">
          {threat.evidence.map((e) => (
            <li key={`${e.kind}:${e.ref}`} className="flex flex-wrap items-center gap-2 text-sm">
              <Badge tone={EVIDENCE[e.status].tone}>{EVIDENCE[e.status].label}</Badge>
              <span className="text-xs text-muted">{e.kind}</span>
              <span className={e.kind === "test" ? "font-mono text-xs" : ""}>{e.label}</span>
              {e.detail && <span className="text-xs text-ink-2">— {e.detail}</span>}
            </li>
          ))}
        </ul>
      </div>
      <div
        className="rounded-lg border-l-2 p-3 text-sm"
        style={{ borderColor: "var(--warning)", background: "var(--surface-2)" }}
      >
        <div className="eyebrow mb-1">Residual risk</div>
        {threat.residual}
      </div>
    </div>
  );
}

export default function ThreatCoverage() {
  const report = useApi<CoverageReport>("/api/compliance");
  const [frameworkId, setFrameworkId] = useState("owasp-llm-2025");
  const [selected, setSelected] = useState<string | null>(null);
  const data = report.data;
  const framework = data?.frameworks.find((f) => f.id === frameworkId) ?? data?.frameworks[0];
  const threat = framework?.items.find((i) => i.id === selected) ?? framework?.items[0];
  const usedControls = data ? data.controls.filter((c) => framework?.items.some((i) => i.controls.includes(c.id))) : [];
  const run = data?.evidence_run;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Threat coverage"
        description="How AegisAI's controls map to the OWASP Top 10 for LLM Applications (2025) and MITRE ATLAS. Evidence is checked live against the latest red-team run, and residual risk is stated for every threat — including the ones AegisAI does not cover."
      />
      <ErrorNote message={report.error} />
      {framework && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatTile
              icon={ShieldCheck}
              tone="good"
              label="Mitigated"
              value={framework.summary.mitigated ?? 0}
              note={`of ${framework.items.length} threats`}
            />
            <StatTile
              icon={ShieldQuestion}
              tone="warning"
              label="Partially covered"
              value={framework.summary.partial ?? 0}
              note="residual risk stated"
            />
            <StatTile
              icon={CircleDashed}
              tone="critical"
              label="Not covered"
              value={framework.summary.gap ?? 0}
              note="named, not hidden"
            />
            <StatTile
              icon={CheckCircle2}
              tone="accent"
              label="Verified by red team"
              value={`${framework.items.filter((i) => i.verified).length} / ${framework.items.length}`}
              note={run ? `run of ${new Date(run.started_at).toLocaleString()}` : "no run yet — open the Red-team lab"}
            />
          </div>

          <Tabs
            tabs={(data?.frameworks ?? []).map((f) => ({ id: f.id, label: `${f.name} · ${f.version}` }))}
            value={framework.id}
            onChange={(id) => {
              setFrameworkId(id);
              setSelected(null);
            }}
          />

          <Card
            title="Coverage matrix"
            subtitle="Which control defends against which threat — select a row for evidence and residual risk"
            icon={Layers}
            actions={
              <a href={framework.url} target="_blank" rel="noreferrer" className="action-link text-xs">
                Framework reference <ExternalLink className="h-3 w-3" />
              </a>
            }
          >
            <div className="-mx-5 overflow-x-auto">
              <table className="w-full border-separate border-spacing-0 text-sm">
                <thead>
                  <tr className="text-left text-xs text-ink-2">
                    <th className="sticky left-0 z-10 border-b border-edge bg-surface px-5 py-2 font-semibold">
                      Threat
                    </th>
                    <th className="border-b border-edge px-3 py-2 font-semibold">Status</th>
                    {usedControls.map((c) => (
                      <th
                        key={c.id}
                        className="border-b border-edge px-1 py-2 text-center"
                        title={`${c.name}: ${c.description}`}
                      >
                        <span className="inline-block max-w-[4.5rem] text-[10px] leading-tight font-semibold">
                          {c.name}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {framework.items.map((t) => {
                    const active = t.id === threat?.id;
                    return (
                      <tr
                        key={t.id}
                        onClick={() => setSelected(t.id)}
                        className={`cursor-pointer ${active ? "bg-surface-2" : "hover:bg-surface-2/60"}`}
                      >
                        <td
                          className={`sticky left-0 z-10 border-b border-edge px-5 py-2.5 ${active ? "bg-surface-2" : "bg-surface"}`}
                        >
                          <div className="font-mono text-[11px] text-muted">{t.id}</div>
                          <div className="text-sm font-medium whitespace-nowrap">{t.name}</div>
                        </td>
                        <td className="border-b border-edge px-3 py-2.5">
                          <Badge tone={STATUS[t.status].tone}>{STATUS[t.status].label}</Badge>
                        </td>
                        {usedControls.map((c) => (
                          <td key={c.id} className="border-b border-edge px-1 py-2.5 text-center">
                            {t.controls.includes(c.id) ? (
                              <span
                                className="inline-block h-3 w-3 rounded-full"
                                style={{ background: t.status === "gap" ? "var(--muted)" : "var(--series-1)" }}
                                title={`${c.name} defends against ${t.name}`}
                              />
                            ) : (
                              <span className="inline-block h-1 w-1 rounded-full bg-grid" />
                            )}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {threat && data && (
            <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
              <Card icon={Target} title="Threat detail">
                <ThreatDetail threat={threat} controls={data.controls} />
              </Card>
              <Card icon={FileCode2} title="Controls in this framework" subtitle="Where each one lives in the code">
                <ul className="space-y-3">
                  {usedControls.map((c) => (
                    <li key={c.id}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">{c.name}</span>
                        {c.page && (
                          <button onClick={() => go(c.page)} className="action-link text-xs">
                            Open <ExternalLink className="h-3 w-3" />
                          </button>
                        )}
                      </div>
                      <div className="mt-0.5 font-mono text-[11px] break-all text-muted">{c.code.join(" · ")}</div>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
          )}
        </>
      )}
      {!data && !report.error && (
        <Card>
          <Empty icon={ShieldCheck}>Loading coverage…</Empty>
        </Card>
      )}
    </div>
  );
}
