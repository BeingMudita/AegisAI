import { useState, type KeyboardEvent, type PointerEvent } from "react";

const H = 96; // viewBox height; the strip stretches to the container's width
const STEP = 3; // viewBox units per dimension: a 2-unit bar and a 1-unit gap

/** One embedding vector as a row of bars around a zero baseline (up = positive).
 *  The pointer snaps to the nearest dimension; arrow keys do the same. */
export function VectorStrip({ values }: { values: number[] }) {
  const [active, setActive] = useState<number | null>(null);
  const max = Math.max(1e-9, ...values.map(Math.abs));
  const mid = H / 2;
  const width = values.length * STEP;
  const scale = (mid - 4) / max;

  function fromPointer(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const i = Math.floor(((event.clientX - box.left) / box.width) * values.length);
    setActive(Math.max(0, Math.min(values.length - 1, i)));
  }

  function onKey(event: KeyboardEvent<SVGSVGElement>) {
    const moves: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, PageDown: 16, PageUp: -16 };
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      setActive(event.key === "Home" ? 0 : values.length - 1);
    } else if (event.key in moves) {
      event.preventDefault();
      setActive((i) => Math.max(0, Math.min(values.length - 1, (i ?? 0) + moves[event.key])));
    }
  }

  return (
    <figure className="min-w-0">
      <div className="mb-1.5 flex min-h-5 items-baseline justify-between gap-3 text-xs" aria-live="polite">
        {active === null ? (
          <span className="text-muted">Point at a bar, or focus the strip and use ← →.</span>
        ) : (
          <span>
            <strong className="tabular font-semibold text-ink">{values[active].toFixed(5)}</strong>
            <span className="ml-2 text-muted">dimension {active}</span>
          </span>
        )}
        <span className="tabular text-muted">±{max.toFixed(3)}</span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${H}`}
        preserveAspectRatio="none"
        className="block h-24 w-full cursor-crosshair rounded-md bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]"
        role="img"
        tabIndex={0}
        aria-label={`Embedding vector with ${values.length} dimensions, largest magnitude ${max.toFixed(3)}. Arrow keys read one dimension at a time.`}
        onPointerMove={fromPointer}
        onPointerLeave={() => setActive(null)}
        onFocus={() => setActive((i) => i ?? 0)}
        onBlur={() => setActive(null)}
        onKeyDown={onKey}
      >
        <line x1={0} x2={width} y1={mid} y2={mid} stroke="var(--axis)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        {values.map((v, i) => {
          const h = Math.max(0.5, Math.abs(v) * scale);
          return (
            <rect
              key={i}
              x={i * STEP}
              y={v >= 0 ? mid - h : mid}
              width={STEP - 1}
              height={h}
              fill={i === active ? "var(--ink)" : "var(--ink-2)"}
              opacity={active === null || i === active ? 1 : 0.55}
            />
          );
        })}
        {active !== null && (
          <line
            x1={active * STEP + (STEP - 1) / 2}
            x2={active * STEP + (STEP - 1) / 2}
            y1={0}
            y2={H}
            stroke="var(--ink)"
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
            opacity={0.5}
          />
        )}
      </svg>
      <figcaption className="mt-1 flex justify-between text-[11px] text-muted">
        <span>dim 0</span>
        <span>above the line: positive · below: negative</span>
        <span>dim {values.length - 1}</span>
      </figcaption>
    </figure>
  );
}
