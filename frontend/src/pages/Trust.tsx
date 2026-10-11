import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { api, qs } from "../api";
import { useAuth } from "../auth";
import { ChartCard, TrustLine } from "../components/charts";
import { Badge, Button, Card, Empty, ErrorNote, Meter, PageHeader, Pager, formatNumber, inputClass, trustTone } from "../components/ui";
import { formatTime, useApi } from "../hooks";
import type { SubjectType, TrustDetail, TrustLevel, TrustScore } from "../types";

const PAGE_SIZES = [15, 30, 50];
const PAGE_SIZE_KEY = "aegis.trust.pageSize";
const LEVELS: TrustLevel[] = ["UNTRUSTED", "LOW", "MEDIUM", "HIGH", "VERIFIED"];

interface TrustPage {
  scores: TrustScore[];
  threshold: number;
  total: number;
  levels?: Record<TrustLevel, number>;
}

function savedPageSize() {
  try {
    const n = Number(localStorage.getItem(PAGE_SIZE_KEY));
    return PAGE_SIZES.includes(n) ? n : PAGE_SIZES[0];
  } catch {
    return PAGE_SIZES[0];
  }
}

/** A subject's name for display: "FinanceAgent · for admin" (per-user agent trust), or a
 *  source's file name with its folder in grey ("FIN-000002088.txt  corpus/documents/invoice"). */
function SubjectName({ type, id }: { type: SubjectType; id: string }) {
  const at = type === "AGENT" ? id.indexOf("@") : -1;
  if (at >= 0) {
    return (
      <>
        {id.slice(0, at)} <span className="text-xs font-normal text-muted">· for {id.slice(at + 1)}</span>
      </>
    );
  }
  const slash = id.lastIndexOf("/");
  if (slash < 0) return <>{id}</>;
  return (
    <span className="flex min-w-0 items-baseline gap-2">
      <span className="truncate">{id.slice(slash + 1)}</span>
      <span className="hidden min-w-0 truncate text-xs font-normal text-muted sm:inline">{id.slice(0, slash)}</span>
    </span>
  );
}

const shortName = (id: string) => id.slice(id.lastIndexOf("/") + 1);

export default function Trust() {
  const { user } = useAuth();
  // One page of the registry at a time: a large archive has thousands of sources.
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(savedPageSize);
  const [query, setQuery] = useState("");
  const [type, setType] = useState<SubjectType | "">("");
  const [level, setLevel] = useState<TrustLevel | "">("");
  const list = useApi<TrustPage>(
    `/api/trust${qs({ subject_type: type, q: query.trim(), level, offset, limit: pageSize })}`,
    10000,
  );
  const [selected, setSelected] = useState<{ type: SubjectType; id: string } | null>(null);
  const detail = useApi<TrustDetail>(
    selected ? `/api/trust/${selected.type}/${encodeURIComponent(selected.id)}` : null,
    4000,
  );
  const [override, setOverride] = useState("0.80");
  const [rationale, setRationale] = useState("Reviewed by admin");
  const [error, setError] = useState<string | null>(null);
  const panel = useRef<HTMLDivElement>(null);

  const threshold = list.data?.threshold ?? 0.6;
  const scores = list.data?.scores ?? [];
  const total = list.data?.total ?? 0;
  const levels = list.data?.levels;
  const filtered = Boolean(query || type || level);

  function changePageSize(size: number) {
    setPageSize(size);
    setOffset(0);
    try {
      localStorage.setItem(PAGE_SIZE_KEY, String(size));
    } catch {
      /* the choice just isn't remembered */
    }
  }

  function select(s: TrustScore) {
    setSelected({ type: s.subject_type, id: s.subject_id });
    setError(null);
  }

  // Below the two-column width the history opens under the list: bring it into view.
  useEffect(() => {
    if (!selected || !panel.current) return;
    if (window.matchMedia("(min-width: 1280px)").matches) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    panel.current.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }, [selected]);

  async function applyOverride() {
    if (!selected) return;
    setError(null);
    try {
      await api.put(`/api/trust/${selected.type}/${encodeURIComponent(selected.id)}`, {
        score: Number(override),
        rationale,
      });
      void list.reload();
      void detail.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  // History is newest-first from the API; chart it oldest-first, starting from the prior score.
  const history = [...(detail.data?.history ?? [])].reverse();
  const points = history.length
    ? [
        { step: 0, score: history[0].previous, signal: "start", time: "" },
        ...history.map((h, i) => ({ step: i + 1, score: h.score, signal: h.signal, time: formatTime(h.created_at) })),
      ]
    : [];
  const shown = detail.data && selected && detail.data.subject_id === selected.id ? detail.data : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Trust"
        description="Every agent and data source has a trust score from 0 to 1. Attacks and policy violations lower it fast; clean behaviour raises it slowly. Tools need a minimum score — click a row to see its history."
      />
      <ErrorNote message={list.error} />
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <Card
          title="Trust registry"
          subtitle={`Lowest first · default threshold ${threshold.toFixed(2)} · ${formatNumber(total)} ${filtered ? "matching" : ""} subjects`}
          actions={<Pager compact offset={offset} pageSize={pageSize} total={total} noun="subjects" onChange={setOffset} />}
        >
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <label className="relative min-w-[200px] flex-1">
              <span className="sr-only">Search subjects</span>
              <input
                className={inputClass}
                placeholder="Search agents, sources and tools…"
                value={query}
                onChange={(e) => { setQuery(e.target.value); setOffset(0); }}
              />
            </label>
            <div className="shrink-0">
              <label className="sr-only" htmlFor="trust-type">Subject type</label>
              <select id="trust-type" className={`${inputClass} py-2 pr-8`} value={type} onChange={(e) => { setType(e.target.value as SubjectType | ""); setOffset(0); }}>
                <option value="">All subjects</option>
                <option value="AGENT">Agents</option>
                <option value="SOURCE">Sources</option>
                <option value="TOOL">Tools</option>
              </select>
            </div>
          </div>

          <div className="mb-3 flex flex-wrap items-center gap-1.5 text-xs" role="group" aria-label="Filter by trust level">
            {(["", ...LEVELS] as const).map((lv) => {
              const on = level === lv;
              const count = lv ? levels?.[lv] : levels && Object.values(levels).reduce((a, b) => a + b, 0);
              if (lv && levels && !count && !on) return null; // hide empty levels
              return (
                <button
                  key={lv || "all"}
                  aria-pressed={on}
                  onClick={() => { setLevel(lv); setOffset(0); }}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium transition ${on ? "border-ink-2 bg-surface-2 text-ink" : "border-edge text-ink-2 hover:text-ink"}`}
                >
                  {lv && <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: `var(--${trustTone(lv)})` }} />}
                  {lv ? lv.toLowerCase() : "All levels"}
                  {count !== undefined && <span className="tabular text-muted">{formatNumber(count)}</span>}
                </button>
              );
            })}
          </div>

          {scores.length ? (
            <div className="overflow-x-auto">
              <table className="w-full table-fixed text-sm">
                <thead>
                  <tr className="text-left text-xs text-ink-2">
                    <th className="border-b border-edge py-1.5 pr-3 font-semibold">Subject</th>
                    <th className="w-16 border-b border-edge py-1.5 pr-3 font-semibold">Type</th>
                    <th className="w-[30%] border-b border-edge py-1.5 pr-3 font-semibold">Score</th>
                    <th className="w-24 border-b border-edge py-1.5 pr-3 font-semibold">Level</th>
                    <th className="w-16 border-b border-edge py-1.5 text-right font-semibold">Changes</th>
                  </tr>
                </thead>
                <tbody>
                  {scores.map((s) => {
                    const active = selected?.id === s.subject_id && selected.type === s.subject_type;
                    return (
                      <tr
                        key={`${s.subject_type}:${s.subject_id}`}
                        tabIndex={0}
                        aria-selected={active}
                        title={s.subject_id}
                        onClick={() => select(s)}
                        onKeyDown={(e: KeyboardEvent) => {
                          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(s); }
                        }}
                        className={`cursor-pointer outline-none focus-visible:bg-surface-2 ${active ? "bg-surface-2" : "hover:bg-surface-2"}`}
                      >
                        <td className="border-b border-edge py-1.5 pr-3 font-medium">
                          <SubjectName type={s.subject_type} id={s.subject_id} />
                        </td>
                        <td className="border-b border-edge py-1.5 pr-3 text-xs text-ink-2">{s.subject_type.toLowerCase()}</td>
                        <td className="border-b border-edge py-1.5 pr-3">
                          <div className="flex items-center gap-2">
                            <span className="tabular w-9 shrink-0 text-xs">{s.score.toFixed(2)}</span>
                            <Meter
                              value={s.score}
                              tone={trustTone(s.level)}
                              markers={[{ at: threshold, label: "threshold" }]}
                              label={`${s.subject_id} trust`}
                            />
                          </div>
                        </td>
                        <td className="border-b border-edge py-1.5 pr-3">
                          <Badge tone={trustTone(s.level)}>{s.level.toLowerCase()}</Badge>
                        </td>
                        <td className="tabular border-b border-edge py-1.5 text-right text-xs">{s.assessments}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>
              {list.loading && !list.data
                ? "Loading…"
                : filtered
                  ? "Nothing matches this search."
                  : "No trust records yet — they appear as agents act and sources are ingested."}
            </Empty>
          )}
          <div className="flex flex-wrap items-end justify-between gap-x-4">
            <div className="min-w-0 flex-1">
              <Pager offset={offset} pageSize={pageSize} total={total} noun="subjects" onChange={setOffset} />
            </div>
            {total > PAGE_SIZES[0] && (
              <label className="flex items-center gap-2 pt-3 text-xs text-muted">
                Rows
                <select
                  className="rounded-md border border-edge bg-surface px-1.5 py-1 text-xs text-ink"
                  value={pageSize}
                  onChange={(e) => changePageSize(Number(e.target.value))}
                >
                  {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
            )}
          </div>
        </Card>

        <div ref={panel} className="min-w-0 scroll-mt-4 space-y-4 xl:sticky xl:top-4">
          {!selected ? (
            <Card title="History">
              <Empty>Select a subject to see how its score changed and why.</Empty>
            </Card>
          ) : detail.error && !shown ? (
            <Card title={shortName(selected.id)} subtitle={selected.id}>
              <ErrorNote message={detail.error} />
            </Card>
          ) : !shown ? (
            <Card title={shortName(selected.id)} subtitle={selected.id}>
              <Empty>Loading…</Empty>
            </Card>
          ) : (
            <>
              <Card
                title={<SubjectName type={shown.subject_type} id={shown.subject_id} />}
                subtitle={`${shown.subject_type.toLowerCase()} · ${shown.subject_id}`}
                actions={<Button variant="subtle" size="sm" onClick={() => setSelected(null)} aria-label="Close history">✕</Button>}
              >
                <div className="flex items-center gap-3">
                  <span className="tabular text-3xl font-semibold text-ink">{shown.score.toFixed(2)}</span>
                  <Badge tone={trustTone(shown.level)}>{shown.level.toLowerCase()}</Badge>
                  <span className="ml-auto text-xs text-muted">
                    {shown.assessments} change{shown.assessments === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="mt-3">
                  <Meter
                    value={shown.score}
                    tone={trustTone(shown.level)}
                    markers={[{ at: threshold, label: "threshold" }]}
                    label={`${shown.subject_id} trust`}
                  />
                </div>
              </Card>
              <ChartCard
                title="Trust history"
                subtitle="Each step is one assessment; penalties are fast, recovery is slow"
                table={{
                  columns: ["#", "Signal", "From", "To", "Why"],
                  rows: history.map((h, i) => [i + 1, h.signal, h.previous.toFixed(2), h.score.toFixed(2), h.rationale ?? ""]),
                }}
              >
                {points.length ? <TrustLine points={points} threshold={threshold} /> : <Empty>No changes yet.</Empty>}
              </ChartCard>
              {shown.history.length > 0 && (
                <Card title="Recent assessments">
                  <ul className="max-h-56 space-y-2 overflow-auto text-xs">
                    {shown.history.slice(0, 12).map((h, i) => (
                      <li key={i}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono">{h.signal}</span>
                          <span className="tabular text-ink-2">
                            {h.previous.toFixed(2)} → {h.score.toFixed(2)}
                          </span>
                        </div>
                        {h.rationale && <div className="text-muted">{h.rationale}</div>}
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
              {user?.role === "ADMIN" && (
                <Card title="Override" subtitle="Set a reviewed score (audited)">
                  <div className="space-y-2">
                    <input
                      className={inputClass}
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={override}
                      onChange={(e) => setOverride(e.target.value)}
                      aria-label="New trust score"
                    />
                    <input
                      className={inputClass}
                      value={rationale}
                      onChange={(e) => setRationale(e.target.value)}
                      aria-label="Rationale"
                    />
                    <ErrorNote message={error} />
                    <Button onClick={() => void applyOverride()}>Apply</Button>
                  </div>
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
