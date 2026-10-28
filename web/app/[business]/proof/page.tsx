import { Suspense } from "react";
import { LearningCurve, LiftChart } from "@/components/proof-charts";
import { Badge, Card, Label, PageHead, Skeleton } from "@/components/ui";
import { api, type Learned, pct, pp, type TwinResults } from "@/lib/api";
import { stageLabel } from "@/lib/labels";

export default function ProofPage({ params }: PageProps<"/[business]/proof">) {
  return (
    <>
      <PageHead
        title="Proof"
        lead="Did Pheri's next steps work? Every result is against a holdout: customers Pheri deliberately left alone. Here it is measured in a customer twin."
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
  const [twin, learned] = await Promise.all([
    api<TwinResults>(`/businesses/${business}/twin`),
    api<Learned>(`/businesses/${business}/learned`),
  ]);
  const o = twin.overall;
  return (
    <div className="space-y-8">
      <p className="rounded-xl border border-amber/30 bg-amber-soft/60 px-5 py-3 text-ink-2">
        A customer twin of {twin.customers.toLocaleString()} synthetic customers. Their responses come from a hidden table
        (maths, no model); {Math.round(twin.holdout_share * 100)}% are held out and get nothing. Pheri sees each stage
        only through its own journey rules&rsquo; measured mistakes, and learns which action works over {twin.rounds}{" "}
        rounds (Thompson sampling).
      </p>

      <div className="grid grid-cols-3 gap-6">
        <Card>
          <Label>Lift against the holdout</Label>
          <p className="mt-2 font-serif text-[3rem] leading-none text-ink">{pp(o.lift_pp)}</p>
          <p className="mt-1 text-ink-2">percentage points</p>
          <p className="mt-3 text-[0.92rem] text-muted">
            95% interval {pp(o.ci_pp?.[0])} to {pp(o.ci_pp?.[1])} ·{" "}
            <span className={o.verdict === "works" ? "text-teal-ink" : ""}>
              {o.verdict === "works" ? "✓ works" : "? not clear yet"}
            </span>
          </p>
        </Card>
        <Card className="col-span-2">
          <Label>Who responded</Label>
          <div className="mt-3 grid grid-cols-3 gap-6">
            <Tile value={pct(o.treated.rate)} label="Pheri, learning" sub={`${o.treated.n.toLocaleString()} customers`} strong />
            <Tile
              value={pct(o.random_policy?.rate)}
              label="Same steps, picked at random"
              sub="same customers, same luck"
            />
            <Tile value={pct(o.holdout.rate)} label="Holdout, no action" sub={`${o.holdout.n.toLocaleString()} customers`} />
          </div>
        </Card>
      </div>

      <Card>
        <h2 className="mb-5 text-[1.6rem] font-medium">Lift by stage, and what Pheri learned works best</h2>
        <LiftChart stages={twin.stages} />
      </Card>

      <div className="grid grid-cols-[auto_1fr] items-start gap-6">
        <Card>
          <h2 className="text-[1.35rem] font-medium">Learning, round by round</h2>
          <p className="mt-1 mb-4 max-w-[30rem] text-[0.95rem] text-ink-2">
            Share of Pheri&rsquo;s picks that were the truly best allowed action. The twin knows the truth; a real business
            would see only the lift.
          </p>
          <LearningCurve curve={twin.learning_curve} />
          <p className="mt-1 text-center text-[0.82rem] text-muted">round</p>
        </Card>
        <Report learned={learned} />
      </div>
    </div>
  );
}

function Tile({ value, label, sub, strong }: { value: string; label: string; sub: string; strong?: boolean }) {
  return (
    <div>
      <p className={`font-serif text-[2.4rem] leading-none ${strong ? "text-teal-ink" : "text-ink"}`}>{value}</p>
      <p className="mt-2 font-medium text-ink">{label}</p>
      <p className="text-[0.88rem] text-muted">{sub}</p>
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
      <p className="mt-4 font-serif text-[1.15rem] leading-snug text-ink">{learned.headline}</p>
      <ul className="mt-4 space-y-2.5">
        {learned.findings.map((f) => (
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
