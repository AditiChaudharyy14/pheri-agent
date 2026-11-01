import { pct } from "@/lib/api";

// SVG paint goes in attributes (not utility classes) so marks always get their colour. One series colour (teal, for
// customers Pheri followed up with) and the grey line colour (customers it deliberately didn't message).
const C = {
  chart: "var(--color-chart)",
  other: "var(--color-line-2)",
  grid: "var(--color-grid)",
  zero: "var(--color-muted)",
  surface: "var(--color-surface)",
  muted: "var(--color-muted)",
  ink: "var(--color-ink)",
};

/** One stage's extra outcomes per 100 customers: a dot at the estimate, a line across the likely range, on a scale
 * shared by every stage (so the rows compare), with zero marked. Fills its container: phone or desktop. */
export function RangeBar({ lift, ci, domain, label }: { lift: number; ci: [number, number]; domain: [number, number]; label: string }) {
  const [lo, hi] = domain;
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100;
  return (
    <svg viewBox="0 0 100 14" preserveAspectRatio="none" className="block h-4 w-full" role="img" aria-label={label}>
      <line x1={x(0)} x2={x(0)} y1={0} y2={14} stroke={C.zero} strokeWidth={0.4} vectorEffect="non-scaling-stroke" />
      <line x1={x(ci[0])} x2={x(ci[1])} y1={7} y2={7} stroke={C.chart} strokeOpacity={0.45} strokeWidth={4}
        strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      <line x1={x(lift)} x2={x(lift)} y1={1} y2={13} stroke={C.chart} strokeWidth={3} strokeLinecap="round"
        vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function sharedDomain(ranges: [number, number][]): [number, number] {
  const step = 5;
  const lo = Math.min(0, ...ranges.map((r) => r[0]));
  const hi = Math.max(0, ...ranges.map((r) => r[1]));
  return [Math.floor(lo / step) * step, Math.ceil(hi / step) * step];
}

type Row = { label: string; day: number; treated: number; held: number };

/** Delayed outcomes: for each milestone (a reply on day 1, an order on day 3, a reorder by day 30), how many of
 * every 100 customers got there, followed up vs not messaged. Paired horizontal bars, values written at the end. */
export function MilestoneChart({ rows }: { rows: Row[] }) {
  const max = Math.max(...rows.flatMap((r) => [r.treated, r.held]));
  const w = (v: number) => `calc((100% - 3.75rem) * ${(v / max).toFixed(4)})`; // room for the value after the bar
  return (
    <figure className="mt-4">
      <figcaption className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-[0.85rem] text-ink-2">
        <span className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: C.chart }} aria-hidden /> Followed up by Pheri
        </span>
        <span className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: C.other }} aria-hidden /> Deliberately not messaged
        </span>
      </figcaption>
      <ul className="space-y-3.5">
        {rows.map((r) => (
          <li key={r.label} className="grid grid-cols-[6.5rem_1fr] items-center gap-x-3 sm:grid-cols-[9rem_1fr]">
            <span className="text-[0.92rem] leading-tight text-ink">
              {r.label}
              <span className="block text-[0.8rem] text-muted">day {r.day}</span>
            </span>
            <span className="space-y-1" role="img"
              aria-label={`${r.label}: ${pct(r.treated)} followed up, ${pct(r.held)} not messaged`}>
              {[
                { v: r.treated, fill: C.chart, strong: true },
                { v: r.held, fill: C.other, strong: false },
              ].map((b, i) => (
                <span key={i} className="flex items-center gap-2">
                  <span className="block h-3 rounded-r-sm" style={{ width: w(b.v), background: b.fill, minWidth: 2 }} />
                  <span className={`shrink-0 text-[0.82rem] tabular-nums ${b.strong ? "font-medium text-ink" : "text-muted"}`}>
                    {pct(b.v)}
                  </span>
                </span>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
