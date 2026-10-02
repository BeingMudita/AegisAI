import { useState } from "react";

import { api } from "../api";
import { useAuth } from "../auth";
import { ChartCard, TrustLine } from "../components/charts";
import { Badge, Button, Card, Empty, ErrorNote, Meter, PageHeader, inputClass, trustTone } from "../components/ui";
import { formatTime, useApi } from "../hooks";
import type { SubjectType, TrustDetail, TrustScore } from "../types";

export default function Trust() {
  const { user } = useAuth();
  const list = useApi<{ scores: TrustScore[]; threshold: number }>("/api/trust", 4000);
  const [selected, setSelected] = useState<{ type: SubjectType; id: string } | null>(null);
  const detail = useApi<TrustDetail>(
    selected ? `/api/trust/${selected.type}/${encodeURIComponent(selected.id)}` : null,
    4000,
  );
  const [override, setOverride] = useState("0.80");
  const [rationale, setRationale] = useState("Reviewed by admin");
  const [error, setError] = useState<string | null>(null);

  const threshold = list.data?.threshold ?? 0.6;
  const scores = list.data?.scores ?? [];

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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Trust"
        description="Every agent and data source has a trust score from 0 to 1. Attacks and policy violations lower it fast; clean behaviour raises it slowly. Tools need a minimum score — click a row to see its history."
      />
      <ErrorNote message={list.error} />
      <Card
        title="Trust registry"
        subtitle={`Lowest first · default threshold ${threshold.toFixed(2)} · select a row for its history`}
      >
        {scores.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-2">
                  <th className="border-b border-edge py-1.5 pr-3 font-semibold">Subject</th>
                  <th className="border-b border-edge py-1.5 pr-3 font-semibold">Type</th>
                  <th className="w-1/3 border-b border-edge py-1.5 pr-3 font-semibold">Score</th>
                  <th className="border-b border-edge py-1.5 pr-3 font-semibold">Level</th>
                  <th className="border-b border-edge py-1.5 font-semibold">Changes</th>
                </tr>
              </thead>
              <tbody>
                {scores.map((s) => {
                  const active = selected?.id === s.subject_id && selected.type === s.subject_type;
                  return (
                    <tr
                      key={`${s.subject_type}:${s.subject_id}`}
                      onClick={() => setSelected({ type: s.subject_type, id: s.subject_id })}
                      className={`cursor-pointer ${active ? "bg-surface-2" : "hover:bg-surface-2"}`}
                    >
                      <td className="border-b border-edge py-1.5 pr-3 font-medium">{s.subject_id}</td>
                      <td className="border-b border-edge py-1.5 pr-3 text-xs text-ink-2">
                        {s.subject_type.toLowerCase()}
                      </td>
                      <td className="border-b border-edge py-1.5 pr-3">
                        <div className="flex items-center gap-2">
                          <span className="tabular w-9 text-xs">{s.score.toFixed(2)}</span>
                          <Meter
                            value={s.score}
                            markers={[{ at: threshold, label: "threshold" }]}
                            label={`${s.subject_id} trust`}
                          />
                        </div>
                      </td>
                      <td className="border-b border-edge py-1.5 pr-3">
                        <Badge tone={trustTone(s.level)}>{s.level.toLowerCase()}</Badge>
                      </td>
                      <td className="tabular border-b border-edge py-1.5 text-xs">{s.assessments}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No trust records yet — they appear as agents act and sources are ingested.</Empty>
        )}
      </Card>

      {selected && detail.data && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <ChartCard
            title={`${detail.data.subject_id} — trust history`}
            subtitle="Each step is one assessment; penalties are fast, recovery is slow"
            table={{
              columns: ["#", "Signal", "From", "To", "Why"],
              rows: history.map((h, i) => [
                i + 1,
                h.signal,
                h.previous.toFixed(2),
                h.score.toFixed(2),
                h.rationale ?? "",
              ]),
            }}
          >
            {points.length ? <TrustLine points={points} threshold={threshold} /> : <Empty>No changes yet.</Empty>}
          </ChartCard>
          <div className="space-y-4">
            <Card title="Recent assessments">
              <ul className="max-h-56 space-y-2 overflow-auto text-xs">
                {detail.data.history.slice(0, 12).map((h, i) => (
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
          </div>
        </div>
      )}
    </div>
  );
}
