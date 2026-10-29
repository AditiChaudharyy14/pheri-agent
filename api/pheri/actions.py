"""What Pheri may do for a customer, per business. The model picks from this list; code checks the pick.

An action the catalog does not know, a channel the business does not use, or a discount on an action
that is not a discount is refused by `problems()` before any owner rule is even looked at.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


@dataclass(frozen=True)
class ActionType:
    kind: str
    description: str
    customer_facing: bool = True  # sends something to the customer (rules on channels and hours apply)
    discount: bool = False


CATALOG: dict[str, ActionType] = {a.kind: a for a in (
    ActionType("send_help", "Send help for a problem the customer reported: steps, a workaround, or the fix status."),
    ActionType("book_call", "Offer a short call with the team."),
    ActionType("send_checkin", "A short, friendly check-in."),
    ActionType("offer_upgrade", "Suggest more seats or a bigger plan."),
    ActionType("offer_discount", "Offer a discount, in percent off.", discount=True),
    ActionType("send_reminder", "Remind them about what they left in their cart."),
    ActionType("recommend_product", "Recommend a product that fits what they already buy."),
    ActionType("offer_subscription", "Invite them to a monthly subscription."),
    ActionType("offer_reorder", "Remind them it is about time to reorder, with what they bought last time."),
    ActionType("task_for_owner", "Ask the owner or the team to handle something by hand.", customer_facing=False),
    ActionType("no_action", "Do nothing now; say why.", customer_facing=False),
    # Created by code only (never offered to the model): a reply that looks like an attack goes to a person.
    ActionType("escalate_to_human", "A person reads this customer's message before Pheri does anything.",
               customer_facing=False),
)}
ESCALATE = "escalate_to_human"

BUSINESS_ACTIONS: dict[str, tuple[str, ...]] = {
    "brightdesk": ("send_help", "book_call", "send_checkin", "offer_upgrade", "offer_discount", "task_for_owner",
                   "no_action"),
    "birgunj": ("send_reminder", "recommend_product", "offer_reorder", "offer_discount", "send_help", "send_checkin",
                "task_for_owner", "no_action"),
}
CHANNELS: dict[str, tuple[str, ...]] = {
    "brightdesk": ("email", "in_app"),
    "birgunj": ("whatsapp", "instagram_dm"),
}
ALL_CHANNELS = ("email", "in_app", "instagram_dm", "chat", "sms", "whatsapp")


class ProposedAction(BaseModel):
    kind: str
    channel: str | None = None
    discount_pct: float | None = None
    message: str = ""
    send_at: datetime | None = None  # None: now

    @property
    def type(self) -> ActionType | None:
        return CATALOG.get(self.kind)


def problems(business: str, action: ProposedAction) -> list[str]:
    """Structural checks that hold for every business, whatever its owner's rules say."""
    if action.kind not in BUSINESS_ACTIONS[business]:
        return [f"{action.kind!r} is not an action {business} offers"]
    t = CATALOG[action.kind]
    out = []
    if t.customer_facing and action.channel not in CHANNELS[business]:
        out.append(f"channel {action.channel!r} is not one {business} uses ({', '.join(CHANNELS[business])})")
    if t.discount and not (action.discount_pct and 0 < action.discount_pct <= 100):
        out.append("a discount needs a percentage between 0 and 100")
    if not t.discount and action.discount_pct:
        out.append(f"{action.kind} cannot carry a discount: set discount_pct to null, or use offer_discount")
    return out
