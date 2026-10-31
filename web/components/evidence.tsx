import type { Evidence, Receipt } from "@/lib/api";
import { CHANNEL_NAME, factLabel, factValue, langOf } from "@/lib/labels";

/** Every claim carries its receipt: the customer's own words (in their script) with where and when they wrote it,
 * or the shop's order numbers a fact was counted from. The model picked the evidence by id; code filled it in. */
export function EvidenceChips({ evidence }: { evidence: Evidence[] }) {
  const shown = evidence.filter((e) => e.ref !== "journey_stage");
  if (!shown.length) return <p className="text-[0.92rem] text-muted">No receipts attached.</p>;
  const facts = shown.filter((e) => e.kind === "fact");
  const quotes = shown.filter((e) => e.kind === "quote");
  return (
    <div className="space-y-2">
      {quotes.map((e) => (
        <figure key={e.quote_id ?? e.value} className="border-l-2 border-line-2 py-0.5 pl-3">
          <blockquote lang={e.receipt?.kind === "message" ? langOf(e.receipt.lang) : undefined}
                      className="font-serif text-[1.05rem] leading-snug text-ink">
            &ldquo;{e.value}&rdquo;
          </blockquote>
          <figcaption className="mt-1 text-[0.8rem] text-muted">{receiptText(e.receipt)}</figcaption>
        </figure>
      ))}
      {facts.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {facts.map((e) => (
            <li key={e.ref} className="inline-flex max-w-full flex-wrap items-baseline gap-x-1.5 rounded-lg border border-line bg-paper px-2.5 py-1 text-[0.85rem]">
              <span className="text-muted">{factLabel(e.ref)}</span>
              <span className="font-medium text-ink">{factValue(e.ref, e.ref === "usage_change_pct" ? Number(e.value) : e.value)}</span>
              {e.receipt && <span className="text-[0.78rem] text-muted">· {receiptText(e.receipt)}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function receiptText(r: Receipt | null | undefined): string {
  if (!r) return "counted from the shop's records";
  if (r.kind === "order") return `order ${r.ids.join(", ")}${r.more ? ` +${r.more} more` : ""}`;
  if (r.kind === "calendar") return "festival calendar";
  if (r.kind === "activity") return "activity log";
  if (r.from_staff) return "a note by the team";
  const when = r.at ? new Date(r.at).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "Asia/Kathmandu" }) : "";
  return [r.channel ? `on ${CHANNEL_NAME[r.channel] ?? r.channel}` : "their message", when].filter(Boolean).join(", ");
}
