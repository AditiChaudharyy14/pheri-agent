import Link from "next/link";

/** The demo tour (the Morning page's "Start here"), carried from page to page: where this page sits, and the next
 * step. Birgunj Saree Ghar only: it is the shop the tour is written for. */
const STEPS = [
  { title: "Morning brief", path: "" },
  { title: "Night shift", path: "/night" },
  { title: "Slop vs Pheri", path: "/slop" },
  { title: "Speak a rule", path: "/rules#speak" },
  { title: "Proof", path: "/proof" },
];

export function TourNext({ business, step, className = "" }: { business: string; step: number; className?: string }) {
  if (business !== "birgunj") return null;
  const next = STEPS[step]; // step is 1-based: STEPS[step] is the one after it
  return (
    <nav aria-label="Demo tour" className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[0.95rem] ${className}`}>
      <span className="text-muted">Tour, step {step} of {STEPS.length}</span>
      {next ? (
        <Link href={`/${business}${next.path}`} className="font-medium text-teal-ink underline underline-offset-4">
          Next: {next.title} →
        </Link>
      ) : (
        <Link href={`/${business}`} className="font-medium text-teal-ink underline underline-offset-4">
          That&rsquo;s the tour. Back to the morning →
        </Link>
      )}
    </nav>
  );
}
