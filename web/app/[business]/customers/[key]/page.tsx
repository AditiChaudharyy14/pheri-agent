import Link from "next/link";
import { Suspense } from "react";
import { ApproveReject } from "@/components/approve";
import { DecidedByLine } from "@/components/decided-by";
import { OfferDiscount } from "@/components/discount";
import { EvidenceChips } from "@/components/evidence";
import { Badge, Card, Chip, Label, ModeBadge, Skeleton, StageBadge } from "@/components/ui";
import { api, customerPath, type CustomerDetail, type Insight, type NextStep, type Profile } from "@/lib/api";
import { actionLabel, CHANNEL_LABEL, factLabel, factValue, STATUS_LABEL } from "@/lib/labels";

type Params = PageProps<"/[business]/customers/[key]">["params"];
const SHOWN_REFS = 2;

export default function CustomerPage({ params }: PageProps<"/[business]/customers/[key]">) {
  return (
    <Suspense fallback={<Skeleton rows={3} />}>
      <Customer params={params} />
    </Suspense>
  );
}

async function Customer({ params }: { params: Params }) {
  const { business, key: raw } = await params;
  const key = decodeURIComponent(raw);
  const path = customerPath(business, key);
  const [c, p, step] = await Promise.all([
    api<CustomerDetail>(path),
    api<Profile>(`${path}/profile`),
    api<NextStep>(`${path}/decision`),
  ]);
  const first = c.name.split(" ")[0];
  return (
    <>
      <header className="mb-8 flex items-end justify-between gap-6">
        <div>
          <Link href={`/${business}/journey`} className="text-[0.92rem] text-muted hover:text-teal-ink">
            ← Journey
          </Link>
          <div className="mt-2 flex flex-wrap items-baseline gap-4">
            <h1 className="text-[2.6rem] leading-tight font-medium">{c.name}</h1>
            {c.company && <span className="text-[1.15rem] text-ink-2">{c.company}</span>}
            <StageBadge stage={c.journey.stage} />
            {c.do_not_contact && <Badge tone="rose">Asked not to be contacted</Badge>}
          </div>
        </div>
        <Link
          href={`/${business}/customers/${encodeURIComponent(key)}/trace`}
          className="rounded-xl border border-line-2 bg-surface px-4 py-2.5 text-ink-2 hover:bg-sunk"
        >
          Decision trace →
        </Link>
      </header>

      <div className="grid grid-cols-[1fr_420px] items-start gap-8">
        <div className="space-y-6">
          <Card>
            <h2 className="text-[1.45rem] font-medium">Why {first} is here</h2>
            <p className="mt-1 text-ink-2">The journey rule that matched, counted in code.</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {c.journey.because.map((b) => (
                <Chip key={b.fact}>
                  <span className="text-muted">{factLabel(b.fact)}</span>
                  <span className="font-medium text-ink">{factValue(b.fact, b.value)}</span>
                </Chip>
              ))}
            </div>
          </Card>

          <Card>
            <h2 className="text-[1.45rem] font-medium">Facts, with their sources</h2>
            <p className="mt-1 text-ink-2">Every number is counted in code and names the rows it came from.</p>
            <table className="mt-4 w-full text-[0.95rem]">
              <tbody>
                {Object.entries(c.facts).map(([f, v]) => {
                  const refs = p.provenance.facts[f] ?? [];
                  return (
                    <tr key={f} className="border-t border-line align-top">
                      <td className="py-2.5 pr-4 text-ink-2">{factLabel(f)}</td>
                      <td className="py-2.5 pr-4 font-medium text-ink">{factValue(f, v)}</td>
                      <td className="py-2.5 text-right">
                        <span className="inline-flex flex-wrap justify-end gap-1.5">
                          {refs.slice(0, SHOWN_REFS).map((r) => (
                            <span key={r} className="rounded-md bg-sunk px-2 py-0.5 font-mono text-[0.76rem] text-muted">
                              {r}
                            </span>
                          ))}
                          {refs.length > SHOWN_REFS && (
                            <span className="px-1 text-[0.8rem] text-muted">+{refs.length - SHOWN_REFS} more</span>
                          )}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>

          <Card>
            <h2 className="text-[1.45rem] font-medium">What {first} wrote, verified</h2>
            <p className="mt-1 text-ink-2">
              Read by the model, then checked in code: each quote is really in the message it cites, or it is dropped.
            </p>
            <Quotes profile={p} />
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <div className="flex items-center justify-between">
              <Label>Pheri&rsquo;s next step</Label>
              <div className="flex gap-2">
                <ModeBadge mode={step.action?.mode} />
                {step.private && <Badge tone="teal">Private</Badge>}
              </div>
            </div>
            <p className="mt-3 text-[1.3rem] font-semibold text-teal-ink">
              {actionLabel(step.decision.action)}{" "}
              {step.decision.channel && (
                <span className="text-[1rem] font-normal text-ink-2">{CHANNEL_LABEL[step.decision.channel]}</span>
              )}
            </p>
            {step.decision.message && (
              <blockquote className="mt-3 border-l-2 border-teal/40 pl-4 leading-relaxed text-ink-2">
                {step.decision.message}
              </blockquote>
            )}
            <div className="mt-4 space-y-3">
              <div>
                <Label>Why this</Label>
                <p className="mt-1 leading-relaxed">{step.decision.why_this}</p>
              </div>
              <div>
                <Label>Why now</Label>
                <p className="mt-1 leading-relaxed">{step.decision.why_now || "—"}</p>
              </div>
            </div>
            <div className="mt-4">
              <EvidenceChips evidence={step.evidence} />
            </div>
            <div className="mt-5 flex items-end justify-between gap-4">
              <div className="text-[0.92rem] text-ink-2">
                {step.action && (STATUS_LABEL[step.action.status] ?? step.action.status)}
              </div>
              {step.approval?.decision === "pending" && (
                <div className="w-40">
                  <ApproveReject
                    business={business}
                    approvalId={step.approval.id}
                    verified={step.action?.payload.verification?.passed !== false}
                  />
                </div>
              )}
            </div>
            <div className="mt-5 border-t border-line pt-3">
              <DecidedByLine
                business={business}
                customerKey={key}
                by={step.decided_by}
                cost={step.cost_usd}
                turns={step.turns}
                isPrivate={step.private}
                verification={step.verification}
              />
            </div>
          </Card>

          <Card>
            <Label>Try it</Label>
            <p className="mt-2 mb-4 text-ink-2">Would the owner&rsquo;s rules let Pheri offer {first} a discount?</p>
            <OfferDiscount business={business} customerKey={key} name={first} />
          </Card>
        </div>
      </div>
    </>
  );
}

const GROUPS: [keyof Profile["insights"], string][] = [
  ["goals", "Goals"],
  ["needs", "Needs"],
  ["blockers", "Blockers"],
  ["role", "Role"],
  ["sentiment", "Mood"],
  ["language", "Language"],
];

function Quotes({ profile }: { profile: Profile }) {
  const rows = GROUPS.flatMap(([k, title]) => {
    const v = profile.insights[k];
    const items = (Array.isArray(v) ? v : v ? [v] : []) as Insight[];
    return items.map((i, n) => ({ title, i, n }));
  });
  if (!rows.length) return <p className="mt-4 text-muted">Nothing to read yet.</p>;
  return (
    <ul className="mt-4 space-y-3">
      {rows.map(({ title, i, n }) => (
        <li key={`${title}-${i.source_id}-${n}`} className="grid grid-cols-[7rem_1fr_auto] items-baseline gap-4 border-t border-line pt-3">
          <span className="text-[0.85rem] text-muted">
            {title}
            {i.label && title !== "Language" && i.label.length <= 40 && !i.quote.startsWith(i.label) ? (
              <span className="block text-ink-2">{i.label}</span>
            ) : null}
            {title === "Language" && i.code ? <span className="block text-ink-2">{i.code}</span> : null}
          </span>
          <span className="font-serif text-[1.08rem] leading-snug text-ink">&ldquo;{i.quote}&rdquo;</span>
          <span className="font-mono text-[0.78rem] text-muted">{i.source_id}</span>
        </li>
      ))}
    </ul>
  );
}
