"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { call, softSummary, type StoredVerification } from "@/lib/api";

/** Approve (code re-checks the rules first) or reject a queued action. A draft that failed only soft checks can be
 * sent anyway, as an owner override on the record; one that failed a hard check can only be rejected. A money
 * question comes with code's two choices: picking one sends Pheri's holding reply and keeps the pick on record. */
export function ApproveReject({ business, approvalId, check, options = [] }: { business: string; approvalId: string;
  check?: StoredVerification | null; options?: string[] }) {
  const verified = !check || check.passed;
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const decide = (verb: "approve" | "reject", override = false, choice?: string) =>
    start(async () => {
      setError(null);
      try {
        await call(`/businesses/${business}/approvals/${approvalId}/${verb}`, {
          body: verb === "approve" ? { by: "owner:demo", override, ...(choice ? { choice } : {}) }
            : { by: "owner:demo", note: "Not now" },
        });
        router.refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    });

  return (
    <div className="flex flex-col items-stretch gap-2">
      {verified && options.length > 0 ? (
        <>
          <p className="text-[0.85rem] leading-snug text-ink-2">Send the holding reply, and you will:</p>
          {options.map((o, i) => (
            <button
              key={o}
              onClick={() => decide("approve", false, o)}
              disabled={pending}
              className={i === 0
                ? "rounded-xl bg-teal px-4 py-2.5 text-left text-[0.92rem] font-medium leading-snug text-white hover:bg-teal-ink disabled:opacity-60"
                : "rounded-xl border border-teal/50 bg-surface px-4 py-2.5 text-left text-[0.92rem] leading-snug text-teal-ink hover:bg-teal-soft disabled:opacity-60"}
            >
              {o}
            </button>
          ))}
        </>
      ) : verified ? (
        <button
          onClick={() => decide("approve")}
          disabled={pending}
          className="rounded-xl bg-teal px-5 py-2.5 text-[0.98rem] font-medium text-white hover:bg-teal-ink disabled:opacity-60"
        >
          Approve
        </button>
      ) : check?.overridable ? (
        <>
          <p className="text-[0.85rem] leading-snug text-amber">Failed soft checks: {check.summary ?? softSummary(check)}.</p>
          <button
            onClick={() => decide("approve", true)}
            disabled={pending}
            title="You read it and send it anyway. The audit log records who, when, which checks, and the exact text."
            className="rounded-xl border-2 border-amber/60 bg-amber-soft px-5 py-2 text-[0.98rem] font-medium text-amber hover:bg-amber-soft/70 disabled:opacity-60"
          >
            Send anyway
          </button>
        </>
      ) : (
        <p className="text-[0.85rem] leading-snug text-rose">
          Can&rsquo;t be sent: {(check?.hard_failed ?? []).map((c) => c.replaceAll("_", " ")).join(", ") || "it failed Pheri\u2019s checks"}
          , which no one can override. Reply yourself, or reject it.
        </p>
      )}
      <button
        onClick={() => decide("reject")}
        disabled={pending}
        className="rounded-xl border border-line-2 bg-surface px-5 py-2.5 text-[0.98rem] text-ink-2 hover:bg-sunk disabled:opacity-60"
      >
        Reject
      </button>
      {error && <p className="max-w-48 text-[0.85rem] text-rose">{error}</p>}
    </div>
  );
}
