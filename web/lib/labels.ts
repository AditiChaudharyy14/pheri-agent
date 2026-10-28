// What each action is called on screen.
export const ACTION_LABEL: Record<string, string> = {
  send_help: "Send help",
  book_call: "Offer a call",
  send_checkin: "Check in",
  offer_upgrade: "Suggest an upgrade",
  offer_discount: "Offer a discount",
  send_reminder: "Remind about the cart",
  recommend_product: "Recommend a product",
  offer_subscription: "Offer a subscription",
  task_for_owner: "A task for you",
  no_action: "Nothing for now",
  escalate_to_human: "Escalated to you",
};

export const CHANNEL_LABEL: Record<string, string> = {
  email: "by email",
  in_app: "in the app",
  instagram_dm: "by Instagram DM",
  chat: "in chat",
};

export const STATUS_LABEL: Record<string, string> = {
  awaiting_approval: "Waiting for you",
  executed: "Done",
  approved: "Approved",
  rejected: "Rejected",
  blocked: "Blocked by a rule",
  suggested: "Suggested",
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
  usage_change_pct: "usage vs usual, %",
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
  subscriber: "Subscriber",
  lapsing: "Lapsing",
  cart_abandoner: "Left a cart",
  gift_buyer: "Gift buyer",
};

export const factLabel = (f: string) => FACT_LABEL[f] ?? f.replaceAll("_", " ");
export const stageLabel = (s: string) => STAGE_LABEL[s] ?? s.replaceAll("_", " ");
