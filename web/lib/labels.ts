// What each action is called on screen.
export const ACTION_LABEL: Record<string, string> = {
  send_help: "Send help",
  book_call: "Offer a call",
  send_checkin: "Check in",
  offer_upgrade: "Suggest an upgrade",
  offer_discount: "Offer a discount",
  send_reminder: "Follow up on their question",
  recommend_product: "Recommend a product",
  offer_subscription: "Offer a subscription",
  offer_reorder: "Time to reorder",
  task_for_owner: "A task for you",
  no_action: "Nothing for now",
  escalate_to_human: "Escalated to you",
};

export const CHANNEL_LABEL: Record<string, string> = {
  email: "by email",
  in_app: "in the app",
  instagram_dm: "by Instagram DM",
  chat: "in chat",
  whatsapp: "on WhatsApp",
};

export const CHANNEL_NAME: Record<string, string> = {
  email: "email", in_app: "the app", instagram_dm: "Instagram", chat: "chat", whatsapp: "WhatsApp",
};

/** The HTML lang for a customer's words, so screen readers and fonts treat Devanagari right. */
export const langOf = (code: string | null | undefined) =>
  ({ ne: "ne", "ne-Latn": "ne-Latn", hi: "hi", bho: "bho", en: "en" } as Record<string, string>)[code ?? ""] ?? undefined;

export const STATUS_LABEL: Record<string, string> = {
  awaiting_approval: "Waiting for you",
  executed: "Done",
  approved: "Approved",
  rejected: "Rejected",
  blocked: "Blocked by a rule",
  suggested: "Suggested",
  scheduled: "Ready at 8:00",
};

export const actionLabel = (a: string | null | undefined) => (a ? ACTION_LABEL[a] ?? a.replaceAll("_", " ") : "");

// Facts and stages in plain words.
export const FACT_LABEL: Record<string, string> = {
  journey_stage: "journey stage",
  days_since_signup: "days since signup",
  days_quiet: "days quiet",
  failed_exports: "failed exports, all time",
  failed_exports_30d: "failed exports this month",
  seat_limit_hits_30d: "seat-limit hits this month",
  active_days_30d: "active days this month",
  active_days_prev_60d: "active days, 60 days before",
  usage_change_pct: "usage vs usual",
  open_tickets: "open tickets",
  price_complaints: "price complaints",
  renewal_in_days: "days to renewal",
  mrr_usd: "monthly revenue, $",
  plan: "plan",
  seats: "seats",
  country: "country",
  orders: "orders",
  total_spend_usd: "total spent, $",
  days_since_last_order: "days since last order",
  subscription: "subscription",
  gift_only: "only buys gifts",
  days_since_cart_abandoned: "days since cart left",
  town: "town",
  segment: "buys as",
  total_spend_npr: "total spent, Rs",
  last_order_items: "last order",
  usual_payment: "usually pays by",
  open_complaints: "orders with a problem",
  complaint_kind: "the problem",
  days_late: "days late",
  returns: "returns",
  cod_refusals: "cash on delivery refused",
  reorder_every_days: "reorders every (days)",
  festival_only: "only buys for festivals",
  days_since_enquiry: "days since they asked",
  next_festival: "next festival",
  days_to_next_festival: "days to the festival",
};

export const STAGE_LABEL: Record<string, string> = {
  onboarding: "Onboarding",
  stuck: "Stuck",
  quiet: "Quiet",
  healthy: "Healthy",
  expanding: "Expanding",
  at_risk_renewal: "At risk (renewal)",
  new: "New",
  loyal: "Loyal",
  wholesale: "Wholesale",
  festival: "Festival buyer",
  asked_no_order: "Asked, no order",
  gone_quiet: "Gone quiet",
  complaint: "Waiting on a fix",
};

export const factLabel = (f: string) => FACT_LABEL[f] ?? f.replaceAll("_", " ");
export const stageLabel = (s: string) => STAGE_LABEL[s] ?? s.replaceAll("_", " ");

// The code rule behind each stage (api/pheri/journey.py), in the owner's words. First match wins, in this order.
export const STAGE_RULE: Record<string, string> = {
  onboarding: "In their first 14 days.",
  stuck: "Exports failed this month.",
  at_risk_renewal: "Renewal within 30 days, and a price complaint or usage down 60% or more.",
  expanding: "Hit their seat limit this month.",
  quiet: "No activity at all this month.",
  healthy: "Everyone else: active, no warning signs.",
  complaint: "An order from the last 30 days is late, damaged, the wrong colour or waiting to be exchanged.",
  asked_no_order: "Sent a WhatsApp cart in the last 7 days and has not ordered since.",
  new: "Joined in the last 30 days.",
  festival: "Has only ever bought in the two weeks before a festival.",
  gone_quiet: "No order in the last 60 days.",
  wholesale: "A wholesale buyer who still orders.",
  loyal: "Everyone else: orders regularly.",
};

// Journey order, as a customer moves through it.
export const STAGE_ORDER: Record<string, string[]> = {
  brightdesk: ["onboarding", "healthy", "expanding", "stuck", "quiet", "at_risk_renewal"],
  birgunj: ["new", "asked_no_order", "loyal", "festival", "wholesale", "complaint", "gone_quiet"],
};

// The demo's hero customer (data/synth/brightdesk/_truth.json "hero"): shown first in her stage.
export const HERO: Record<string, string> = { brightdesk: "maya.okafor@pinecrest.example" };

/** A fact's value as a person reads it. */
export const factValue = (fact: string, v: unknown) => {
  if (v === null || v === undefined) return "—";
  if (fact === "usage_change_pct" && typeof v === "number") return `${v > 0 ? "+" : ""}${v}%`;
  if (fact === "journey_stage") return stageLabel(String(v));
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (v === "True" || v === "False") return v === "True" ? "yes" : "no"; // evidence values arrive as Python's text
  return String(v);
};

export const LANGUAGE_NAME: Record<string, string> = {
  ne: "Nepali", "ne-Latn": "Roman Nepali", hi: "Hindi", bho: "Bhojpuri", bh: "Bhojpuri", en: "English",
  es: "Spanish", pt: "Portuguese",
};

/** "07:30", in Nepal time, for the owner in Birgunj. */
export const clockNPT = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kathmandu" });
export const dayNPT = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kathmandu" });
