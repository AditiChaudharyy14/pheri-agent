"""Customer twin: thousands of synthetic customers whose responses are maths, not a model.

    twin = population("brightdesk", n=200, seed=7)        # 5,000 for the full run (Sat 31 Oct)
    records = simulate(twin, policy=RandomPolicy())        # who got what, and who responded

Each twin customer has a hidden true stage, drawn from the stage mix of the business's synthetic data.
Pheri never sees it: it sees the stage its journey rules would assign, drawn from the journey
classifier's measured confusion matrix (so Pheri is wrong exactly as often as it really is). Whether
a customer responds depends only on the hidden stage and the action (RESPONSE below, the twin's
ground truth), or on the hidden stage alone for the holdout, who get no action.

The owner's rules apply here too: an action the rule check refuses is never offered (no discount for
anyone in their first month at Brightdesk). No LLM, no network, no spend.

Every draw comes from its own seeded stream (population, holdout, outcomes, policy), and each customer's
outcome is one uniform number fixed up front, so two policies run on the same twin meet the same luck.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from .actions import BUSINESS_ACTIONS, CATALOG, CHANNELS, ProposedAction
from .journey import STAGES, accuracy
from .rules import CheckContext, NoDiscountFirstDays, Rule, check
from .synth import COUNTRIES, NOW, OUT

HOLDOUT_SHARE = 0.20
ACTIONS = {b: tuple(a for a in acts if CATALOG[a].customer_facing) for b, acts in BUSINESS_ACTIONS.items()}

# The twin's ground truth: chance of a good outcome (renews, replies, buys again) within the window.
# Invented to be plausible, and hidden from the policy; the holdout gets BASELINE.
RESPONSE: dict[str, dict[str, dict[str, float]]] = {
    "brightdesk": {
        "onboarding":      {"send_help": .30, "book_call": .22, "send_checkin": .15, "offer_upgrade": .03, "offer_discount": .10},
        "stuck":           {"send_help": .38, "book_call": .26, "send_checkin": .08, "offer_upgrade": .02, "offer_discount": .14},
        "quiet":           {"send_help": .10, "book_call": .12, "send_checkin": .20, "offer_upgrade": .02, "offer_discount": .15},
        "healthy":         {"send_help": .05, "book_call": .06, "send_checkin": .06, "offer_upgrade": .12, "offer_discount": .08},
        "expanding":       {"send_help": .08, "book_call": .20, "send_checkin": .07, "offer_upgrade": .40, "offer_discount": .10},
        "at_risk_renewal": {"send_help": .12, "book_call": .32, "send_checkin": .10, "offer_upgrade": .03, "offer_discount": .28},
    },
    "kettle": {
        "new":            {"send_reminder": .05, "recommend_product": .25, "offer_subscription": .08, "offer_discount": .18, "send_checkin": .10},
        "loyal":          {"send_reminder": .04, "recommend_product": .30, "offer_subscription": .22, "offer_discount": .20, "send_checkin": .08},
        "subscriber":     {"send_reminder": .02, "recommend_product": .14, "offer_subscription": .01, "offer_discount": .10, "send_checkin": .12},
        "lapsing":        {"send_reminder": .08, "recommend_product": .12, "offer_subscription": .05, "offer_discount": .26, "send_checkin": .14},
        "cart_abandoner": {"send_reminder": .35, "recommend_product": .10, "offer_subscription": .03, "offer_discount": .30, "send_checkin": .06},
        "gift_buyer":     {"send_reminder": .04, "recommend_product": .22, "offer_subscription": .03, "offer_discount": .12, "send_checkin": .06},
    },
}
BASELINE = {
    "brightdesk": {"onboarding": .08, "stuck": .05, "quiet": .04, "healthy": .05, "expanding": .15, "at_risk_renewal": .10},
    "kettle": {"new": .07, "loyal": .20, "subscriber": .10, "lapsing": .04, "cart_abandoner": .12, "gift_buyer": .06},
}
# The rules the owner confirmed in the demo, as typed checks: the twin needs no model to compile them.
TWIN_RULES = {"brightdesk": [Rule("seed", "Never offer discounts in a customer's first month.",
                                  [NoDiscountFirstDays(days=30)])], "kettle": []}
NEW_STAGES = {"onboarding": (1, 13), "new": (1, 20)}  # days since signup; everyone else 20-700


@dataclass
class TwinCustomer:
    id: str
    hidden_stage: str  # the truth: drives the response, never shown to the policy
    seen_stage: str  # what Pheri's journey rules would say
    days_since_signup: int
    country: str
    holdout: bool
    luck: float  # the one uniform number that decides their outcome: responds if luck < chance
    round: int  # which round they arrive in

    def allowed(self, business: str, rules: list[Rule]) -> tuple[str, ...]:
        """The actions the owner's rules allow for this customer, checked in code like any other action."""
        ctx = CheckContext(business, {"days_since_signup": self.days_since_signup, "country": self.country}, NOW)
        out = []
        for a in ACTIONS[business]:
            proposed = ProposedAction(kind=a, channel=CHANNELS[business][0],
                                      discount_pct=10.0 if CATALOG[a].discount else None)
            if check(rules, proposed, ctx).allowed:
                out.append(a)
        return tuple(out)


@dataclass
class Twin:
    business: str
    customers: list[TwinCustomer]
    rounds: int
    seed: int
    rules: list[Rule] = field(default_factory=list)


@lru_cache(maxsize=None)
def stage_mix(business: str) -> dict[str, float]:
    """The hidden-stage mix of the business's synthetic customers (data/synth/<business>/_truth.json)."""
    truth = json.loads((OUT / business / "_truth.json").read_text(encoding="utf-8"))["stages"]
    counts = Counter(truth.values())
    return {s: counts[s] / sum(counts.values()) for s in STAGES[business]}


@lru_cache(maxsize=None)
def seen_given_hidden(business: str) -> dict[str, dict[str, float]]:
    """P(journey rules say s' | truly s), from the measured confusion matrix."""
    conf = accuracy(business).confusion
    out = {}
    for s in STAGES[business]:
        row = {p: conf[(s, p)] for p in STAGES[business]}
        total = sum(row.values())
        out[s] = {p: v / total for p, v in row.items()} if total else {s: 1.0}
    return out


def _pick(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def population(business: str, n: int = 200, rounds: int = 10, seed: int = 7,
               holdout_share: float = HOLDOUT_SHARE) -> Twin:
    pop = random.Random(f"{seed}:population")
    luck = random.Random(f"{seed}:outcomes")
    mix, seen = stage_mix(business), seen_given_hidden(business)
    customers = []
    for i in range(n):
        hidden = _pick(pop, mix)
        lo, hi = NEW_STAGES.get(hidden, (20, 700))
        customers.append(TwinCustomer(f"{business[:2]}-twin-{i:05d}", hidden, _pick(pop, seen[hidden]),
                                      pop.randint(lo, hi), pop.choice(COUNTRIES), False, luck.random(),
                                      i * rounds // n))
    # Exactly holdout_share of them, chosen on a stream of their own.
    for c in random.Random(f"{seed}:holdout").sample(customers, round(n * holdout_share)):
        c.holdout = True
    return Twin(business, customers, rounds, seed, TWIN_RULES[business])


@dataclass
class Record:
    customer: str
    round: int
    hidden_stage: str
    seen_stage: str
    holdout: bool
    action: str | None  # None: holdout, or no action the rules allow
    chance: float  # the true chance that applied (for checking the twin, never shown to the policy)
    responded: bool


class RandomPolicy:
    """Picks any allowed action at random: the floor every learning policy must beat."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(f"{seed}:random-policy")

    def choose(self, seen_stage: str, allowed: tuple[str, ...]) -> str:
        return self.rng.choice(allowed)

    def update(self, seen_stage: str, action: str, responded: bool) -> None:
        pass


def simulate(twin: Twin, policy) -> list[Record]:
    """Round by round: the policy picks for this round's treated customers, then learns from their outcomes."""
    b = twin.business
    records: list[Record] = []
    for r in range(twin.rounds):
        batch = [c for c in twin.customers if c.round == r]
        decided = []
        for c in batch:
            if c.holdout:
                chance = BASELINE[b][c.hidden_stage]
                records.append(Record(c.id, r, c.hidden_stage, c.seen_stage, True, None, chance, c.luck < chance))
                continue
            allowed = c.allowed(b, twin.rules)
            action = policy.choose(c.seen_stage, allowed) if allowed else None
            chance = RESPONSE[b][c.hidden_stage][action] if action else BASELINE[b][c.hidden_stage]
            rec = Record(c.id, r, c.hidden_stage, c.seen_stage, False, action, chance, c.luck < chance)
            records.append(rec)
            decided.append(rec)
        for rec in decided:  # outcomes arrive at the end of the round
            if rec.action:
                policy.update(rec.seen_stage, rec.action, rec.responded)
    return records
