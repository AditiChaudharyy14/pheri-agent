import Link from "next/link";
import { Suspense } from "react";
import { DecidedByLine } from "@/components/decided-by";
import { EvidenceChips } from "@/components/evidence";
import { PageHead, Skeleton } from "@/components/ui";
import { api, type Slop } from "@/lib/api";
import { actionLabel, stageLabel } from "@/lib/labels";

/** The same customer, two drafts: what a plain AI writes from their messages, and what Pheri writes. The plain one
 * is a real model reply, run through exactly the checks Pheri's own drafts go through. */
export default function SlopPage({ params }: PageProps<"/[business]/slop">) {
  return (
    <>
      <PageHead
        title="What a plain AI would have sent"
        lead="Same customer, same messages. A plain AI writes a friendly follow-up; Pheri's checks read it like any of Pheri's own drafts. Struck through: what Pheri would never send, and why."
      />
      <Suspense fallback={<Skeleton rows={3} />}>
        <Pairs params={params} />
      </Suspense>
    </>
  );
}

async function Pairs({ params }: { params: PageProps<"/[business]/slop">["params"] }) {
  const { business } = await params;
  const rows = await api<Slop[]>(`/businesses/${business}/slop`);
  if (!rows.length) return <p className="text-ink-2">No customers to compare yet.</p>;
  return (
    <ol className="space-y-10">
      {rows.map((r) => (
        <li key={r.customer.key} aria-label={r.customer.name}>
          <h2 className="flex flex-wrap items-baseline gap-x-3 text-[1.45rem] font-medium">
            <Link href={`/${business}/customers/${encodeURIComponent(r.customer.key)}`} className="hover:text-teal-ink">
              {r.customer.name}
            </Link>
            <span className="text-[0.95rem] font-normal text-muted">{stageLabel(r.customer.stage)}</span>
          </h2>
          <div className="mt-3 grid gap-4 lg:grid-cols-2 lg:gap-6">
            <Plain r={r} />
            <PheriSide business={business} r={r} />
          </div>
        </li>
      ))}
    </ol>
  );
}

function Plain({ r }: { r: Slop }) {
  const p = r.plain;
  return (
    <section className="rounded-2xl border border-line border-l-4 border-l-vermilion bg-surface p-4 lg:p-6">
      <h3 className="text-[0.8rem] font-medium tracking-[0.08em] text-muted uppercase">A plain AI draft</h3>
      <div className="mt-3 space-y-2 leading-relaxed">
        {p.sentences.map((s, i) =>
          s.struck ? (
            <p key={i}>
              <del className="text-ink-2 decoration-vermilion decoration-2">{s.text}</del>
              {s.reasons.map((why) => (
                <span key={why} className="mt-0.5 block text-[0.88rem] text-rose">
                  {why}
                </span>
              ))}
            </p>
          ) : (
            <p key={i} className="text-ink">{s.text}</p>
          ),
        )}
      </div>
      {p.whole_draft.length > 0 && (
        <ul className="mt-4 space-y-1 border-t border-line pt-3 text-[0.9rem] text-rose">
          {p.whole_draft.map((why) => (
            <li key={why}>✗ {why}</li>
          ))}
        </ul>
      )}
      {(p.structural ?? []).length > 0 && (
        <p className="mt-3 text-[0.85rem] text-ink-2">
          <span className="text-rose">Also failed:</span> {(p.structural ?? []).map((x) => x.replace(/\.$/, "")).join(" · ")}.
        </p>
      )}
      <p className="mt-3 text-[0.8rem] text-muted">
        {p.failed.length} problems found{p.judged ? `, ${p.judged} of them by the judge (shown here, never used to send)` : ""} · Muse Spark 1.3, {p.recorded ? "recorded from a live run" : "offline stand-in"}
        {p.failed.some((f) => f.hard) ? " · could never be sent" : ""}
      </p>
    </section>
  );
}

function PheriSide({ business, r }: { business: string; r: Slop }) {
  const s = r.pheri;
  const d = s.decision;
  const status = s.action?.status;
  return (
    <section className="rounded-2xl border border-line border-l-4 border-l-teal bg-surface p-4 lg:p-6">
      <h3 className="text-[0.8rem] font-medium tracking-[0.08em] text-muted uppercase">Pheri</h3>
      <p className="mt-3 font-medium text-teal-ink">{actionLabel(d.action)}</p>
      {d.message ? <p className="mt-2 leading-relaxed text-ink">{d.message}</p> : <p className="mt-2 text-ink-2">Nothing to send.</p>}
      <p className="mt-3 text-[0.92rem] text-ink-2">
        <span className="text-muted">Why: </span>
        {d.why_this}
      </p>
      <div className="mt-3">
        <EvidenceChips evidence={s.evidence} />
      </div>
      <div className="mt-3 text-[0.85rem]">
        {status === "scheduled" && <p className="mb-1 text-teal-ink">Goes out at {s.sends_at_local ?? "8:00"}, their time.</p>}
        {status === "awaiting_approval" && <p className="mb-1 text-amber">Waiting for you.</p>}
        <DecidedByLine business={business} customerKey={s.customer.key} by={s.decided_by} cost={s.cost_usd} turns={s.turns}
                       isPrivate={s.private} verification={s.verification} override={s.override} />
      </div>
    </section>
  );
}
