import type { Evidence } from "@/lib/api";
import { factLabel, stageLabel } from "@/lib/labels";
import { Chip } from "./ui";

/** The facts and verified quotes code attached to a decision. The model picked them by id; code filled them in. */
export function EvidenceChips({ evidence }: { evidence: Evidence[] }) {
  if (!evidence.length) return <p className="text-[0.92rem] text-muted">No evidence attached.</p>;
  const facts = evidence.filter((e) => e.kind === "fact");
  const quotes = evidence.filter((e) => e.kind === "quote");
  return (
    <div className="space-y-2.5">
      {facts.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {facts.map((e) => (
            <Chip key={e.ref} title="A fact counted in code">
              <span className="text-muted">{factLabel(e.ref)}</span>
              <span className="font-medium text-ink">{e.ref === "journey_stage" ? stageLabel(e.value) : e.value}</span>
            </Chip>
          ))}
        </div>
      )}
      {quotes.length > 0 && (
        <ul className="space-y-1.5">
          {quotes.map((e) => (
            <li key={e.quote_id ?? e.value} className="flex items-baseline gap-2 text-[0.95rem] text-ink-2">
              <span className="font-serif text-[1.05rem] text-ink">&ldquo;{e.value}&rdquo;</span>
              <span className="shrink-0 font-mono text-[0.78rem] text-muted" title="The message it is quoted from">
                {e.ref}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
