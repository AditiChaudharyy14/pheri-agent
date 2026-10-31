import type { ReactNode } from "react";
import { MODE_LABEL, words } from "@/lib/api";
import { stageLabel } from "@/lib/labels";

export function PageHead({ title, lead, right }: { title: string; lead?: ReactNode; right?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4 lg:mb-8 lg:gap-8">
      <div className="max-w-3xl">
        <h1 className="text-[2rem] leading-tight font-medium text-ink lg:text-[2.6rem]">{title}</h1>
        {lead && <p className="mt-2 text-[1.1rem] leading-relaxed text-ink-2">{lead}</p>}
      </div>
      {right}
    </header>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-line bg-surface p-5 lg:p-7 ${className}`}>{children}</section>;
}

type Tone = "teal" | "amber" | "rose" | "slate" | "ink";
const TONES: Record<Tone, string> = {
  teal: "bg-teal-soft text-teal-ink",
  amber: "bg-amber-soft text-amber",
  rose: "bg-rose-soft text-rose",
  slate: "bg-slate-soft text-ink-2",
  ink: "bg-ink text-paper",
};

export function Badge({ children, tone = "slate", title }: { children: ReactNode; tone?: Tone; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center rounded-full px-3 py-1 text-[0.82rem] font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function ModeBadge({ mode }: { mode: string | null | undefined }) {
  if (!mode) return null;
  const tone: Tone = mode === "act_alone" ? "teal" : mode === "ask_owner" ? "amber" : "slate";
  return <Badge tone={tone}>{MODE_LABEL[mode] ?? words(mode)}</Badge>;
}

export function StageBadge({ stage }: { stage: string }) {
  return <Badge tone="slate">{stageLabel(stage)}</Badge>;
}

export function Chip({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span title={title} className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-line bg-paper px-2.5 py-1 text-[0.85rem] text-ink-2">
      {children}
    </span>
  );
}

export function Label({ children }: { children: ReactNode }) {
  return <div className="text-[0.78rem] font-medium tracking-[0.08em] text-muted uppercase">{children}</div>;
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-5" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-40 animate-pulse rounded-2xl border border-line bg-surface" />
      ))}
    </div>
  );
}
