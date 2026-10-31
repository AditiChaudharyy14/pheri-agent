import { Suspense } from "react";
import { RuleComposer } from "@/components/rule-composer";
import { Badge, Card, PageHead, Skeleton } from "@/components/ui";
import { api, BUSINESSES, type Business, type MiddleStep, type RuleRow } from "@/lib/api";
import { actionLabel, stageLabel } from "@/lib/labels";

export default function RulesPage({ params }: PageProps<"/[business]/rules">) {
  return (
    <>
      <PageHead
        title="Your rules"
        lead="Write a rule in plain words. Muse Spark turns it into checks, code describes exactly what it will block, and you confirm. From then on code checks every action against it, before anything happens."
      />
      <Suspense fallback={<Skeleton rows={2} />}>
        <Rules params={params} />
      </Suspense>
    </>
  );
}

async function Rules({ params }: { params: PageProps<"/[business]/rules">["params"] }) {
  const { business } = await params;
  const [rules, middle] = await Promise.all([
    api<RuleRow[]>(`/businesses/${business}/rules`),
    api<MiddleStep>(`/businesses/${business}/middle-step`),
  ]);
  const active = rules.filter((r) => r.active);
  const drafts = rules.filter((r) => !r.active);
  return (
    <div className="space-y-8">
      <div className="grid items-start gap-6 lg:grid-cols-[1fr_460px] lg:gap-8">
        <Card className="min-w-0">
          <RuleComposer business={business} />
        </Card>
        <div className="min-w-0 space-y-6">
          <Card>
            <h2 className="text-[1.45rem] font-medium">
              In force at {BUSINESSES[business as Business]} <span className="text-muted">({active.length})</span>
            </h2>
            {active.length === 0 && <p className="mt-3 text-ink-2">No rules yet.</p>}
            <ul className="mt-4 space-y-4">
              {active.map((r) => (
                <li key={r.id} className="border-t border-line pt-4">
                  <p className="font-serif text-[1.15rem] text-ink">&ldquo;{r.source_text}&rdquo;</p>
                  <ul className="mt-2 space-y-1">
                    {r.described.map((d) => (
                      <li key={d} className="text-[0.95rem] text-ink-2">
                        <span className="mr-2 text-teal">●</span>
                        {d}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-[0.82rem] text-muted">Confirmed by {r.confirmed_by}</p>
                </li>
              ))}
            </ul>
          </Card>
          {drafts.length > 0 && (
            <Card>
              <h2 className="text-[1.2rem] font-medium">
                Drafts <Badge>not enforced</Badge>
              </h2>
              <ul className="mt-3 space-y-2">
                {drafts.map((r) => (
                  <li key={r.id} className="text-[0.95rem] text-ink-2">
                    &ldquo;{r.source_text}&rdquo;
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
      <MiddleStepCard m={middle} />
    </div>
  );
}

const pctOf = (x: number) => `${Math.round(x * 100)}%`;

function MiddleStepCard({ m }: { m: MiddleStep }) {
  return (
    <Card>
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-[1.45rem] font-medium">Before Pheri writes a message: is the stage right, does the plan fit?</h2>
        <div className="flex gap-2">
          <Badge tone="amber">Money actions need {pctOf(m.thresholds.money)}</Badge>
          <Badge tone="teal">Nudges need {pctOf(m.thresholds.nudge)}</Badge>
        </div>
      </div>
      <p className="mt-2 max-w-4xl text-[0.95rem] text-ink-2">
        Code scores its own journey stage and each plan against a labelled truth set: of the customers it puts in a stage,
        how many truly are there, and how many the plan truly fits. A plan below the bar is refused in the loop, before the
        message is written; the model hears why and picks another. Money actions (discount, upgrade, subscription) need
        every case right.
      </p>
      <ul className="mt-5 divide-y divide-line">
        {m.stages.map((st) => (
          <li key={st.stage} className="grid gap-2 py-3 sm:grid-cols-[14rem_1fr] sm:gap-4">
            <div>
              <span className="font-medium text-ink">{stageLabel(st.stage)}</span>
              <span className="block text-[0.85rem] text-muted">
                stage right for {pctOf(st.stage_score)} of {st.customers}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {st.plans
                .filter((x) => x.plan_score > 0)
                .sort((a, b) => b.plan_score - a.plan_score)
                .map((x) => (
                  <Badge key={x.action} tone={x.passed ? "teal" : "slate"} title={`${x.class}: needs ${pctOf(x.threshold)}`}>
                    {x.passed ? "✓" : "✗"} {actionLabel(x.action)} {pctOf(x.plan_score)}
                  </Badge>
                ))}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
