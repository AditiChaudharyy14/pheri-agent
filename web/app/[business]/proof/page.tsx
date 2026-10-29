import { Suspense } from "react";
import { LiftChart } from "@/components/proof-charts";
import { Badge, Card, Label, PageHead, Skeleton } from "@/components/ui";
import { api, type Learned, pct, pp, type TwinResults, type VerificationTotals } from "@/lib/api";

const SHOWN_FINDINGS = 3;
import { stageLabel } from "@/lib/labels";

export default function ProofPage({ params }: PageProps<"/[business]/proof">) {
  return (
    <>
      <PageHead
        title="Proof"
        lead="Did Pheri's follow-ups work? Measured against a holdout: customers Pheri deliberately left alone."
        right={
          <span className="rounded-xl border-2 border-amber/50 bg-amber-soft px-4 py-2 text-[0.95rem] font-semibold tracking-[0.12em] text-amber">
            SIMULATED
          </span>
        }
      />
      <Suspense fallback={<Skeleton rows={3} />}>
        <Proof params={params} />
      </Suspense>
    </>
  );
}

async function Proof({ params }: { params: PageProps<"/[business]/proof">["params"] }) {
  const { business } = await params;
  const [twin, learned, checked] = await Promise.all([
    api<TwinResults>(`/businesses/${business}/twin`),
    api<Learned>(`/businesses/${business}/learned`),
    api<VerificationTotals>(`/businesses/${business}/verification`),
  ]);
  const o = twin.overall;
  const held = Math.round(twin.holdout_share * 100);
  return (
    <div className="space-y-8">
      <Card>
        <p className="font-serif text-[1.9rem] leading-snug text-ink">
          Customers Pheri followed up with responded {pct(o.treated.rate)} of the time. The {held}% held back, who got
          nothing, responded {pct(o.holdout.rate)}.{" "}
          <span className={o.verdict === "works" ? "text-teal-ink" : ""}>That is {pp(o.lift_pp)} points</span>.
        </p>
        <p className="mt-3 text-ink-2">
          95% interval {pp(o.ci_pp?.[0])} to {pp(o.ci_pp?.[1])} ({o.verdict === "works" ? "it works" : "not clear yet"}), on{" "}
          {twin.customers.toLocaleString()} simulated customers whose responses come from a hidden table (maths, no model).
          Pheri sees each one only through its own journey rules, mistakes included, and learns what works over{" "}
          {twin.rounds} rounds.
        </p>
        <p className="mt-4 border-t border-line pt-3 text-ink-2">
          <span className="font-medium text-ink">Nothing goes out unchecked.</span> For the {checked.decisions} next steps
          on the first page Pheri wrote {checked.drafts} drafts: code caught {checked.caught_by_code}, the judge caught{" "}
          {checked.caught_by_judge}, {checked.retries} were rewritten with the reasons, and {checked.sent_to_owner} went to
          the owner instead of the customer.
        </p>
      </Card>

      <Report learned={learned} />

      <Card>
        <details>
          <summary className="cursor-pointer text-[1.15rem] font-medium">How we know: the lift for each stage</summary>
          <div className="mt-5">
            <LiftChart stages={twin.stages} />
          </div>
        </details>
      </Card>
    </div>
  );
}

function Report({ learned }: { learned: Learned }) {
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-[1.35rem] font-medium">What Pheri learned</h2>
        <Badge tone={learned.rejected.length ? "amber" : "teal"}>
          {learned.findings.length} findings checked · {learned.rejected.length} rejected
        </Badge>
      </div>
      <p className="mt-1 text-[0.88rem] text-muted">
        {learned.source === "stand-in"
          ? "Written by the offline stand-in. The Muse Wonder report is a deliberate, budgeted run."
          : `Written by Muse Wonder${learned.source === "recorded" ? ", recorded from a live run" : ""}.`}{" "}
        Code checks every number against the results and every verdict against its interval.
      </p>
      {learned.attempts.length > 1 && (
        <p className="mt-3 text-[0.9rem] text-ink-2">
          {learned.attempts
            .map((a) => (a.passed ? `Attempt ${a.attempt} passed` : `Attempt ${a.attempt} rejected by code: ${a.rejected.join(", ")}`))
            .join(" → ")}
        </p>
      )}
      <p className="mt-4 font-serif text-[1.15rem] leading-snug text-ink">{learned.headline}</p>
      <ul className="mt-4 space-y-2.5">
        {learned.findings.slice(0, SHOWN_FINDINGS).map((f) => (
          <li key={f.stage} className="grid grid-cols-[8.5rem_1fr] gap-3 text-[0.95rem]">
            <span className="text-ink">
              {stageLabel(f.stage)}
              <span className={`block text-[0.8rem] ${f.verdict === "works" ? "text-teal-ink" : "text-muted"}`}>
                {f.verdict === "works" ? "✓ works" : f.verdict === "hurts" ? "✗ hurts" : "? not clear yet"}
              </span>
            </span>
            <span className="text-ink-2">{f.text}</span>
          </li>
        ))}
      </ul>
      {learned.caveats.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <Label>Keep in mind</Label>
          <ul className="mt-1.5 space-y-1 text-[0.92rem] text-ink-2">
            {learned.caveats.map((c) => (
              <li key={c.text}>{c.text}</li>
            ))}
          </ul>
        </div>
      )}
      {learned.rejected.length > 0 && (
        <div className="mt-4 rounded-lg bg-amber-soft px-3 py-2 text-[0.9rem] text-amber">
          Rejected by code: {learned.rejected.map((r) => `${r.part} (${r.problems.join("; ")})`).join(" · ")}
        </div>
      )}
    </Card>
  );
}
