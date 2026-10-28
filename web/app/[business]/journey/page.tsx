import Link from "next/link";
import { Suspense } from "react";
import { Card, PageHead, Skeleton } from "@/components/ui";
import { api, BUSINESSES, type Business, type CustomerRow } from "@/lib/api";
import { factLabel, factValue, HERO, STAGE_ORDER, STAGE_RULE, stageLabel } from "@/lib/labels";

const SHOWN = 5;

export default function JourneyPage({ params }: PageProps<"/[business]/journey">) {
  return (
    <>
      <PageHead
        title="Journey map"
        lead="Where every customer is, decided in code from facts counted in their data. No model chooses a stage; each one comes with the facts that put the customer there."
      />
      <Suspense fallback={<Skeleton rows={2} />}>
        <Stages params={params} />
      </Suspense>
    </>
  );
}

async function Stages({ params }: { params: PageProps<"/[business]/journey">["params"] }) {
  const { business } = await params;
  const { items, total } = await api<{ items: CustomerRow[]; total: number }>(
    `/businesses/${business}/customers?limit=500`,
  );
  const by = new Map<string, CustomerRow[]>();
  for (const c of items) by.set(c.stage, [...(by.get(c.stage) ?? []), c]);
  const order = STAGE_ORDER[business] ?? [...by.keys()];
  return (
    <>
      <p className="mb-6 text-ink-2">
        {total} {BUSINESSES[business as Business]} customers, in the order a customer moves through them.
      </p>
      <div className="grid grid-cols-3 gap-6">
        {order.map((stage, i) => {
          const rows = [...(by.get(stage) ?? [])].sort((a, b) => Number(b.key === HERO[business]) - Number(a.key === HERO[business]));
          const share = total ? rows.length / total : 0;
          return (
            <Card key={stage} className="flex flex-col">
              <div className="flex items-baseline justify-between">
                <h2 className="text-[1.45rem] font-medium">
                  <span className="mr-2 font-sans text-[0.9rem] text-muted">{i + 1}</span>
                  {stageLabel(stage)}
                </h2>
                <span className="font-serif text-[2.2rem] leading-none text-teal-ink">{rows.length}</span>
              </div>
              <div className="mt-3 h-1.5 rounded-full bg-sunk" aria-hidden>
                <div className="h-1.5 rounded-full bg-teal" style={{ width: `${Math.max(2, share * 100)}%` }} />
              </div>
              <p className="mt-1.5 text-right text-[0.82rem] text-muted">{Math.round(share * 100)}% of customers</p>
              <p className="mt-3 text-[0.95rem] leading-relaxed text-ink-2">{STAGE_RULE[stage]}</p>
              <ul className="mt-4 space-y-1.5 border-t border-line pt-4">
                {rows.slice(0, SHOWN).map((c) => {
                  const why = c.because[0];
                  return (
                    <li key={c.key} className="flex items-baseline justify-between gap-3">
                      <Link
                        href={`/${business}/customers/${encodeURIComponent(c.key)}`}
                        className="truncate text-ink hover:text-teal-ink hover:underline"
                      >
                        {c.name}
                      </Link>
                      {why && (
                        <span className="shrink-0 text-[0.82rem] text-muted">
                          {factLabel(why.fact)} {factValue(why.fact, why.value)}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
              {rows.length > SHOWN && <p className="mt-2 text-[0.85rem] text-muted">and {rows.length - SHOWN} more</p>}
            </Card>
          );
        })}
      </div>
    </>
  );
}
