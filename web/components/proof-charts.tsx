import type { StageResult } from "@/lib/api";
import { pct, pp } from "@/lib/api";
import { actionLabel, stageLabel } from "@/lib/labels";

// SVG paint goes in attributes (not utility classes) so marks always get their colour.
const C = {
  chart: "var(--color-chart)",
  grid: "var(--color-grid)",
  zero: "var(--color-line-2)",
  surface: "var(--color-surface)",
  muted: "var(--color-muted)",
  ink: "var(--color-ink)",
};

const TRACK = 360; // px, the plot width of one lift row
const ROW_H = 46;
const COLS = "grid-cols-[9rem_360px_10rem_6.5rem_1fr]";

function niceDomain(lo: number, hi: number): [number, number] {
  const step = 5;
  return [Math.floor(Math.min(lo, 0) / step) * step, Math.ceil(Math.max(hi, 0) / step) * step];
}

/** Lift vs holdout per stage: a dot at the lift, a whisker for its 95% interval, a shared zero line. */
export function LiftChart({ stages }: { stages: StageResult[] }) {
  const rows = stages.filter((s) => s.lift_pp != null && s.ci_pp);
  const [lo, hi] = niceDomain(Math.min(...rows.map((s) => s.ci_pp![0])), Math.max(...rows.map((s) => s.ci_pp![1])));
  const x = (v: number) => ((v - lo) / (hi - lo)) * TRACK;
  const ticks: number[] = [];
  for (let t = lo; t <= hi; t += hi - lo > 40 ? 10 : 5) ticks.push(t);
  return (
    <div role="figure" aria-label="Lift against the holdout per stage, with 95% intervals">
      <div className={`grid ${COLS} items-end gap-x-6 pb-1 text-[0.82rem] text-muted`}>
        <span>Stage</span>
        <svg width={TRACK} height={18} className="overflow-visible" aria-hidden>
          {ticks.map((t) => (
            <text key={t} x={x(t)} y={13} textAnchor="middle" fill={C.muted} fontSize={12}>
              {t > 0 ? `+${t}` : t}
            </text>
          ))}
        </svg>
        <span>Lift, points [95% interval]</span>
        <span>Verdict</span>
        <span className="text-right">Best action learned</span>
      </div>
      {rows.map((s) => {
        const [a, b] = s.ci_pp!;
        const works = s.verdict === "works";
        return (
          <div key={s.stage} className={`grid ${COLS} items-center gap-x-6 border-t border-line`}>
            <span className="text-ink">{stageLabel(s.stage)}</span>
            <svg width={TRACK} height={ROW_H} className="overflow-visible">
              <title>
                {`${stageLabel(s.stage)}: ${pp(s.lift_pp)} points (95% interval ${pp(a)} to ${pp(b)}); contacted ${pct(
                  s.treated.rate,
                )} of ${s.treated.n.toLocaleString()}, holdout ${pct(s.holdout.rate)} of ${s.holdout.n.toLocaleString()}`}
              </title>
              <rect x={0} y={0} width={TRACK} height={ROW_H} fill="transparent" />
              {ticks.map((t) => (
                <line key={t} x1={x(t)} x2={x(t)} y1={0} y2={ROW_H} stroke={C.grid} strokeWidth={1} />
              ))}
              <line x1={x(0)} x2={x(0)} y1={0} y2={ROW_H} stroke={C.zero} strokeWidth={1.5} />
              <line
                x1={x(a)} x2={x(b)} y1={ROW_H / 2} y2={ROW_H / 2}
                stroke={C.chart} strokeOpacity={0.5} strokeWidth={2} strokeLinecap="round"
              />
              {[a, b].map((v) => (
                <line key={v} x1={x(v)} x2={x(v)} y1={ROW_H / 2 - 6} y2={ROW_H / 2 + 6} stroke={C.chart} strokeOpacity={0.5} strokeWidth={2} strokeLinecap="round" />
              ))}
              <circle
                cx={x(s.lift_pp!)} cy={ROW_H / 2} r={6}
                fill={works ? C.chart : C.surface} stroke={works ? C.surface : C.chart} strokeWidth={2}
              />
            </svg>
            <span className="whitespace-nowrap tabular-nums">
              <span className="font-medium text-ink">{pp(s.lift_pp)}</span>{" "}
              <span className="text-[0.9rem] text-muted">[{pp(a)}, {pp(b)}]</span>
            </span>
            <span className={`whitespace-nowrap ${works ? "text-teal-ink" : "text-muted"}`}>
              {works ? "✓ works" : "? not clear yet"}
            </span>
            <span className="py-2 text-right text-ink-2">
              {actionLabel(s.best_action)}
              {s.best_call === "close call" && (
                <span className="block text-[0.8rem] text-amber">close call with {actionLabel(s.runner_up)}</span>
              )}
            </span>
          </div>
        );
      })}
      <p className="mt-3 border-t border-line pt-3 text-[0.85rem] text-muted">
        Dot: lift against the holdout. Line: its 95% interval. Filled when the whole interval is above zero (works); open
        when it includes zero (not clear yet). Hover a row for the counts.
      </p>
    </div>
  );
}
