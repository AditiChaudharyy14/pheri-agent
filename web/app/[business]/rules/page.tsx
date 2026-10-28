import { Suspense } from "react";
import { RuleComposer } from "@/components/rule-composer";
import { Badge, Card, PageHead, Skeleton } from "@/components/ui";
import { api, BUSINESSES, type Business, type RuleRow } from "@/lib/api";

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
  const rules = await api<RuleRow[]>(`/businesses/${business}/rules`);
  const active = rules.filter((r) => r.active);
  const drafts = rules.filter((r) => !r.active);
  return (
    <div className="grid grid-cols-[1fr_460px] items-start gap-8">
      <Card>
        <RuleComposer business={business} />
      </Card>
      <div className="space-y-6">
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
  );
}
