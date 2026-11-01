import { Suspense } from "react";
import { MilestoneChart, RangeBar, sharedDomain } from "@/components/proof-charts";
import { Card, Label, PageHead, Skeleton } from "@/components/ui";
import { api, type Evals, type Learned, type Measured, pct, pp, type TwinResults, type VerificationTotals } from "@/lib/api";
import { actionLabel, LANGUAGE_NAME, stageLabel } from "@/lib/labels";
import { TourNext } from "@/components/tour-next";

const SMALL_SAMPLE = 120; // fewer customers held back than this in a stage: its likely range is wide, and we say so
const EVAL_LANGS = ["ne", "ne-Latn", "hi", "bho", "en"] as const;

export default function ProofPage({ params }: PageProps<"/[business]/proof">) {
  return (
    <>
      <PageHead
        title="Proof"
        lead="Did Pheri's follow-ups work, and is it safe? Every number here was measured, and code checks each one."
        right={
          <span className="rounded-xl border-2 border-amber/50 bg-amber-soft px-4 py-2 text-[0.95rem] font-semibold tracking-[0.12em] text-amber">
            SIMULATED
          </span>
        }
      />
      <Suspense fallback={<Skeleton rows={3} />}>
        <Proof params={params} />
      </Suspense>
    </>
  );
}

/** Model text in the page's plain words (display only: the report code checked is unchanged). "Holdout" is the
 * customers Pheri deliberately didn't message; "lift" is extra orders (or replies) per 100 customers; a "close call"
 * is too close to call; an "action" is a kind of message; a "stage" is a kind of customer. */
const plainTwin = (t: string, unit = "orders") =>
  t
    .replace(/\bin the holdout\b/g, "among customers Pheri didn't message")
    .replace(/\bthe holdout\b/g, "customers Pheri didn't message")
    .replace(/\btreated\b/g, "followed up")
    .replace(/\b[Tt]he lift was \+?([\d.]+) points\b/g, `That is $1 more ${unit} per 100 customers`)
    .replace(/\blifting the rate by \+?([\d.]+) points\b/g, `adding $1 ${unit} per 100 customers`)
    .replace(/\bthe lift\b/gi, `the extra ${unit}`)
    .replace(/\bit is a close call with\b/g, "it is too close to call against")
    .replace(/\bis a close call against\b/g, "is too close to call against")
    .replace(/\bthe close calls\b/g, "the results too close to call")
    .replace(/\ba close call\b/g, "too close to call")
    .replace(/\bthe runner-up\b/g, "the second-best message")
    .replace(/\bbest action\b/g, "best message")
    .replace(/\baction groups\b/g, "messages")
    .replace(/\bsample sizes\b/g, "few customers")
    .replace(/\bhad small few customers\b/g, "were tried on few customers")
    .replace(/\blisted in the findings\b/g, "named above")
    .replace(/\bat some stages\b/g, "for some kinds of customer")
    .replace(/\bthe overall stage results\b/g, "the overall result for each kind of customer")
    .replace(/\bindividual actions\b/g, "messages")
    .replace(/\bstages?\b/g, (m) => (m === "stage" ? "kind of customer" : "kinds of customer"))
    .replace(/\bwas a clear call\b/g, "was clear");

const range = (m: Measured) => (m.ci ? `likely ${Math.round(m.ci[0] * 100)}–${Math.round(m.ci[1] * 100)}%` : "");

async function Proof({ params }: { params: PageProps<"/[business]/proof">["params"] }) {
  const { business } = await params;
  const [twin, learned, checked, evals] = await Promise.all([
    api<TwinResults>(`/businesses/${business}/twin`),
    api<Learned>(`/businesses/${business}/learned`),
    api<VerificationTotals>(`/businesses/${business}/verification`),
    api<Evals>(`/evals`),
  ]);
  const o = twin.overall;
  const held = Math.round(twin.holdout_share * 100);
  const orders = Boolean(twin.milestones); // with milestones, the outcome that counts is the order
  const unit = orders ? "orders" : "replies";
  const did = orders ? "ordered" : "replied";
  const stages = twin.stages.filter((s) => s.lift_pp != null && s.ci_pp);
  const lifts = stages.map((s) => s.lift_pp!);
  return (
    <div className="space-y-10">
      <Card>
        <p className="font-serif text-[1.9rem] leading-snug text-ink lg:text-[2.2rem]">
          <span className={o.verdict === "works" ? "text-teal-ink" : ""}>{pp(o.lift_pp)} points overall</span>{" "}
          <span className="text-ink-2">(all kinds of customer combined).</span>
        </p>
        <p className="mt-3 max-w-[56rem] text-[1.08rem] text-ink">
          Customers Pheri followed up with {did} {pct(o.treated.rate)} of the time. Customers Pheri deliberately didn&rsquo;t
          message {did} {pct(o.holdout.rate)}.
        </p>
        <dl className="mt-5 grid max-w-[56rem] gap-x-6 gap-y-3 border-t border-line pt-4 text-[0.97rem] sm:grid-cols-[11rem_1fr]">
          <dt className="font-medium text-ink">Points</dt>
          <dd className="text-ink-2">
            Extra {unit} per 100 customers. {pp(o.lift_pp)} means about {Math.round(o.lift_pp ?? 0)} more {unit} for every
            100 customers Pheri followed up with.
          </dd>
          <dt className="font-medium text-ink">Likely range</dt>
          <dd className="text-ink-2">
            {pp(o.ci_pp?.[0])} to {pp(o.ci_pp?.[1])} points: we are 95% sure the true number is in here.
          </dd>
          <dt className="font-medium text-ink">Not messaged</dt>
          <dd className="text-ink-2">
            {held}% of customers, picked at random, whom Pheri deliberately left alone, so there is something to compare
            with. Everyone else Pheri followed up with.
          </dd>
          <dt className="font-medium text-ink">Why groups differ</dt>
          <dd className="text-ink-2">
            Each kind of customer orders at its own rate anyway (a customer waiting on a fix rarely orders on their own;
            a loyal one often does), so each has its own number, from {pp(Math.min(...lifts))} to{" "}
            {pp(Math.max(...lifts))}. The overall number is all of them combined, with bigger groups counting more.
          </dd>
        </dl>
        <p className="mt-4 text-[0.9rem] text-muted">
          {twin.customers.toLocaleString()} simulated customers who behave by fixed odds we set (maths, no model).
          Pheri sees each one only through its own journey rules, mistakes included, and learns what works over{" "}
          {orders ? `${twin.days} days` : `${twin.rounds} rounds`}.
        </p>
      </Card>

      <section aria-labelledby="stages">
        <h2 id="stages" className="text-[1.45rem] font-medium lg:text-[1.7rem]">Every kind of customer</h2>
        <p className="mt-1 max-w-[56rem] text-ink-2">
          Extra {unit} per 100 customers of each kind, with the likely range. The line marks zero; the further right,
          the more Pheri helped.
        </p>
        <Report learned={learned} unit={unit} />
        <ul className="mt-4 divide-y divide-line border-y border-line">
          {stages.map((s) => {
            const finding = learned.findings.find((f) => f.stage === s.stage);
            const small = s.holdout.n < SMALL_SAMPLE;
            return (
              <li key={s.stage} className="grid gap-x-6 gap-y-2 py-4 md:grid-cols-[13rem_1fr]">
                <div>
                  <p className="font-medium text-ink">
                    {stageLabel(s.stage)}{" "}
                    <span className={s.verdict === "works" ? "text-teal-ink" : "text-muted"}>
                      {s.verdict === "works" ? "✓ works" : s.verdict === "hurts" ? "✗ hurts" : "? not clear yet"}
                    </span>
                  </p>
                  <p className="text-[0.85rem] text-muted">
                    {s.treated.n.toLocaleString()} followed up · {s.holdout.n.toLocaleString()} not messaged
                    {small && <span className="block text-amber">fewer customers, so a wider range</span>}
                  </p>
                </div>
                <div className="min-w-0">
                  <p className="tabular-nums">
                    <span className="font-medium text-ink">{pp(s.lift_pp)} points</span>{" "}
                    <span className="text-[0.92rem] text-muted">
                      likely {pp(s.ci_pp![0])} to {pp(s.ci_pp![1])} · {pct(s.treated.rate)} vs {pct(s.holdout.rate)}
                    </span>
                  </p>
                  <div className="mt-1.5 max-w-[30rem]">
                    <RangeBar
                      lift={s.lift_pp!}
                      ci={s.ci_pp!}
                      domain={sharedDomain(stages.map((x) => x.ci_pp!))}
                      label={`${stageLabel(s.stage)}: ${pp(s.lift_pp)} points, likely ${pp(s.ci_pp![0])} to ${pp(s.ci_pp![1])}`}
                    />
                  </div>
                  {finding ? (
                    <p className="mt-2 text-[0.95rem] text-ink-2">{plainTwin(finding.text, unit)}</p>
                  ) : (
                    s.best_action && (
                      <p className="mt-2 text-[0.95rem] text-ink-2">Best so far: {actionLabel(s.best_action).toLowerCase()}.</p>
                    )
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        {learned.caveats.length > 0 && (
          <div className="mt-4 max-w-[56rem]">
            <Label>Keep in mind</Label>
            <ul className="mt-1.5 list-disc space-y-1 pl-5 text-[0.93rem] text-ink-2">
              {learned.caveats.map((c) => (
                <li key={c.text}>{plainTwin(c.text, unit)}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <Safe evals={evals} checked={checked} twin={twin} />
      <TourNext business={business} step={5} />
    </div>
  );
}

/** Who wrote the stage notes: Muse Wonder (recorded from a live run) or the offline stand-in; code checked it. */
function Report({ learned, unit }: { learned: Learned; unit: string }) {
  const wonder = learned.source !== "stand-in";
  return (
    <div className="mt-4 rounded-xl bg-sunk px-4 py-3 text-[0.95rem]">
      <p className="font-serif text-[1.12rem] leading-snug text-ink">&ldquo;{plainTwin(learned.headline, unit)}&rdquo;</p>
      <p className="mt-1.5 text-[0.88rem] text-muted">
        {wonder
          ? `What Pheri learned, written by Muse Wonder${learned.source === "recorded" ? " in a live run (recorded)" : ""}.`
          : "Written by the offline stand-in; the Muse Wonder report is a deliberate, budgeted run."}{" "}
        Code checked every number against the results before it was shown:{" "}
        {learned.attempts
          .map((a) => (a.passed ? `attempt ${a.attempt} passed` : `attempt ${a.attempt} rejected (${a.rejected.join(", ")})`))
          .join(", then ")}
        {learned.rejected.length ? `; rejected and left out: ${learned.rejected.map((r) => r.part).join(", ")}` : ""}.
      </p>
    </div>
  );
}

function Safe({ evals, checked, twin }: { evals: Evals; checked: VerificationTotals; twin: TwinResults }) {
  const open = evals.pipeline.baseten;
  const closed = evals.pipeline.meta;
  const harmful = open.harmful + closed.harmful;
  const j = evals.judge;
  const g = evals.guard;
  const m = twin.milestones;
  return (
    <section aria-labelledby="safe">
      <h2 id="safe" className="text-[1.45rem] font-medium lg:text-[1.7rem]">How we know it&rsquo;s safe and right</h2>
      <p className="mt-1 max-w-[56rem] text-ink-2">
        Measured once on {evals.messages} synthetic customer messages, some of them trying to trick Pheri, read live by both models and saved;
        these numbers come straight from those saved results.
      </p>

      <ol className="mt-5 space-y-8">
        <li className="grid gap-x-6 gap-y-1 md:grid-cols-[13rem_1fr]">
          <p className="font-serif text-[2rem] leading-none text-teal-ink">{harmful}</p>
          <div>
            <p className="font-medium text-ink">harmful things done because a message tried to trick Pheri</p>
            <p className="mt-1 text-[0.95rem] text-ink-2">
              Every trick message was run through the whole of Pheri (read, decide, check, send) with the word filter that
              runs before any AI switched off, so only the AI and the later checks stood in the way. On Meta&rsquo;s open
              model all {open.run} of{" "}
              {open.of}: {open.past_guard} got past the first reading, {open.sent} sent anything, {open.harmful} did harm. On
              Meta&rsquo;s hosted model, {closed.run} of {closed.of} (a partial run, stopped there by choice): {closed.past_guard} got past,{" "}
              {closed.sent} got an ordinary reply, {closed.harmful} did harm.
            </p>
          </div>
        </li>

        <li className="grid gap-x-6 gap-y-1 md:grid-cols-[13rem_1fr]">
          <p className="font-serif text-[2rem] leading-none text-teal-ink">
            {j.planted_caught.k}/{j.planted_caught.n}
          </p>
          <div>
            <p className="font-medium text-ink">invented claims caught by the judge, a second AI that checks each claim against the records</p>
            <p className="mt-1 text-[0.95rem] text-ink-2">
              {j.planted_caught.n} drafts with one false claim slipped in on purpose, which pass every code check, so only the
              judge could catch them ({range(j.planted_caught)}). It also let {j.supported_passed.k} of{" "}
              {j.supported_passed.n} true drafts through. In this demo&rsquo;s own night: {checked.drafts} drafts, code caught{" "}
              {checked.caught_by_code}, the judge {checked.caught_by_judge}, and nothing unchecked was ever sent.
            </p>
          </div>
        </li>

        <li>
          <p className="font-medium text-ink">Trick messages stopped, in the way each customer writes</p>
          <p className="mt-1 max-w-[56rem] text-[0.95rem] text-ink-2">
            Meta&rsquo;s hosted model (Muse Spark 1.3) and Meta&rsquo;s open model (Muse Spark Open), which a shop can run
            itself. Written the way people on the border write (Bhojpuri, Roman Nepali), the open model stops more.
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[34rem] text-[0.93rem]">
              <thead>
                <tr className="text-left text-[0.85rem] text-muted">
                  <th className="py-2 pr-4 font-normal">Written in</th>
                  <th className="py-2 pr-4 font-normal">Hosted model</th>
                  <th className="py-2 pr-4 font-normal">Open model</th>
                  <th className="py-2 font-normal">Messages understood correctly (hosted / open)</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {[...EVAL_LANGS, "all"].map((lang) => {
                  const c = g.meta[lang];
                  const op = g.baseten[lang];
                  const better = (op.attacks_stopped.rate ?? 0) > (c.attacks_stopped.rate ?? 0);
                  return (
                    <tr key={lang} className={`border-t border-line ${lang === "all" ? "font-medium" : ""}`}>
                      <td className="py-2 pr-4 text-ink">{lang === "all" ? "All" : LANGUAGE_NAME[lang] ?? lang}</td>
                      <td className="py-2 pr-4">
                        {c.attacks_stopped.k}/{c.attacks_stopped.n}{" "}
                        <span className="text-[0.82rem] text-muted">{range(c.attacks_stopped)}</span>
                      </td>
                      <td className={`py-2 pr-4 ${better ? "text-teal-ink" : ""}`}>
                        {op.attacks_stopped.k}/{op.attacks_stopped.n}{" "}
                        <span className="text-[0.82rem] text-muted">{range(op.attacks_stopped)}</span>
                      </td>
                      <td className="py-2 text-ink-2">
                        {pct(c.label.rate, 0)} / {pct(op.label.rate, 0)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[0.85rem] text-muted">
            Ranges are 95%: with 20 to 40 trick messages per language they are wide. Ordinary messages wrongly stopped:{" "}
            {g.meta.all.false_alarms.k} of {g.meta.all.false_alarms.n} (hosted), {g.baseten.all.false_alarms.k} of{" "}
            {g.baseten.all.false_alarms.n} (open).
          </p>
        </li>

        {m && (
          <li>
            <p className="font-medium text-ink">Learns from replies today, corrects with orders later</p>
            <p className="mt-1 max-w-[56rem] text-[0.95rem] text-ink-2">
              A reply comes on day {m.days.reply}, an order on day {m.days.order}, a reorder by day {m.days.reorder}. Pheri
              treats each reply as an early guess at an order and replaces the guess when the real order arrives, credited
              to the message that caused it.
              {twin.overall.reply_only_policy && (
                <>
                  {" "}Learning from replies alone would have won {pct(twin.overall.reply_only_policy.rate)} orders;
                  correcting with orders won {pct(twin.overall.treated.rate)}.
                </>
              )}
            </p>
            <MilestoneChart
              rows={[
                { label: "Replied", day: m.days.reply, treated: m.reply.treated.rate ?? 0, held: m.reply.holdout.rate ?? 0 },
                { label: "Ordered", day: m.days.order, treated: twin.overall.treated.rate ?? 0, held: twin.overall.holdout.rate ?? 0 },
                { label: "Reordered", day: m.days.reorder, treated: m.reorder.treated.rate ?? 0, held: m.reorder.holdout.rate ?? 0 },
              ]}
            />
            {(twin.corrections ?? []).length > 0 && (
              <ul className="mt-4 space-y-1 text-[0.92rem] text-ink-2">
                {(twin.corrections ?? []).map((c) => (
                  <li key={c.stage}>
                    <span className="text-ink">{stageLabel(c.stage)}:</span> replies pointed to &ldquo;
                    {actionLabel(c.replies_say).toLowerCase()}&rdquo;, orders to &ldquo;{actionLabel(c.orders_say).toLowerCase()}
                    &rdquo;
                    {c.settled_on_day !== null ? `; Pheri followed the orders by day ${c.settled_on_day}.` : "."}
                  </li>
                ))}
              </ul>
            )}
          </li>
        )}
      </ol>
    </section>
  );
}
