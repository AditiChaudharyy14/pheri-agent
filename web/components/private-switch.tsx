"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { call } from "@/lib/api";

/** Full private mode on or off: every step on Muse Spark Open via Baseten, or on the Meta Model API. */
export function PrivateSwitch({ business, on }: { business: string; on: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const set = (full: boolean) =>
    start(async () => {
      await call(`/businesses/${business}/private-mode`, { method: "PUT", body: { by: "owner:demo", full } });
      router.refresh();
    });
  const option = (full: boolean, label: string, sub: string) => (
    <button
      onClick={() => set(full)}
      disabled={pending || on === full}
      aria-pressed={on === full}
      className={`flex-1 rounded-xl px-5 py-3 text-left transition-colors ${
        on === full ? "bg-ink text-paper" : "text-ink-2 hover:bg-sunk"
      } disabled:cursor-default`}
    >
      <span className="block font-medium">{label}</span>
      <span className={`block text-[0.85rem] ${on === full ? "text-paper/75" : "text-muted"}`}>{sub}</span>
    </button>
  );
  return (
    <div className="flex gap-1 rounded-2xl border border-line bg-paper p-1" role="group" aria-label="Private mode">
      {option(false, "Meta Model API", "Muse Spark")}
      {option(true, "Private mode", "Muse Spark Open via Baseten")}
    </div>
  );
}
