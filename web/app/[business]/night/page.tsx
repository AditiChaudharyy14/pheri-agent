import Link from "next/link";
import { Suspense } from "react";
import { NightPlayback } from "@/components/night-playback";
import { PrivateSwitch } from "@/components/private-switch";
import { Badge, Card, Chip, Label, PageHead, Skeleton } from "@/components/ui";
import { api, type Brief, type Reply, type RunsOn, words } from "@/lib/api";

const LANG: Record<string, string> = { en: "English", es: "Spanish", pt: "Portuguese", hi: "Hindi", ne: "Nepali", bh: "Bhojpuri / Hindi", bho: "Bhojpuri" };
const STEP: Record<string, string> = { guard: "Reading replies", profile: "Profiles", decide: "Decisions", rules: "Compiling rules" };

export default function NightPage({ params }: PageProps<"/[business]/night">) {
  return (
    <>
      <PageHead
        title="Night shift"
        lead="What came in overnight and how Pheri read it. Code reads every message before and after the model; an attack never becomes an action, it comes to you."
      />
      <Suspense fallback={<Skeleton rows={2} />}>
        <Timeline params={params} />
      </Suspense>
      <Suspense fallback={<Skeleton rows={3} />}>
        <Night params={params} />
      </Suspense>
    </>
  );
}

/** Tonight, message by message, replayed: what came in, every draft Pheri wrote (caught, sent back, rewritten), and
 * where it ended up. Only drafts that really happened: each row is the stored decision. */
async function Timeline({ params }: { params: PageProps<"/[business]/night">["params"] }) {
  const { business } = await params;
  const b = await api<Brief>(`/businesses/${business}/brief`);
  if (!b.timeline.length) return null;
  return (
    <section aria-labelledby="tonight" className="mb-10">
      <h2 id="tonight" className="mb-3 text-[1.45rem] font-medium lg:text-[1.7rem]">Tonight, message by message</h2>
      <NightPlayback business={business} events={b.timeline} />
    </section>
  );
}

async function Night({ params }: { params: PageProps<"/[business]/night">["params"] }) {
  const { business } = await params;
  const [replies, runs] = await Promise.all([
    api<Reply[]>(`/businesses/${business}/replies`),
    api<RunsOn>(`/businesses/${business}/private-mode/runs-on`),
  ]);
  const sorted = [...replies].sort((a, b) => Number(b.attack) - Number(a.attack));
  const attacks = replies.filter((r) => r.attack).length;
  return (
    <div className="grid items-start gap-6 lg:grid-cols-[1fr_400px] lg:gap-8">
      <div>
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-[1.45rem] font-medium lg:text-[1.7rem]">Messages that came in</h2>
          <span className="text-ink-2">
            {replies.length} read · {attacks} stopped
          </span>
        </div>
        <ul className="space-y-4">
          {sorted.map((r) => (
            <li key={r.source_id}>
              <ReplyCard business={business} r={r} />
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-6">
        <Card>
          <h2 className="text-[1.45rem] font-medium">Which model reads your customers</h2>
          <p className="mt-1 mb-5 text-ink-2">
            Private mode runs every step on Muse Spark Open: Meta&rsquo;s open-weight model, served by a partner (Baseten),
            self-hostable. Nothing goes to the Meta Model API; code refuses any call that would.
          </p>
          <PrivateSwitch business={business} on={runs.full_private} />
          <table className="mt-5 w-full text-[0.95rem]">
            <tbody>
              {Object.entries(runs.steps).map(([step, m]) => (
                <tr key={step} className="border-t border-line">
                  <td className="py-2.5 pr-3 whitespace-nowrap text-ink-2">{STEP[step] ?? step}</td>
                  <td className="py-2.5 text-right" title={m.model}>
                    <span className={`font-medium ${m.provider === "baseten" ? "text-teal-ink" : "text-ink"}`}>
                      {m.provider === "baseten" ? "Muse Spark Open" : "Muse Spark"}
                    </span>
                    <span className="block text-[0.82rem] whitespace-nowrap text-muted">
                      {m.provider === "baseten" ? "Baseten" : "Meta Model API"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card>
          <Label>How a message is read</Label>
          <ol className="mt-3 space-y-2.5 text-[0.95rem] text-ink-2">
            <li>
              <span className="mr-2 font-serif text-teal">1</span>Code screens it for attacks, in Nepali, Roman Nepali, Hindi, Bhojpuri and English.
            </li>
            <li>
              <span className="mr-2 font-serif text-teal">2</span>The model labels it, reading it as data inside a sealed block.
            </li>
            <li>
              <span className="mr-2 font-serif text-teal">3</span>Code checks the answer: an attack seen by either side is an attack.
            </li>
          </ol>
        </Card>
      </div>
    </div>
  );
}

const TONE: Record<string, "rose" | "amber" | "teal" | "slate"> = {
  attack: "rose",
  stop: "amber",
  complaint: "amber",
  objection: "slate",
  question: "slate",
  purchase_intent: "teal",
  other: "slate",
};

function ReplyCard({ business, r }: { business: string; r: Reply }) {
  return (
    <Card className={r.attack ? "border-rose/30" : ""}>
      <div className="flex flex-wrap items-center gap-2.5">
        <Badge tone={TONE[r.label] ?? "slate"}>{words(r.label)}</Badge>
        <Badge>{LANG[r.language] ?? r.language}</Badge>
        <Link href={`/${business}/customers/${encodeURIComponent(r.customer.key)}`} className="ml-1 text-ink hover:text-teal-ink">
          {r.customer.name}
        </Link>
        {r.escalation && (
          <span className="ml-auto">
            <Badge tone={r.escalation.status === "awaiting_approval" ? "rose" : "slate"}>
              {r.escalation.status === "awaiting_approval" ? "Stopped: waiting for you" : "Handled"}
            </Badge>
          </span>
        )}
      </div>
      <Message text={r.text} kind={r.kind} lang={r.language} />
      <p className="mt-2 text-[0.95rem] text-ink-2">
        <span className="text-muted">Summary: </span>
        {r.summary}
      </p>
      {(r.screen_before.length > 0 || r.screen_after.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-2">
          {r.screen_before.map((h) => (
            <Chip key={h} title="Caught by the code screen, before the model">
              <span className="text-rose">code caught</span> {words(h)}
            </Chip>
          ))}
          {r.screen_after.map((h) => (
            <Chip key={h} title="Corrected by code, after the model">
              <span className="text-amber">code corrected</span> {words(h)}
            </Chip>
          ))}
        </div>
      )}
    </Card>
  );
}

/** A ticket is a subject line, a newline, then the body; a message is just its text. */
function Message({ text, kind, lang }: { text: string; kind: string; lang?: string }) {
  const [subject, ...rest] = text.split("\n");
  const body = rest.join("\n");
  return kind === "ticket" && body ? (
    <div className="mt-3">
      <p className="text-[0.95rem] font-medium text-ink-2">{subject}</p>
      <p className="mt-1 font-serif text-[1.12rem] leading-snug text-ink">&ldquo;{body}&rdquo;</p>
    </div>
  ) : (
    <p lang={lang} className="mt-3 font-serif text-[1.12rem] leading-snug text-ink">&ldquo;{text}&rdquo;</p>
  );
}
