"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { call } from "@/lib/api";

/** Approve (code re-checks the rules first) or reject a queued action. */
export function ApproveReject({ business, approvalId }: { business: string; approvalId: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const decide = (verb: "approve" | "reject") =>
    start(async () => {
      setError(null);
      try {
        await call(`/businesses/${business}/approvals/${approvalId}/${verb}`, {
          body: verb === "approve" ? { by: "owner:demo" } : { by: "owner:demo", note: "Not now" },
        });
        router.refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    });

  return (
    <div className="flex flex-col items-stretch gap-2">
      <button
        onClick={() => decide("approve")}
        disabled={pending}
        className="rounded-xl bg-teal px-5 py-2.5 text-[0.98rem] font-medium text-white hover:bg-teal-ink disabled:opacity-60"
      >
        Approve
      </button>
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
