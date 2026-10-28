import { Suspense } from "react";
import { Badge, Card, Label, PageHead, Skeleton } from "@/components/ui";
import { api, type ProviderSpend, type Spend, type SpendRow } from "@/lib/api";

const PROVIDER: Record<string, { name: string; sub: string }> = {
  meta: { name: "Meta Model API", sub: "Muse Spark, Muse Wonder" },
  baseten: { name: "Baseten", sub: "Muse Spark Open, private mode" },
};
const PURPOSE: Record<string, string> = {
  profile_insights: "Customer profiles",
  decide: "Next best actions (tool loop)",
  decide_private: "Next best actions, private mode",
  guard: "Reading replies",
  compile_rule: "Compiling rules",
  learn_report: "What Pheri learned",
  smoke: "Smoke tests",
};
const MODEL: Record<string, string> = {
  "muse-spark-1.3": "Muse Spark",
  "muse-wonder-1.0": "Muse Wonder",
  "meta-models/muse-spark-open-1026": "Muse Spark Open",
};

const money = (v: number, digits = 4) => `$${v.toFixed(digits)}`;
const tokens = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}k` : `${n}`);
const day = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export default function SpendPage({ params }: PageProps<"/[business]/spend">) {
  return (
    <>
      <PageHead
        title="Spend"
        lead="Every model call reserves its worst-case cost before it is sent. Code refuses any call that would pass a cap, so free credits can never turn into a bill."
      />
      <Suspense fallback={<Skeleton rows={3} />}>
        <SpendView params={params} />
      </Suspense>
    </>
  );
}

async function SpendView({ params }: { params: PageProps<"/[business]/spend">["params"] }) {
  await params; // spend is per provider, the same for every business
  const s = await api<Spend>("/spend");
  const live = s.live_runs;
  const here = s.by_purpose.reduce((n, r) => n + r.calls, 0);
  return (
    <div className="space-y-8">
      {live && (
        <>
          <div className="flex items-baseline justify-between">
            <h2 className="text-[1.7rem] font-medium">This week&rsquo;s live runs</h2>
            <span className="text-ink-2">
              {live.calls.reduce((n, r) => n + r.calls, 0)} paid calls · ledger as of {day(live.as_of)}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-6">
            {Object.entries(live.providers).map(([p, t]) => (
              <ProviderCard key={p} provider={p} t={t} />
            ))}
          </div>
          <Card>
            <h2 className="mb-4 text-[1.45rem] font-medium">Where it went</h2>
            <Breakdown rows={live.calls} />
          </Card>
        </>
      )}

      <div className="grid grid-cols-2 gap-6">
        <Card>
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="text-[1.35rem] font-medium">This server</h2>
            <Badge tone={s.mode === "mock" ? "slate" : "amber"}>{s.mode === "mock" ? "Mock mode" : "Live mode"}</Badge>
          </div>
          <p className="mt-2 text-ink-2">
            {s.mode === "mock"
              ? `What you are clicking through runs offline. Its ledger holds ${here.toLocaleString()} offline calls, every one counted at $0.`
              : `Its ledger holds ${here.toLocaleString()} calls, each one settled at its real cost.`}
          </p>
          <table className="mt-4 w-full text-[0.95rem]">
            <tbody>
              {Object.entries(s.providers).map(([p, t]) => (
                <tr key={p} className="border-t border-line">
                  <td className="py-2.5 text-ink-2">{PROVIDER[p]?.name ?? p}</td>
                  <td className="py-2.5 text-right tabular-nums text-ink">
                    {money(t.settled_usd + (t.reserved_usd ?? 0))}
                    <span className="text-muted"> of {money(t.cap_usd, 0)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card>
          <Label>How a call is paid for</Label>
          <ol className="mt-3 space-y-2.5 text-[0.95rem] text-ink-2">
            <li>
              <span className="mr-2 font-serif text-teal">1</span>Code estimates the worst case and reserves it in the
              ledger. Over {money(s.max_call_usd, 2)} for one call, or past the cap, and nothing is sent.
            </li>
            <li>
              <span className="mr-2 font-serif text-teal">2</span>The call runs. Only synthetic customers ever reach a
              model.
            </li>
            <li>
              <span className="mr-2 font-serif text-teal">3</span>The reservation is settled with the real cost from the
              usage report, or released if the call failed.
            </li>
          </ol>
        </Card>
      </div>
    </div>
  );
}

function ProviderCard({ provider, t }: { provider: string; t: ProviderSpend }) {
  const used = t.settled_usd + t.offset_usd;
  const share = t.cap_usd ? used / t.cap_usd : 0;
  const info = PROVIDER[provider] ?? { name: provider, sub: "" };
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <h3 className="text-[1.35rem] font-medium">{info.name}</h3>
          <p className="text-[0.9rem] text-muted">{info.sub}</p>
        </div>
        <span className="text-[0.9rem] text-muted tabular-nums">cap {money(t.cap_usd, 0)}</span>
      </div>
      <p className="mt-4 font-serif text-[3rem] leading-none text-ink tabular-nums">{money(used)}</p>
      <div
        className="mt-5 h-2.5 w-full overflow-hidden rounded-full bg-grid"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={t.cap_usd}
        aria-valuenow={used}
        aria-label={`${info.name}: ${money(used)} of the ${money(t.cap_usd, 0)} cap`}
      >
        <div className="h-full rounded-full bg-chart" style={{ width: `max(4px, ${(share * 100).toFixed(2)}%)` }} />
      </div>
      <div className="mt-2 flex justify-between text-[0.92rem] tabular-nums">
        <span className="text-ink-2">{(share * 100).toFixed(2)}% of the cap used</span>
        <span className="text-muted">{money(t.remaining_usd, 2)} left</span>
      </div>
    </Card>
  );
}

function Breakdown({ rows }: { rows: SpendRow[] }) {
  const total = rows.reduce((n, r) => n + r.usd, 0);
  return (
    <table className="w-full text-[0.98rem]">
      <thead>
        <tr className="text-left text-[0.82rem] text-muted">
          <th className="pb-2 font-normal">What for</th>
          <th className="pb-2 font-normal">Model</th>
          <th className="pb-2 text-right font-normal">Calls</th>
          <th className="pb-2 text-right font-normal">Tokens in (cached)</th>
          <th className="pb-2 text-right font-normal">Tokens out</th>
          <th className="pb-2 text-right font-normal">Per call</th>
          <th className="pb-2 text-right font-normal">Cost</th>
        </tr>
      </thead>
      <tbody className="tabular-nums">
        {rows.map((r) => (
          <tr key={`${r.provider}-${r.model}-${r.purpose}`} className="border-t border-line">
            <td className="py-2.5 text-ink">{PURPOSE[r.purpose] ?? r.purpose}</td>
            <td className="py-2.5 text-ink-2">{MODEL[r.model] ?? r.model}</td>
            <td className="py-2.5 text-right text-ink-2">{r.calls}</td>
            <td className="py-2.5 text-right text-ink-2">
              {tokens(r.input_tokens)} <span className="text-muted">({tokens(r.cached_tokens)})</span>
            </td>
            <td className="py-2.5 text-right text-ink-2">{tokens(r.output_tokens)}</td>
            <td className="py-2.5 text-right text-muted">{money(r.usd / Math.max(1, r.calls))}</td>
            <td className="py-2.5 text-right font-medium text-ink">{money(r.usd)}</td>
          </tr>
        ))}
        <tr className="border-t-2 border-line-2">
          <td className="pt-3 font-medium text-ink" colSpan={6}>
            Total, both providers
          </td>
          <td className="pt-3 text-right font-medium text-ink">{money(total)}</td>
        </tr>
      </tbody>
    </table>
  );
}
