import Link from "next/link";
import { Suspense } from "react";
import { ApproveReject } from "@/components/approve";
import { DecidedByLine } from "@/components/decided-by";
import { EvidenceChips } from "@/components/evidence";
import { Skeleton } from "@/components/ui";
import { api, pct, type Brief, type NextStepWithTime } from "@/lib/api";
import { actionLabel, clockNPT, dayNPT, LANGUAGE_NAME, stageLabel } from "@/lib/labels";

/** The owner's morning check, usually on a phone: what the night shift did, in sentences, then what needs them. */
export default function MorningPage({ params }: PageProps<"/[business]">) {
  return (
    <Suspense fallback={<Skeleton rows={3} />}>
      <Morning params={params} />
    </Suspense>
  );
}

async function Morning({ params }: { params: PageProps<"/[business]">["params"] }) {
  const { business } = await params;
  const b = await api<Brief>(`/businesses/${business}/brief`);
  const langs = Object.entries(b.read.by_language).sort((x, y) => y[1] - x[1]);
  const night = b.scheduled.length + b.need_you.length + b.blocked.length + b.stopped.length > 0;
  return (
    <div className="mx-auto max-w-[56rem] space-y-8">
      <header>
        <p className="text-[0.9rem] text-muted">
          {dayNPT(b.morning)} · {clockNPT(b.morning)}
          {night && <> · the night shift finished at {clockNPT(b.night)}</>}
        </p>
        <h1 className="mt-1 text-[2rem] leading-tight font-medium lg:text-[2.6rem]">Good morning.</h1>
      </header>

      {!night ? (
        <section className="rounded-2xl border border-line bg-surface p-6">
          <p className="font-serif text-[1.35rem] leading-snug">Nothing came in overnight, so Pheri had nothing to do.</p>
          <p className="mt-2 text-ink-2">
            You can still <Link href={`/${business}/rules`} className="text-teal-ink underline">set a rule</Link> for
            tonight.
          </p>
        </section>
      ) : (
        <section aria-label="The night, in short" className="font-serif text-[1.3rem] leading-relaxed text-ink lg:text-[1.55rem]">
          <p>
            While you slept, Pheri read <b className="font-semibold">{b.read.messages} messages</b>
            {langs.length > 0 && <> ({langs.map(([l, n]) => `${n} in ${LANGUAGE_NAME[l] ?? l}`).join(", ")})</>}
            {b.read.voice_notes.read > 0 && <> and {b.read.voice_notes.read} voice notes</>}, and looked at{" "}
            {b.customers} customers.
          </p>
          <p className="mt-3">
            <Count tone="teal" n={b.scheduled.length} one="reply" many="replies" /> passed every check and{" "}
            {b.scheduled.length === 1 ? "goes" : "go"} out at <b className="font-semibold">8:00</b>, when your quiet hours
            end. <Count tone="marigold" n={b.need_you.length} one="needs you" many="need you" />
            {b.blocked.length > 0 && (
              <>
                ; <Count tone="vermilion" n={b.blocked.length} one="was" many="were" /> blocked by your rules
              </>
            )}
            .
          </p>
          {b.stopped.length > 0 && (
            <p className="mt-3">
              <Count tone="vermilion" n={b.stopped.length} one="message" many="messages" /> tried to trick Pheri into
              discounts, refunds or other customers&rsquo; numbers. {b.stopped.length === 1 ? "It was" : "All were"}{" "}
              stopped; none became an action.
            </p>
          )}
        </section>
      )}

      {b.unreadable_voice.length > 0 && (
        <aside role="status" className="rounded-xl border-l-4 border-marigold bg-amber-soft px-4 py-3 text-[0.98rem] text-ink">
          <span className="font-medium">Listen yourself: </span>
          {b.unreadable_voice.map((v, i) => (
            <span key={v.customer}>
              {i > 0 && "; "}
              {v.name} sent a voice note in {LANGUAGE_NAME[v.lang] ?? v.lang}
            </span>
          ))}
          . Muse Voice can&rsquo;t read {b.unreadable_voice.map((v) => LANGUAGE_NAME[v.lang] ?? v.lang).join(" or ")} yet,
          so Pheri didn&rsquo;t guess.
        </aside>
      )}

      {b.public_demo && (
        <aside className="rounded-xl border border-line bg-sunk px-4 py-3 text-[0.92rem] text-ink-2">
          Public demo: you&rsquo;re seeing a night recorded from a live run. Live runs are off here; what you approve
          stays in your own copy.
        </aside>
      )}

      {b.need_you.length > 0 && (
        <section aria-labelledby="need-you">
          <h2 id="need-you" className="flex items-baseline gap-3 text-[1.45rem] font-medium">
            <Dot tone="marigold" />
            {b.need_you.length} {b.need_you.length === 1 ? "needs" : "need"} you
          </h2>
          <ul className="mt-3 space-y-4">
            {b.need_you.map((s) => (
              <li key={s.customer.key}>
                <NeedYou business={business} step={s} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {b.stopped.length > 0 && (
        <section aria-labelledby="stopped">
          <h2 id="stopped" className="flex items-baseline gap-3 text-[1.25rem] font-medium">
            <Dot tone="vermilion" />
            Stopped
          </h2>
          <ul className="mt-2 divide-y divide-line border-y border-line">
            {b.stopped.map((r) => (
              <li key={r.source_id} className="py-3">
                <p className="text-[0.92rem] text-muted">
                  {r.customer.name} · {LANGUAGE_NAME[r.language] ?? r.language}
                </p>
                <p lang={r.language} className="mt-1 font-serif text-[1.05rem] leading-snug text-ink">
                  &ldquo;{r.text}&rdquo;
                </p>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[0.9rem] text-ink-2">
            Pheri won&rsquo;t act on these or write back. <Link href={`/${business}/night`} className="text-teal-ink underline">
              Read how each was caught
            </Link>
            .
          </p>
        </section>
      )}

      {b.scheduled.length > 0 && (
        <section aria-labelledby="ready">
          <h2 id="ready" className="flex items-baseline gap-3 text-[1.25rem] font-medium">
            <Dot tone="teal" />
            Ready at 8:00
          </h2>
          <ul className="mt-2 divide-y divide-line border-y border-line">
            {b.scheduled.map((s) => (
              <li key={s.customer.key}>
                <Ready business={business} step={s} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {b.proof && (
        <p className="border-t border-line pt-5 text-[1.02rem] text-ink-2">
          Does it work? In a simulation of {b.proof.customers.toLocaleString()} customers, those Pheri followed up with{" "}
          {b.proof.outcome} {pct(b.proof.treated)} of the time, against {pct(b.proof.holdout)} for those it left
          alone. <Link href={`/${business}/proof`} className="text-teal-ink underline">How we know</Link> ·{" "}
          <Link href={`/${business}/slop`} className="text-teal-ink underline">What a plain AI would have sent</Link>
        </p>
      )}
    </div>
  );
}

const TONE = {
  teal: { text: "text-teal-ink", dot: "bg-teal" },
  marigold: { text: "text-amber", dot: "bg-marigold" },
  vermilion: { text: "text-rose", dot: "bg-vermilion" },
} as const;

function Count({ tone, n, one, many }: { tone: keyof typeof TONE; n: number; one: string; many: string }) {
  return (
    <b className={`font-semibold ${TONE[tone].text}`}>
      {n} {n === 1 ? one : many}
    </b>
  );
}

function Dot({ tone }: { tone: keyof typeof TONE }) {
  return <span aria-hidden className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${TONE[tone].dot}`} />;
}

function Who({ business, step }: { business: string; step: NextStepWithTime }) {
  const c = step.customer;
  return (
    <p className="flex flex-wrap items-baseline gap-x-2">
      <Link href={`/${business}/customers/${encodeURIComponent(c.key)}`} className="font-serif text-[1.2rem] font-medium text-ink hover:text-teal-ink">
        {c.name}
      </Link>
      <span className="text-[0.9rem] text-muted">
        {[c.town ?? c.company, stageLabel(c.stage)].filter(Boolean).join(" · ")}
      </span>
    </p>
  );
}

function NeedYou({ business, step }: { business: string; step: NextStepWithTime }) {
  const d = step.decision;
  const v = step.verification;
  const why = v && !v.passed && !step.override
    ? `Pheri wrote it ${v.attempts} times and it still failed a check: ${v.reasons[0] ?? "see the trace"}`
    : d.action === "offer_discount" ? "Money off is yours to decide." : d.action === "task_for_owner" ? "Only you can do this." : null;
  return (
    <article className="rounded-2xl border border-line border-l-4 border-l-marigold bg-surface p-4 lg:p-6">
      <Who business={business} step={step} />
      <p className="mt-2 font-medium text-amber">
        {actionLabel(d.action)}
        {d.discount_pct ? ` · ${d.discount_pct}% off` : ""}
      </p>
      {why && <p className="mt-1 text-[0.95rem] text-ink-2">{why}</p>}
      {d.message && (
        <blockquote className="mt-3 border-l-2 border-line-2 pl-3 leading-relaxed text-ink">{d.message}</blockquote>
      )}
      <div className="mt-3">
        <EvidenceChips evidence={step.evidence} />
      </div>
      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="text-[0.85rem]">
          <DecidedByLine business={business} customerKey={step.customer.key} by={step.decided_by} cost={step.cost_usd}
                         turns={step.turns} isPrivate={step.private} verification={step.verification} override={step.override} />
        </div>
        {step.approval?.decision === "pending" && (
          <div className="sm:w-48">
            <ApproveReject business={business} approvalId={step.approval.id} check={step.action?.payload.verification} />
          </div>
        )}
      </div>
    </article>
  );
}

function Ready({ business, step }: { business: string; step: NextStepWithTime }) {
  const d = step.decision;
  return (
    <details className="group py-3">
      <summary className="flex cursor-pointer list-none items-baseline justify-between gap-3">
        <span className="min-w-0">
          <span className="font-medium text-ink">{step.customer.name}</span>{" "}
          <span className="text-[0.92rem] text-ink-2">· {actionLabel(d.action)}</span>
        </span>
        <span className="shrink-0 text-[0.85rem] text-teal-ink">{step.sends_at_local ?? "8:00"} their time</span>
      </summary>
      <div className="mt-2 space-y-3 pl-0">
        <p className="leading-relaxed text-ink">{d.message}</p>
        <p className="text-[0.92rem] text-ink-2">
          <span className="text-muted">Why: </span>
          {d.why_this}
        </p>
        <EvidenceChips evidence={step.evidence} />
        <div className="text-[0.85rem]">
          <DecidedByLine business={business} customerKey={step.customer.key} by={step.decided_by} cost={step.cost_usd}
                         turns={step.turns} isPrivate={step.private} verification={step.verification} override={step.override} />
        </div>
      </div>
    </details>
  );
}
