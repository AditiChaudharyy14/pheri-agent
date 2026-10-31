import Link from "next/link";
import { Suspense } from "react";
import { ApproveReject } from "@/components/approve";
import { DecidedByLine } from "@/components/decided-by";
import { EvidenceChips } from "@/components/evidence";
import { Badge, Card, Chip, Label, ModeBadge, Skeleton, StageBadge } from "@/components/ui";
import { api, customerPath, type CustomerDetail, type Insight, type NextStep, type Profile } from "@/lib/api";
import { actionLabel, CHANNEL_LABEL, factLabel, factValue, STATUS_LABEL } from "@/lib/labels";

type Params = PageProps<"/[business]/customers/[key]">["params"];

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
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4 lg:mb-8">
        <div>
          <Link href={`/${business}`} className="text-[0.92rem] text-muted hover:text-teal-ink">
            ← Next steps
          </Link>
          <div className="mt-2 flex flex-wrap items-baseline gap-4">
            <h1 className="text-[2rem] leading-tight font-medium lg:text-[2.6rem]">{c.name}</h1>
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

      <div className="grid items-start gap-6 lg:grid-cols-[1fr_420px] lg:gap-8">
        <div className="space-y-6">
          <Card>
            <div className="flex items-baseline justify-between gap-4">
              <h2 className="text-[1.45rem] font-medium">Why {first} is here</h2>
              <Link href={`/${business}/journey`} className="text-[0.92rem] text-muted hover:text-teal-ink">
                Every stage →
              </Link>
            </div>
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
            <details>
              <summary className="cursor-pointer">
                <span className="text-[1.45rem] font-medium">Facts, with their sources</span>
                <span className="mt-1 block text-ink-2">Every number is counted in code and names the rows it came from.</span>
              </summary>
            <table className="mt-4 w-full text-[0.95rem]">
              <tbody>
                {Object.entries(c.facts).map(([f, v]) => {
                  return (
                    <tr key={f} className="border-t border-line align-top">
                      <td className="py-2.5 pr-4 text-ink-2">{factLabel(f)}</td>
                      <td className="py-2.5 pr-4 font-medium text-ink">{factValue(f, v)}</td>

                    </tr>
                  );
                })}
              </tbody>
            </table>
            </details>
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
                    check={step.action?.payload.verification}
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
                override={step.override}
              />
            </div>
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
        <li key={`${title}-${i.source_id}-${n}`} className="grid grid-cols-[6rem_1fr] items-baseline gap-4 border-t border-line pt-3">
          <span className="text-[0.85rem] text-muted">
            {title}
            {i.label && title !== "Language" && i.label.length <= 40 && !i.quote.startsWith(i.label) ? (
              <span className="block text-ink-2">{i.label}</span>
            ) : null}
            {title === "Language" && i.code ? <span className="block text-ink-2">{i.code}</span> : null}
          </span>
          <span className="font-serif text-[1.08rem] leading-snug text-ink">&ldquo;{i.quote}&rdquo;</span>
        </li>
      ))}
    </ul>
  );
}
