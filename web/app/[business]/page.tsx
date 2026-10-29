import Link from "next/link";
import { Suspense } from "react";
import { ApproveReject } from "@/components/approve";
import { DecidedByLine } from "@/components/decided-by";
import { EvidenceChips } from "@/components/evidence";
import { Badge, Card, Label, ModeBadge, PageHead, Skeleton, StageBadge } from "@/components/ui";
import { api, BUSINESSES, type Business, type NextStep } from "@/lib/api";
import { actionLabel, CHANNEL_LABEL, STATUS_LABEL } from "@/lib/labels";

export default function NextStepsPage({ params }: PageProps<"/[business]">) {
  return (
    <>
      <Suspense fallback={<PageHead title="Next steps" />}>
        <Head params={params} />
      </Suspense>
      <Suspense fallback={<Skeleton rows={4} />}>
        <Steps params={params} />
      </Suspense>
    </>
  );
}

async function Head({ params }: { params: PageProps<"/[business]">["params"] }) {
  const { business } = await params;
  return (
    <PageHead
      title="Next steps"
      lead={
        <>
          What Pheri would do next for each {BUSINESSES[business as Business]} customer, and why. Every step has passed the
          owner&rsquo;s rules in code, and Pheri checked its own draft before showing it to you; nothing reaches a
          customer until you approve it.
        </>
      }
    />
  );
}

async function Steps({ params }: { params: PageProps<"/[business]">["params"] }) {
  const { business } = await params;
  const steps = await api<NextStep[]>(`/businesses/${business}/next-steps`);
  return (
    <div className="space-y-6">
      {steps.map((s) => (
        <StepCard key={s.customer.key} business={business} step={s} />
      ))}
    </div>
  );
}

function StepCard({ business, step }: { business: string; step: NextStep }) {
  const { customer, decision: d, action } = step;
  const v = step.verification;
  const held = v && !v.passed && !step.override ? v.reasons : [];
  return (
    <Card>
      <div className="grid grid-cols-[1fr_auto] gap-8">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href={`/${business}/customers/${encodeURIComponent(customer.key)}`}
              className="font-serif text-[1.55rem] font-medium text-ink hover:text-teal-ink"
            >
              {customer.name}
            </Link>
            {customer.company && <span className="text-ink-2">{customer.company}</span>}
            <StageBadge stage={customer.stage} />
          </div>

          <div className="mt-4 flex flex-wrap items-baseline gap-3">
            <span className="text-[1.25rem] font-semibold text-teal-ink">{actionLabel(d.action)}</span>
            {d.channel && <span className="text-ink-2">{CHANNEL_LABEL[d.channel] ?? d.channel}</span>}
            {d.discount_pct ? <Badge tone="amber">{d.discount_pct}% off</Badge> : null}
          </div>
          {d.message && d.action !== "no_action" && (
            <blockquote className="mt-3 border-l-2 border-teal/40 pl-4 text-[1.02rem] leading-relaxed text-ink-2">
              {d.message}
            </blockquote>
          )}

          <div className="mt-5 grid grid-cols-2 gap-6">
            <div>
              <Label>Why this</Label>
              <p className="mt-1.5 leading-relaxed text-ink">{d.why_this}</p>
            </div>
            <div>
              <Label>Why now</Label>
              <p className="mt-1.5 leading-relaxed text-ink">{d.why_now || "—"}</p>
            </div>
          </div>

          <div className="mt-5">
            <Label>Evidence</Label>
            <div className="mt-2">
              <EvidenceChips evidence={step.evidence} />
            </div>
          </div>
          {held.length > 0 && (
            <p className="mt-4 rounded-lg bg-amber-soft px-3 py-2 text-[0.92rem] text-amber">
              Not sent: after {v?.attempts} {v?.attempts === 1 ? "draft" : "drafts"} it still failed Pheri&rsquo;s checks,
              so it waits for you. {held.join("; ")}.
            </p>
          )}
        </div>

        <aside className="flex w-52 flex-col items-stretch gap-4">
          <div className="flex flex-wrap items-center justify-end gap-2">
            <ModeBadge mode={action?.mode} />
            {step.private && <Badge tone="teal">Private</Badge>}
          </div>
          {action && (
            <div className="text-right text-[0.95rem]">
              <span className={action.status === "blocked" ? "text-rose" : "text-ink-2"}>
                {STATUS_LABEL[action.status] ?? action.status}
              </span>
            </div>
          )}
          {step.approval?.decision === "pending" && (
            <ApproveReject business={business} approvalId={step.approval.id} check={action?.payload.verification} />
          )}
        </aside>
      </div>
      <div className="mt-6 border-t border-line pt-4">
        <DecidedByLine
          business={business}
          customerKey={customer.key}
          by={step.decided_by}
          cost={step.cost_usd}
          turns={step.turns}
          isPrivate={step.private}
          verification={step.verification}
          override={step.override}
        />
      </div>
    </Card>
  );
}
