// Typed access to the Pheri API (api/pheri/app.py). Server components call it directly; client components
// call /api/... on this origin, which app/api/[...path]/route.ts forwards to the API.

export const API_URL = process.env.PHERI_API_URL ?? "http://127.0.0.1:8000";

export const BUSINESSES = { birgunj: "Birgunj Saree Ghar", brightdesk: "Brightdesk" } as const;
export type Business = keyof typeof BUSINESSES;
export const isBusiness = (b: string): b is Business => b in BUSINESSES;

/** The visitor's sandbox id (proxy.ts sets the cookie); the API keys the public demo's state by it. */
export const SANDBOX_COOKIE = "pheri_sandbox";
export const SANDBOX_HEADER = "x-pheri-sandbox";

/** From a server component: the visitor's own sandbox, by their cookie. */
export async function api<T>(path: string): Promise<T> {
  const { cookies } = await import("next/headers");
  const id = (await cookies()).get(SANDBOX_COOKIE)?.value;
  const res = await fetch(`${API_URL}${path}`, { headers: id ? { [SANDBOX_HEADER]: id } : {} });
  if (!res.ok) throw new Error(`API ${res.status} on ${path}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

/** From the browser: same origin, forwarded to the API. */
export async function call<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: init?.method ?? "POST",
    headers: { "content-type": "application/json" },
    body: init?.body === undefined ? undefined : JSON.stringify(init.body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data?.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data as T;
}

export const customerPath = (b: string, key: string) => `/businesses/${b}/customers/${encodeURIComponent(key)}`;

// ---- shapes ---------------------------------------------------------------------------
export type Receipt =
  | { kind: "order"; ids: string[]; more: number }
  | { kind: "message"; channel: string | null; at: string | null; lang: string | null; from_staff: boolean }
  | { kind: "calendar"; name: string }
  | { kind: "activity" };
export type Evidence = { kind: "fact" | "quote"; ref: string; value: string; quote_id?: string; receipt?: Receipt | null };

export type Action = {
  id: string;
  customer_key: string;
  kind: string;
  payload: { channel?: string | null; discount_pct?: number | null; message?: string; reason?: string;
    verification?: StoredVerification };
  why: string;
  evidence: Evidence[];
  mode: "suggest" | "ask_owner" | "act_alone" | null;
  rule_check: { allowed: boolean; results: RuleResult[] };
  status: string;
  created_at: string;
  executed_at: string | null;
};

export type Approval = { id: string; action_id: string; decision: "pending" | "approved" | "rejected";
  decided_by: string | null; note: string | null };

export type Decision = { action: string; channel: string | null; discount_pct: number | null; message: string;
  why_this: string; why_now: string; fact_keys: string[]; quote_ids: string[] };

/** What the action stores: the send step sends it only if this passed for exactly this payload. */
export type StoredVerification = { passed: boolean; sha: string; caught_by: "code" | "judge" | null; reasons: string[];
  code_checks: number; judge_ran: boolean; failed: string[]; hard_failed?: string[]; soft_failed?: string[];
  overridable?: boolean; judge_flagged?: number; hard_reasons?: string[]; judge_summary?: string; summary?: string };

/** An owner sent a draft that failed only soft checks, on the record. */
export type Override = { by: string; at: string; overridden: string[]; reasons: string[]; text: string;
  channel: string | null; sha: string; summary: string; line: string; judge: string; logged_at: string };

/** "judge flagged 1 claim, one problem": what an override would send past (the API's override_summary). */
export const softSummary = (v: StoredVerification) =>
  (v.soft_failed ?? [])
    .map((c) =>
      c === "judge"
        ? v.judge_flagged
          ? `judge flagged ${v.judge_flagged} claim${v.judge_flagged === 1 ? "" : "s"}`
          : "the judge could not answer"
        : c.replaceAll("_", " "),
    )
    .join(", ");

/** One check in code, or the judge's verdict on one claim. */
export type CheckRow = { name: string; applies: boolean; passed: boolean; reasons: string[];
  scores?: { stage: string; class: string; stage_score: number; plan_score: number; threshold: number } };
export type JudgeRow = { claim_id: string; claim: string; supported: boolean; reason: string };
export type Verification = { passed: boolean; checks: CheckRow[]; judge: JudgeRow[]; judge_ran: boolean;
  caught_by: "code" | "judge" | null; reasons: string[]; code_checks: number; judge_model: string | null;
  judge_cost_usd: number; judge_recorded: boolean; judge_error: string | null };
export type Attempt = { attempt: number; decision: Decision; verification: Verification; turns: number[] };
/** The card's footer: "Verified: N code checks + judge", N counted by the API (verify.CODE_CHECKS). */
export type VerificationLine = { passed: boolean; code_checks: number; judge: boolean; caught_by: "code" | "judge" | null;
  reasons: string[]; attempts: number; judge_cost_usd: number; judge_recorded: boolean; hard_failed: string[];
  soft_failed: string[] };
export type VerificationTotals = { decisions: number; drafts: number; caught_by_code: number; caught_by_judge: number;
  retries: number; verified: number; sent_to_owner: number; judge_calls: number; by_check: Record<string, number>;
  first_try: number; code_checks: number };
export type MiddleStep = { thresholds: { money: number; nudge: number }; actions: string[];
  stages: { stage: string; customers: number; stage_score: number; fits: string[];
    plans: { action: string; class: "money" | "nudge"; plan_score: number; threshold: number; passed: boolean }[] }[] };

/** The model behind a decision, and how this server got its replies (stand-in: offline, never a model). */
export type DecidedBy = { provider: string; model: string; source: "live" | "recorded" | "stand-in" };

export type NextStep = {
  customer: { key: string; name: string; company: string | null; town?: string | null; stage: string };
  decision: Decision;
  evidence: Evidence[];
  action: Action | null;
  approval: Approval | null;
  skipped: string | null;
  fallback: string | null;
  unsupported_numbers: string[];
  message_problems: string[];
  private: boolean;
  cost_usd: number;
  turns: number;
  decided_by: DecidedBy | null;
  verification: VerificationLine | null;
  override: Override | null;
};

export type CustomerRow = { key: string; name: string; company: string | null; stage: string;
  because: { fact: string; value: unknown }[] };

export type Insight = { label?: string; quote: string; source_id: string; code?: string };
export type Profile = {
  business: string; customer_key: string; name: string; company: string | null;
  facts: Record<string, unknown>;
  insights: { goals: Insight[]; needs: Insight[]; blockers: Insight[]; role: Insight | null;
    sentiment: (Insight & { label: string }) | null; language: (Insight & { code: string }) | null };
  provenance: { facts: Record<string, string[]>; sources: string[]; dropped: unknown[] };
  model: string | null;
};

export type CustomerDetail = { key: string; name: string; company: string | null; facts: Record<string, unknown>;
  journey: { stage: string; because: { fact: string; value: unknown; refs: string[] }[] };
  do_not_contact: { at: string; source: string } | null };

export type RuleResult = { rule_id: string; check: string; passed: boolean; reason: string | null };
export type DiscountCheck = { allowed: boolean; violations: string[]; results: RuleResult[];
  refused_by: { rule_id: string; source_text: string | null; described: string[]; reason: string }[] };

export type RuleRow = { id: string; source_text: string; active: boolean; confirmed_by: string | null;
  confirmed_at: string | null; described: string[]; problems: string[]; unsupported: string[];
  confirmable?: boolean };

export type Reply = {
  source_id: string; kind: string; at: string | null; text: string;
  customer: { key: string; name: string; company: string | null };
  label: string; language: string; summary: string; attack: boolean; stop: boolean;
  screen_before: string[]; screen_after: string[]; provider: string | null; model: string | null;
  escalation: { id: string; status: string } | null;
};

export type RunsOn = { steps: Record<"guard" | "profile" | "decide" | "rules", { provider: string; model: string;
  label: string }>; full_private: boolean };

export type Group = { n: number; responded: number; rate: number | null };
export type StageResult = {
  stage: string; treated: Group; holdout: Group; lift_pp: number | null; ci_pp: [number, number] | null;
  verdict: "works" | "hurts" | "unclear"; best_action: string | null; runner_up: string | null;
  best_call: "clear" | "close call" | null;
  actions: { action: string; n: number; responded: number; rate: number | null; rate_ci: [number, number] | null;
    posterior_mean: number }[];
};
export type TwinResults = {
  business: string; customers: number; rounds: number; seed: number; holdout_share: number; min_tries: number;
  overall: Omit<StageResult, "stage" | "best_action" | "runner_up" | "best_call" | "actions"> & {
    random_policy?: Group; reply_only_policy?: Group };
  stages: StageResult[];
  learning_curve: { round: number; treated_rate: number; holdout_rate: number; best_pick_share: number | null }[];
  // Delayed outcomes (Birgunj): a reply on day 1, an order on day 3, a reorder by day 30.
  milestones?: { days: Record<string, number>; objective: string; reply: Lift; reorder: Lift };
  days?: number;
  corrections?: { stage: string; replies_say: string; orders_say: string; settled_on_day: number | null }[];
};

type Lift = { treated: Group; holdout: Group; lift_pp: number | null; ci_pp: [number, number] | null; verdict: string };

export type Learned = {
  source: "live" | "recorded" | "stand-in";
  headline: string;
  findings: { stage: string; verdict: string; text: string; fact_ids: string[] }[];
  caveats: { text: string; fact_ids: string[] }[];
  rejected: { part: string; text: string; problems: string[] }[];
  model: string | null; cost_usd: number; markdown: string;
  attempts: { attempt: number; passed: boolean; rejected: string[]; problems: string[] }[];
};

export type SpendRow = { provider: string; model: string; purpose: string; calls: number; usd: number;
  input_tokens: number; cached_tokens: number; output_tokens: number };
export type ProviderSpend = { settled_usd: number; reserved_usd?: number; offset_usd: number; cap_usd: number;
  remaining_usd: number };
export type Spend = { mode: string; as_of: string; max_call_usd: number; providers: Record<string, ProviderSpend>;
  by_purpose: SpendRow[]; live_runs: { as_of: string; providers: Record<string, ProviderSpend>; calls: SpendRow[] } | null };

// ---- words for people ---------------------------------------------------------------------
export const words = (s: string | null | undefined) => (s ?? "").replaceAll("_", " ");
export const MODE_LABEL: Record<string, string> = { suggest: "Suggest", ask_owner: "Ask owner", act_alone: "Act alone" };
export const pct = (r: number | null | undefined, digits = 1) => (r == null ? "—" : `${(100 * r).toFixed(digits)}%`);
export const pp = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`);
export const usd = (v: number) => `$${v.toFixed(4)}`;

export type NextStepWithTime = NextStep & { sends_at_local?: string | null; waits_for_owner?: string | null;
  owner_options?: string[]; owner_choice?: string | null };
export type Brief = {
  night: string; morning: string;
  read: { messages: number; by_language: Record<string, number>; voice_notes: { read: number; unreadable: number } };
  customers: number;
  scheduled: NextStepWithTime[]; sent: NextStepWithTime[]; need_you: NextStepWithTime[]; blocked: NextStepWithTime[];
  stopped: (Reply & { holding_reply?: HoldingReply | null })[];
  unreadable_voice: { customer: string; name: string; lang: string; says: string }[];
  voice_stand_in: boolean;
  proof: { treated: number; holdout: number; lift_pp: number; ci_pp: [number, number]; verdict: string; customers: number;
           outcome: string } | null;
  public_demo: boolean; mode: string;
  rule_moments: { customer: { key: string; name: string }; rule: string; refused: string | null; then: string }[];
  timeline: NightEvent[];
};
export type DraftStep = { attempt: number; passed: boolean; caught_by: string | null; reasons: string[] };
export type NightEvent = {
  at: string | null; customer: { key: string; name: string; town?: string | null; stage: string }; lang: string | null;
  kind: string; text: string; voice: string | null; outcome: string; action: string; sends_at_local: string | null;
  waits_for_owner: string | null; drafts: DraftStep[]; holding_reply?: HoldingReply | null;
};
/** The fixed reply, written by code (never a model), that a customer whose message looked like an attack gets. */
export type HoldingReply = { message: string; language: string | null; status: string; sends_at_local: string | null;
  checks: number | null };
export type SlopSentence = { text: string; struck: boolean; reasons: string[] };
export type Slop = {
  customer: { key: string; name: string; stage: string };
  plain: { text: string; model: string; recorded: boolean; sentences: SlopSentence[]; whole_draft: string[];
           failed: { check: string; hard: boolean; plain: string; detail: string }[]; passed: boolean };
  pheri: NextStepWithTime;
};
