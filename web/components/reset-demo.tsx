"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { call } from "@/lib/api";

/** Back to the start: in the public demo, this visitor's own sandbox only. */
export function ResetDemo({ publicDemo }: { publicDemo: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <button
      onClick={() => start(async () => {
        await call("/demo/reset");
        router.refresh();
      })}
      disabled={pending}
      title={publicDemo
        ? "Your own copy of the demo: approvals, rules and switches you changed go back to the start. Nobody else's change."
        : "Every approval, rule and switch back to the start."}
      className="rounded-full border border-line px-3 py-1 text-[0.8rem] text-ink-2 hover:bg-sunk disabled:opacity-60"
    >
      {pending ? "Resetting…" : "Reset demo"}
    </button>
  );
}
