import Link from "next/link";
import { Suspense } from "react";
import { EvidenceChips } from "@/components/evidence";
import { Badge, Card, Label, ModeBadge, Skeleton } from "@/components/ui";
import { type Attempt, api, customerPath, MODE_LABEL, type NextStep, usd, type Verification } from "@/lib/api";
import { actionLabel, STATUS_LABEL } from "@/lib/labels";

type Part = { kind: string; text?: string; data?: Record<string, unknown>; tool?: string; output?: unknown;
  arguments?: unknown; decision?: Record<string, unknown>; incomplete?: string | null; discarded?: boolean };
type Turn = { turn: number; attempt?: number; sent: Part[]; got: Part[]; usage: { provider: string; model: string;
  input_tokens: number; cached_tokens: number; output_tokens: number; reasoning_tokens: number | null; cost_usd: number } };
type Trace = NextStep & { turns: Turn[]; prechecks: { action: string; allowed: boolean; violations: string[] }[];
  dropped_evidence: { ref: string; reason: string }[]; attempts: Attempt[]; final_verification: Verification | null;
  discarded_tools: string[] };

const CHECK_LABEL: Record<string, string> = {
  rules: "The owner's rules",
  schema: "Every field a draft needs",
  evidence: "Cites real facts",
  facts: "Numbers, dates and plans are in the facts it cites",
  pronouns: "No pronoun the customer never gave",
  address: "Says \u201cyou\u201d, name only in the greeting",
  one_problem: "Leads with one problem",
  language: "In the customer's language",
  length: "Short",
  links: "Links only to the business's sites",
  money: "No money offer unless a rule allows it",
  middle_step: "Stage and plan pass the bar",
};
type Params = PageProps<"/[business]/customers/[key]/trace">["params"];

export default function TracePage({ params }: PageProps<"/[business]/customers/[key]/trace">) {
  return (
    <Suspense fallback={<Skeleton rows={4} />}>
      <TraceView params={params} />
    </Suspense>
  );
}

async function TraceView({ params }: { params: Params }) {
  const { business, key: raw } = await params;
  const key = decodeURIComponent(raw);
  const t = await api<Trace>(`${customerPath(business, key)}/trace`);
  const tokens = t.turns.reduce((n, x) => n + x.usage.input_tokens + x.usage.output_tokens, 0);
  const model = t.turns[0]?.usage;
  return (
    <>
      <header className="mb-8">
        <Link href={`/${business}/customers/${encodeURIComponent(key)}`} className="text-[0.92rem] text-muted hover:text-teal-ink">
          ← {t.customer.name}
        </Link>
        <h1 className="mt-2 text-[2.6rem] leading-tight font-medium">Decision trace</h1>
        <p className="mt-2 max-w-3xl text-[1.1rem] leading-relaxed text-ink-2">
          How Pheri reached the next step for {t.customer.name}: every turn of the agent&rsquo;s loop, then everything code
          did with the answer before anything could happen.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Badge tone="ink">{t.turns.length} turns</Badge>
          {model && <Badge>{model.provider === "baseten" ? "Muse Spark Open" : model.model === "muse-spark-1.3" ? "Muse Spark 1.3" : model.model}</Badge>}
          {model && <Badge>{model.provider === "baseten" ? "Baseten (private)" : "Meta Model API"}</Badge>}
          {t.decided_by?.source === "recorded" && (
            <Badge tone="teal" title="Every reply below is what the model said in a live run, replayed; code ran again now">
              Recorded from a live run
            </Badge>
          )}
          {t.decided_by?.source === "stand-in" && (
            <Badge tone="amber" title="Offline: no model was called; the stand-in follows the same loop">Offline stand-in</Badge>
          )}
          <Badge>{tokens.toLocaleString()} tokens</Badge>
          <Badge>cost {usd(t.cost_usd)}</Badge>
        </div>
      </header>

      {t.attempts.length > 0 ? (
        <ol className="space-y-10">
          {t.attempts.map((a) => (
            <li key={a.attempt}>
              <DraftHeader attempt={a} total={t.attempts.length} />
              <ol className="mt-4 space-y-5">
                {t.turns
                  .filter((turn) => (turn.attempt ?? 1) === a.attempt)
                  .map((turn) => (
                    <li key={turn.turn}>
                      <TurnCard turn={turn} />
                    </li>
                  ))}
              </ol>
              <VerificationPanel v={a.verification} />
            </li>
          ))}
        </ol>
      ) : (
        <ol className="space-y-5">
          {t.turns.map((turn) => (
            <li key={turn.turn}>
              <TurnCard turn={turn} />
            </li>
          ))}
        </ol>
      )}

      <h2 className="mt-12 mb-5 text-[1.9rem] font-medium">What code did with the answer</h2>
      <div className="grid grid-cols-2 gap-6">
        <Card>
          <Step n={1} title="Attach the evidence">
            The model picked facts and quotes by id; code filled in the real values.
          </Step>
          <div className="mt-4">
            <EvidenceChips evidence={t.evidence} />
          </div>
          {t.dropped_evidence.length > 0 && (
            <p className="mt-3 text-[0.92rem] text-amber">Dropped: {t.dropped_evidence.map((d) => d.reason).join("; ")}</p>
          )}
        </Card>
        <Card>
          <Step n={2} title="Verify the draft, again, in the send step">
            submit() runs the checks itself, whatever happened in the loop; the send step sends only the exact message
            that passed.
          </Step>
          <ul className="mt-4 space-y-2">
            {t.override && (
              <li className="rounded-lg bg-amber-soft px-3 py-2 text-[0.93rem] text-amber">
                {t.override.line}. {t.override.by} read it and sent it anyway at{" "}
                {t.override.at.replace("T", " ").slice(0, 16)}; the audit log holds the exact text and every reason.
              </li>
            )}
            {t.final_verification ? (
              <>
                <Check ok={t.final_verification.passed}>
                  {t.final_verification.passed
                    ? `${t.final_verification.code_checks} code checks passed${t.final_verification.judge_ran ? `, and the judge supported all ${t.final_verification.judge.length} claims` : ""}`
                    : t.action?.payload.verification?.overridable
                      ? `Not verified (caught by ${t.final_verification.caught_by}): only soft checks failed, so only you can send it`
                      : `Not verified (caught by ${t.final_verification.caught_by}): a hard check failed, so no one can send it`}
                </Check>
                {t.discarded_tools.length > 0 && (
                  <Check ok={false}>Tool calls discarded and logged: {t.discarded_tools.join(", ")}</Check>
                )}
              </>
            ) : (
              <li className="text-muted">No draft: nothing to verify.</li>
            )}
          </ul>
        </Card>
        <Card>
          <Step n={3} title="Check the owner's rules again">
            Whatever check_rules said in the loop, code checks the final action itself.
          </Step>
          <ul className="mt-4 space-y-2">
            {(t.action?.rule_check.results ?? []).map((r) => (
              <Check key={r.rule_id + r.check} ok={r.passed}>
                <span className="font-mono text-[0.85rem]">{r.check}</span> {r.passed ? "passed" : r.reason}
              </Check>
            ))}
            {!t.action && <li className="text-muted">No action: nothing to check.</li>}
          </ul>
        </Card>
        <Card>
          <Step n={4} title="Route it through the autonomy dial">
            The owner chose, per action type, whether Pheri suggests, asks, or acts.
          </Step>
          <div className="mt-4 flex items-center gap-3">
            <span className="text-[1.15rem] font-semibold text-teal-ink">{actionLabel(t.decision.action)}</span>
            <ModeBadge mode={t.action?.mode} />
          </div>
          <p className="mt-2 text-ink-2">
            {t.action
              ? `${MODE_LABEL[t.action.mode ?? ""] ?? "No mode"}: ${STATUS_LABEL[t.action.status] ?? t.action.status}.`
              : "Nothing to route."}
          </p>
        </Card>
      </div>
    </>
  );
}

function DraftHeader({ attempt, total }: { attempt: Attempt; total: number }) {
  const v = attempt.verification;
  const failed = v.checks.filter((c) => c.applies && !c.passed).map((c) => c.name.replaceAll("_", " "));
  return (
    <div className="flex flex-wrap items-baseline gap-3">
      <h2 className="text-[1.6rem] font-medium">
        Draft {attempt.attempt}
        {total > 1 && <span className="text-muted"> of {total}</span>}
      </h2>
      {v.passed ? (
        <Badge tone="teal">
          ✓ Passed: {v.code_checks} code checks{v.judge_ran ? " + judge" : ""}
        </Badge>
      ) : v.caught_by === "code" ? (
        <Badge tone="rose">✗ Caught by code: {failed.join(", ")}</Badge>
      ) : (
        <Badge tone="rose">✗ Caught by the judge{v.judge_error ? ": could not answer" : ""}</Badge>
      )}
    </div>
  );
}

function VerificationPanel({ v }: { v: Verification }) {
  return (
    <section className="mt-5 grid grid-cols-2 gap-6 rounded-2xl border border-line bg-paper/60 px-7 py-5">
      <div>
        <Label>Layer 1 · code checks, before anything else</Label>
        <ul className="mt-3 space-y-1.5">
          {v.checks.map((c) => (
            <li key={c.name} className="text-[0.93rem]">
              <span className="flex items-baseline gap-2">
                <span className={!c.applies ? "text-muted" : c.passed ? "text-teal" : "text-rose"}>
                  {!c.applies ? "–" : c.passed ? "✓" : "✗"}
                </span>
                <span className={c.applies ? "text-ink" : "text-muted"}>
                  {CHECK_LABEL[c.name] ?? c.name}
                  {!c.applies && " (does not apply)"}
                  {c.scores && (
                    <span className="ml-2 text-[0.82rem] text-muted">
                      stage {Math.round(c.scores.stage_score * 100)}% · plan {Math.round(c.scores.plan_score * 100)}% ·
                      a {c.scores.class} needs {Math.round(c.scores.threshold * 100)}%
                    </span>
                  )}
                </span>
              </span>
              {c.reasons.map((r) => (
                <span key={r} className="mt-0.5 ml-5 block text-[0.86rem] text-rose">
                  {r}
                </span>
              ))}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <Label>Layer 2 · the judge, Muse Spark Open</Label>
        {!v.judge_ran && !v.judge_error && (
          <p className="mt-3 text-[0.93rem] text-muted">Not asked: code caught this draft first, at no cost.</p>
        )}
        {v.judge_error && <p className="mt-3 text-[0.93rem] text-rose">{v.judge_error}: a person checks it.</p>}
        {v.judge_ran && (
          <>
            <p className="mt-2 text-[0.85rem] text-muted">
              &ldquo;Is this claim supported by the cited facts?&rdquo; · {usd(v.judge_cost_usd)}
              {v.judge_recorded ? " · recorded from a live run" : ""}
            </p>
            <ul className="mt-3 space-y-2">
              {v.judge.map((j) => (
                <li key={j.claim_id} className="text-[0.93rem]">
                  <span className="flex items-baseline gap-2">
                    <span className={j.supported ? "text-teal" : "text-rose"}>{j.supported ? "✓" : "✗"}</span>
                    <span className="text-ink-2">&ldquo;{j.claim}&rdquo;</span>
                  </span>
                  <span className={`ml-5 block text-[0.84rem] ${j.supported ? "text-muted" : "text-rose"}`}>{j.reason}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}

function TurnCard({ turn }: { turn: Turn }) {
  const u = turn.usage;
  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-surface">
      <div className="flex items-baseline justify-between border-b border-line px-7 py-4">
        <h2 className="text-[1.35rem] font-medium">Turn {turn.turn}</h2>
        <span className="text-[0.85rem] text-muted">
          {u.input_tokens.toLocaleString()} in · {u.output_tokens.toLocaleString()} out
          {u.reasoning_tokens != null ? ` (${u.reasoning_tokens} reasoning)` : ""} · {usd(u.cost_usd)}
        </span>
      </div>
      <div className="grid grid-cols-2 divide-x divide-line">
        <div className="px-7 py-5">
          <Label>Sent to the model</Label>
          <div className="mt-3 space-y-3">
            {turn.sent.map((p, i) => (
              <SentPart key={i} part={p} />
            ))}
          </div>
        </div>
        <div className="bg-paper/60 px-7 py-5">
          <Label>The model</Label>
          <div className="mt-3 space-y-3">
            {turn.got.map((p, i) => (
              <GotPart key={i} part={p} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function SentPart({ part }: { part: Part }) {
  if (part.kind === "instructions")
    return <Details summary="Instructions (the system prompt)" body={part.text ?? ""} />;
  if (part.kind === "brief")
    return <Details summary={`The brief: ${Object.keys(part.data ?? {}).join(", ")}`} body={JSON.stringify(part.data, null, 2)} />;
  if (part.kind === "nudge") return <p className="text-amber">Nudge: {part.text}</p>;
  if (part.kind === "feedback")
    return (
      <div className="rounded-lg bg-amber-soft px-3 py-2">
        <p className="text-[0.85rem] font-medium text-amber">Code&rsquo;s reasons, sent back to the model</p>
        <pre className="mt-1 font-sans text-[0.86rem] leading-relaxed whitespace-pre-wrap text-ink-2">{part.text}</pre>
      </div>
    );
  if (part.kind === "tool_result") {
    const out = part.output as Record<string, unknown>;
    if (part.tool === "check_rules")
      return (
        <div className={`rounded-lg px-3 py-2 ${out.allowed ? "bg-teal-soft" : "bg-rose-soft"}`}>
          <span className="font-mono text-[0.85rem] text-muted">check_rules</span>{" "}
          <span className="font-medium">{actionLabel(String(out.action))}</span>{" "}
          {out.allowed ? (
            <span className="text-teal-ink">allowed</span>
          ) : (
            <span className="text-rose">refused: {(out.violations as string[]).join("; ")}</span>
          )}
        </div>
      );
    return <Details summary={`${part.tool} returned ${summarize(part.tool, out)}`} body={JSON.stringify(out, null, 2)} />;
  }
  return null;
}

function GotPart({ part }: { part: Part }) {
  if (part.kind === "tool_call" && part.discarded)
    return (
      <p className="text-rose">
        Called <span className="font-mono text-[0.92rem]">{part.tool}</span>: not one of its tools, so the call was
        discarded and logged
      </p>
    );
  if (part.kind === "tool_call")
    return (
      <p>
        Called <span className="font-mono text-[0.92rem] text-teal-ink">{part.tool}</span>
        {part.arguments != null && Object.keys(part.arguments as object).length > 0 && (
          <span className="mt-1 block font-mono text-[0.82rem] break-all text-muted">{JSON.stringify(part.arguments)}</span>
        )}
      </p>
    );
  if (part.kind === "answer") {
    const d = part.decision ?? {};
    return (
      <div>
        <p>
          Answered: <span className="font-semibold text-teal-ink">{actionLabel(String(d.action))}</span>
        </p>
        <p className="mt-2 text-[0.95rem] text-ink-2">{String(d.why_this)}</p>
        <p className="mt-2 font-mono text-[0.8rem] break-all text-muted">
          fact_keys {JSON.stringify(d.fact_keys)} · quote_ids {JSON.stringify(d.quote_ids)}
        </p>
      </div>
    );
  }
  return (
    <p className="text-amber">
      Wrote text, not the decision{part.incomplete ? ` (cut off: ${part.incomplete})` : ""}: {part.text}
    </p>
  );
}

function summarize(tool: string | undefined, out: Record<string, unknown>) {
  if (tool === "get_profile") {
    const facts = Object.keys((out.facts as object) ?? {}).length;
    const stage = (out.journey as { stage?: string })?.stage;
    return `the profile: ${facts} facts, stage ${stage?.replaceAll("_", " ")}`;
  }
  if (tool === "list_allowed_actions") {
    const actions = (out.actions as unknown[])?.length ?? 0;
    const rules = (out.owner_rules as string[]) ?? [];
    return `${actions} actions and ${rules.length} owner rule${rules.length === 1 ? "" : "s"}`;
  }
  return "a result";
}

function Details({ summary, body }: { summary: string; body: string }) {
  return (
    <details className="group rounded-lg border border-line bg-surface">
      <summary className="cursor-pointer list-none px-3 py-2 text-ink-2 marker:hidden group-open:border-b group-open:border-line">
        <span className="mr-2 text-muted group-open:hidden">▸</span>
        <span className="mr-2 hidden text-muted group-open:inline">▾</span>
        {summary}
      </summary>
      <pre className="max-h-72 overflow-auto px-3 py-2 font-mono text-[0.76rem] leading-relaxed whitespace-pre-wrap text-ink-2">
        {body}
      </pre>
    </details>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-baseline gap-3">
        <span className="font-serif text-[1.6rem] leading-none text-teal">{n}</span>
        <h3 className="text-[1.25rem] font-medium">{title}</h3>
      </div>
      <p className="mt-1.5 text-[0.95rem] text-ink-2">{children}</p>
    </div>
  );
}

function Check({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-baseline gap-2">
      <span className={ok ? "text-teal" : "text-rose"} aria-label={ok ? "passed" : "failed"}>
        {ok ? "✓" : "✗"}
      </span>
      <span className="text-ink">{children}</span>
    </li>
  );
}
