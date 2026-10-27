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
