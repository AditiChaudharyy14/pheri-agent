import Link from "next/link";
import { type DecidedBy, usd } from "@/lib/api";

const MODEL: Record<string, string> = { "muse-spark-1.3": "Muse Spark 1.3" };

/** Who decided, for what, in how many turns: "Decided by Muse Spark 1.3 · $0.0166 · 3 turns · View trace". */
export function DecidedByLine({ business, customerKey, by, cost, turns, isPrivate }: {
  business: string;
  customerKey: string;
  by: DecidedBy | null;
  cost: number;
  turns: number;
  isPrivate: boolean;
}) {
  const model = by?.provider === "baseten" ? "Muse Spark Open" : (MODEL[by?.model ?? ""] ?? by?.model);
  const parts = !by
    ? ["No model was asked: code decided"]
    : by.source === "stand-in"
      ? ["Decided by the offline stand-in", usd(cost), `${turns} ${turns === 1 ? "turn" : "turns"}`]
      : [`Decided by ${model}${isPrivate ? " · private" : ""}`, usd(cost), `${turns} ${turns === 1 ? "turn" : "turns"}`];
  return (
    <p
      className="flex flex-wrap items-center gap-x-2 text-[0.88rem] text-muted"
      title={by?.source === "recorded" ? "Replayed from a recorded live run: the cost is what that run paid" : undefined}
    >
      {parts.map((p, i) => (
        <span key={p} className="flex items-center gap-2">
          {i > 0 && <span aria-hidden>·</span>}
          <span className={i === 0 ? "text-ink-2" : "tabular-nums"}>{p}</span>
        </span>
      ))}
      {by && (
        <>
          <span aria-hidden>·</span>
          <Link
            href={`/${business}/customers/${encodeURIComponent(customerKey)}/trace`}
            className="font-medium text-teal-ink hover:underline"
          >
            View trace
          </Link>
        </>
      )}
    </p>
  );
}
