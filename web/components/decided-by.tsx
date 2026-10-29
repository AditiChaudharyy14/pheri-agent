import Link from "next/link";
import { type DecidedBy, usd, type VerificationLine } from "@/lib/api";

const MODEL: Record<string, string> = { "muse-spark-1.3": "Muse Spark 1.3" };

/** Who decided, for what, in how many turns, and how it was checked:
 * "Decided by Muse Spark 1.3 · $0.0166 · 3 turns · Verified: 12 code checks + judge · View trace". */
export function DecidedByLine({
  business,
  customerKey,
  by,
  cost,
  turns,
  isPrivate,
  verification,
}: {
  business: string;
  customerKey: string;
  by: DecidedBy | null;
  cost: number;
  turns: number;
  isPrivate: boolean;
  verification?: VerificationLine | null;
}) {
  const model = by?.provider === "baseten" ? "Muse Spark Open" : (MODEL[by?.model ?? ""] ?? by?.model);
  const parts = !by
    ? ["No model was asked: code decided"]
    : by.source === "stand-in"
      ? ["Decided by the offline stand-in", usd(cost), `${turns} ${turns === 1 ? "turn" : "turns"}`]
      : [
          `Decided by ${model}${isPrivate ? " · private" : ""}`,
          usd(cost),
          `${turns} ${turns === 1 ? "turn" : "turns"}`,
        ];
  return (
    <p
      className="flex flex-wrap items-center gap-x-2 text-[0.88rem] text-muted"
      title={
        by?.source === "recorded" ? "Replayed from a recorded live run: the cost is what that run paid" : undefined
      }
    >
      {parts.map((p, i) => (
        <span key={p} className="flex items-center gap-2">
          {i > 0 && <span aria-hidden>·</span>}
          <span className={i === 0 ? "text-ink-2" : "tabular-nums"}>{p}</span>
        </span>
      ))}
      {verification && (
        <>
          <span aria-hidden>·</span>
          <VerifiedPart v={verification} />
        </>
      )}
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

function VerifiedPart({ v }: { v: VerificationLine }) {
  const drafts = v.attempts > 1 ? ` (draft ${v.attempts})` : "";
  if (v.passed)
    return (
      <span
        className="text-teal-ink"
        title={v.attempts > 1 ? `Earlier drafts were caught and sent back: ${v.attempts - 1}` : undefined}
      >
        ✓ Verified: {v.code_checks} code checks{v.judge ? " + judge" : ""}
        {drafts}
      </span>
    );
  return (
    <span className="text-amber" title={v.reasons.join("\n")}>
      ✗ Not verified after {v.attempts} {v.attempts === 1 ? "draft" : "drafts"}: caught by {v.caught_by}, sent to you
    </span>
  );
}
