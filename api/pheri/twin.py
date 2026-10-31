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

import dataclasses
import json
import random
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from .actions import BUSINESS_ACTIONS, CATALOG, CHANNELS, REACTIVE_ACTIONS, ProposedAction
from .journey import STAGES, accuracy
from .rules import CheckContext, NoDiscountFirstDays, Rule, check
from .synth import COUNTRIES, NOW, OUT

HOLDOUT_SHARE = 0.20
ACTIONS = {b: tuple(a for a in acts if CATALOG[a].customer_facing and a not in REACTIVE_ACTIONS)
           for b, acts in BUSINESS_ACTIONS.items()}

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
    # Birgunj: the chance of an order within the window. Fixing a complaint is what brings a complainer back;
    # a reorder nudge works for people with a rhythm; festival buyers want to see the new collection.
    "birgunj": {
        "new":            {"send_reminder": .06, "recommend_product": .22, "offer_reorder": .04, "offer_discount": .16, "send_help": .05, "send_checkin": .10},
        "loyal":          {"send_reminder": .04, "recommend_product": .26, "offer_reorder": .30, "offer_discount": .18, "send_help": .03, "send_checkin": .08},
        "wholesale":      {"send_reminder": .03, "recommend_product": .12, "offer_reorder": .38, "offer_discount": .20, "send_help": .04, "send_checkin": .10},
        "festival":       {"send_reminder": .05, "recommend_product": .34, "offer_reorder": .10, "offer_discount": .24, "send_help": .03, "send_checkin": .07},
        "asked_no_order": {"send_reminder": .32, "recommend_product": .12, "offer_reorder": .03, "offer_discount": .26, "send_help": .08, "send_checkin": .06},
        "gone_quiet":     {"send_reminder": .05, "recommend_product": .12, "offer_reorder": .08, "offer_discount": .22, "send_help": .04, "send_checkin": .14},
        "complaint":      {"send_reminder": .02, "recommend_product": .03, "offer_reorder": .02, "offer_discount": .10, "send_help": .40, "send_checkin": .06},
    },
}
BASELINE = {
    "brightdesk": {"onboarding": .08, "stuck": .05, "quiet": .04, "healthy": .05, "expanding": .15, "at_risk_renewal": .10},
    "birgunj": {"new": .06, "loyal": .18, "wholesale": .20, "festival": .08, "asked_no_order": .10, "gone_quiet": .03,
                "complaint": .05},
}
PLAN_FIT = 0.5  # a plan fits a stage when its lift over the baseline is at least half the best action's lift


def fitting_plans(business: str) -> dict[str, list[str]]:
    """Per true stage, the actions that fit it: the labelled plans the middle-step check scores against
    (written into _truth.json by synth.py)."""
    out = {}
    for s, row in RESPONSE[business].items():
        lift = {a: r - BASELINE[business][s] for a, r in row.items()}
        best = max(lift.values())
        out[s] = [a for a, x in lift.items() if x > 0 and x >= PLAN_FIT * best]
    return out


# The rules the owner confirmed in the demo, as typed checks: the twin needs no model to compile them.
TWIN_RULES = {"brightdesk": [Rule("seed", "Never offer discounts in a customer's first month.",
                                  [NoDiscountFirstDays(days=30)])], "birgunj": []}
NEW_STAGES = {"onboarding": (1, 13), "new": (1, 25)}  # days since signup; everyone else 20-700


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
    world: dict = field(default_factory=dict)  # milestone twins: their hidden profile from the shop's world
    lucks: dict = field(default_factory=dict)  # milestone twins: one more luck per early or later milestone
    day: int = 0  # milestone twins: the day they arrive

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
    responded: bool  # milestone twins: ordered (the objective)
    replied: bool | None = None  # milestone twins only, from here on
    reordered: bool | None = None
    day: int | None = None
    decision_id: str | None = None


class RandomPolicy:
    """Picks any allowed action at random: the floor every learning policy must beat."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(f"{seed}:random-policy")

    def choose(self, seen_stage: str, allowed: tuple[str, ...]) -> str:
        return self.rng.choice(allowed)

    def update(self, seen_stage: str, action: str, responded: bool) -> None:
        pass

    def observe(self, event) -> None:
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


# ---- Thompson sampling ---------------------------------------------------------------
# A little exploration: before Thompson exploits, each action in a stage gets EXPLORE_SHARE of its even share
# of the customers (5,000 customers, 6 stages x 5 actions: 20 tries; 1,000: 4; 200: 1). A fixed number
# would not be "a little" at every size: 20 tries per action is every customer at 200. Swept at 5,000 over
# five seeds per business: 20 fixed the Brightdesk healthy miss (seed 7) for 0.2 points of response
# (21.5% -> 21.3%); more cost far more (60: 18.5%, 100: 15.6%) and did not raise the share of stages
# learned right (about 52/60 at every setting: the misses left are close calls, the runner-up 0.04-0.05
# behind the best).
EXPLORE_SHARE = 0.12


def min_tries_for(business: str, n: int) -> int:
    return max(1, round(EXPLORE_SHARE * n / (len(STAGES[business]) * len(ACTIONS[business]))))


class ThompsonPolicy:
    """One Beta(1, 1) prior per seen stage x action. For each customer it draws once from every allowed
    action's posterior and picks the highest draw; outcomes update the posteriors at the end of a round.

    min_tries: until every allowed action has been tried that many times in a stage, the least-tried one
    goes first. Tries count when an action is given, not when its result comes back, so one round's
    customers spread over the untried actions. Without it, one unlucky start can starve the best action
    (seen: Brightdesk healthy at 5,000, offer_upgrade 8 of 131, settled on the second-best discount)."""

    def __init__(self, seed: int = 0, min_tries: int = 0):
        self.rng = random.Random(f"{seed}:thompson")
        self.ab: dict[tuple[str, str], list[int]] = {}
        self.tries: dict[tuple[str, str], int] = {}
        self.min_tries = min_tries

    def _beta(self, stage: str, action: str) -> list[int]:
        return self.ab.setdefault((stage, action), [1, 1])

    def choose(self, seen_stage: str, allowed: tuple[str, ...]) -> str:
        fewest = min(self.tries.get((seen_stage, a), 0) for a in allowed)
        if fewest < self.min_tries:
            pick = self.rng.choice([a for a in allowed if self.tries.get((seen_stage, a), 0) == fewest])
        else:
            pick = max(allowed, key=lambda a: self.rng.betavariate(*self._beta(seen_stage, a)))
        self.tries[(seen_stage, pick)] = self.tries.get((seen_stage, pick), 0) + 1
        return pick

    def update(self, seen_stage: str, action: str, responded: bool) -> None:
        self._beta(seen_stage, action)[0 if responded else 1] += 1

    def posterior_mean(self, stage: str, action: str) -> float:
        a, b = self._beta(stage, action)
        return a / (a + b)


# ---- lift vs holdout ------------------------------------------------------------------
Z95 = 1.96


def lift_ci(k1: int, n1: int, k0: int, n0: int) -> tuple[float, float, float] | None:
    """(lift, low, high) in percentage points: treated rate minus holdout rate, 95% normal interval."""
    if not n1 or not n0:
        return None
    p1, p0 = k1 / n1, k0 / n0
    se = (p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0) ** 0.5
    return round(100 * (p1 - p0), 1), round(100 * (p1 - p0 - Z95 * se), 1), round(100 * (p1 - p0 + Z95 * se), 1)


def wilson(k: int, n: int) -> list[float] | None:
    """95% interval for one rate; sensible for small n and for 0 or n successes."""
    if not n:
        return None
    p, z2 = k / n, Z95 ** 2
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = Z95 * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5) / (1 + z2 / n)
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def verdict(ci: tuple[float, float, float] | None) -> str:
    """Decided in code, so a report can never call something that is not clear a win."""
    if ci is None:
        return "unclear"
    return "works" if ci[1] > 0 else "hurts" if ci[2] < 0 else "unclear"


def best_call(tried: list[dict]) -> str | None:
    """'close call' when the 95% interval of the difference between the best action and the runner-up
    includes zero: the data cannot yet say which of the two is better. 'clear' otherwise; None when
    nothing was tried. The difference interval, not "do the two rates' intervals overlap": at 5,000
    customers overlap called 11 of 12 stages close (the runner-up's few tries make its interval wide),
    including Brightdesk stuck, whose true gap is 0.24; the difference called 5, all with true gaps of
    0.04-0.08, and every stage it called clear was."""
    if not tried:
        return None
    if len(tried) == 1:
        return "clear"
    top, run = tried[0], tried[1]
    diff = lift_ci(top["responded"], top["n"], run["responded"], run["n"])
    return "clear" if diff and diff[1] > 0 else "close call"


def _group(records: list[Record]) -> dict:
    n, k = len(records), sum(r.responded for r in records)
    return {"n": n, "responded": k, "rate": round(k / n, 4) if n else None}


def _lift(treated: list[Record], holdout: list[Record]) -> dict:
    t, h = _group(treated), _group(holdout)
    ci = lift_ci(t["responded"], t["n"], h["responded"], h["n"])
    return {"treated": t, "holdout": h, "lift_pp": ci[0] if ci else None, "ci_pp": [ci[1], ci[2]] if ci else None,
            "verdict": verdict(ci)}


def _true_best(business: str, hidden: str, allowed: tuple[str, ...]) -> str | None:
    return max(allowed, key=lambda a: RESPONSE[business][hidden][a]) if allowed else None


def report(twin: Twin, records: list[Record], policy: ThompsonPolicy,
           random_records: list[Record] | None = None) -> dict:
    """The chart-ready results: overall and per seen stage lift with 95% intervals, what the policy learned per
    stage x action, the learning curve, and (labelled) the twin's hidden truth for comparison."""
    b = twin.business
    treated = [r for r in records if not r.holdout]
    holdout = [r for r in records if r.holdout]
    stages = []
    for s in STAGES[b]:
        st = [r for r in treated if r.seen_stage == s]
        actions = []
        for a in ACTIONS[b]:
            g = _group([r for r in st if r.action == a])
            actions.append({"action": a, **g, "rate_ci": wilson(g["responded"], g["n"]),
                            "posterior_mean": round(policy.posterior_mean(s, a), 4)})
        tried = sorted((x for x in actions if x["n"]), key=lambda x: -x["posterior_mean"])
        best = tried[0]["action"] if tried else None
        runner_up = tried[1]["action"] if len(tried) > 1 else None
        stages.append({"stage": s, **_lift(st, [r for r in holdout if r.seen_stage == s]), "best_action": best,
                       "runner_up": runner_up, "best_call": best_call(tried), "actions": actions})
    by_id = {c.id: c for c in twin.customers}
    curve = []
    for r in range(twin.rounds):
        this = [x for x in treated if x.round == r and x.action]
        best = [x.action == _true_best(b, x.hidden_stage, by_id[x.customer].allowed(b, twin.rules)) for x in this]
        curve.append({"round": r, "treated_rate": _group([x for x in treated if x.round <= r])["rate"],
                      "holdout_rate": _group([x for x in holdout if x.round <= r])["rate"],
                      "best_pick_share": round(sum(best) / len(best), 4) if best else None})
    overall = _lift(treated, holdout)
    if random_records is not None:
        overall["random_policy"] = _group([r for r in random_records if not r.holdout])
    return {"business": b, "customers": len(twin.customers), "rounds": twin.rounds, "seed": twin.seed,
            "holdout_share": round(len(holdout) / len(records), 4), "policy": "thompson",
            "min_tries": policy.min_tries, "overall": overall,
            "stages": stages, "learning_curve": curve,
            "twin_truth": {"note": "the twin's hidden ground truth, never shown to the policy",
                           "response": RESPONSE[b], "baseline": BASELINE[b]}}


def run(business: str, n: int = 200, rounds: int = 10, seed: int = 7, min_tries: int | None = None) -> dict:
    """Thompson sampling on a fresh twin, plus the random policy on the same twin and luck for comparison.
    min_tries: None scales it to the twin's size (min_tries_for); 0 is plain Thompson. A business with delayed
    outcomes (MILESTONES) runs day by day, learning from replies and correcting with orders."""
    tries = min_tries_for(business, n) if min_tries is None else min_tries
    if business in MILESTONES:
        return run_milestones(business, n, rounds, seed, tries)
    twin = population(business, n, rounds, seed)
    policy = ThompsonPolicy(seed, tries)
    records = simulate(twin, policy)
    return report(twin, records, policy, simulate(twin, RandomPolicy(seed)))


# ---- delayed outcomes: milestones (Birgunj) ---------------------------------------------------
# When the outcome that matters arrives late, learn from an early milestone and correct with the later ones.
# In Birgunj a reply comes on day 1, an order on day 3, a reorder by day 30. The order is what the shop wants. A
# reply is a cheap early guess at it, and sometimes a misleading one: a discount draws "how much?" replies that
# never become orders. Brightdesk keeps its one outcome, decided at the end of a round, as it was recorded.
MILESTONES: dict[str, tuple[tuple[str, int], ...]] = {"birgunj": (("reply", 1), ("order", 3), ("reorder", 30))}
OBJECTIVE = "order"  # what Thompson sampling optimises, and what the lift against the holdout measures
ARRIVAL_DAYS = 30  # customers arrive over a month; the twin runs on until the last reorder is in
SILENT_ORDER_SHARE = 0.25  # of a customer's order chance, the part that comes with no reply (a cash-on-delivery link)
# The twin's hidden truth for the early milestone: the chance of a reply within a day. Read with RESPONSE (orders):
# in asked_no_order, festival and loyal the action with the most replies is not the one with the most orders.
REPLY: dict[str, dict[str, dict[str, float]]] = {
    "birgunj": {
        "new":            {"send_reminder": .20, "recommend_product": .30, "offer_reorder": .10, "offer_discount": .35, "send_help": .25, "send_checkin": .25},
        "loyal":          {"send_reminder": .15, "recommend_product": .35, "offer_reorder": .40, "offer_discount": .45, "send_help": .10, "send_checkin": .25},
        "wholesale":      {"send_reminder": .10, "recommend_product": .25, "offer_reorder": .55, "offer_discount": .50, "send_help": .15, "send_checkin": .20},
        "festival":       {"send_reminder": .15, "recommend_product": .30, "offer_reorder": .15, "offer_discount": .40, "send_help": .10, "send_checkin": .15},
        "asked_no_order": {"send_reminder": .45, "recommend_product": .25, "offer_reorder": .10, "offer_discount": .55, "send_help": .20, "send_checkin": .15},
        "gone_quiet":     {"send_reminder": .10, "recommend_product": .20, "offer_reorder": .15, "offer_discount": .35, "send_help": .10, "send_checkin": .25},
        "complaint":      {"send_reminder": .10, "recommend_product": .05, "offer_reorder": .05, "offer_discount": .30, "send_help": .60, "send_checkin": .20},
    },
}
REPLY_BASELINE = {"birgunj": {"new": .05, "loyal": .08, "wholesale": .10, "festival": .05, "asked_no_order": .08,
                              "gone_quiet": .02, "complaint": .30}}  # complainers write anyway
# Chance of a reorder within 30 days, given an order: by stage, nudged by the action that won the order (a
# reorder nudge builds the habit; a discount buys one order from people who wait for the next discount).
REORDER_BASE = {"birgunj": {"new": .25, "loyal": .45, "wholesale": .60, "festival": .15, "asked_no_order": .25,
                            "gone_quiet": .20, "complaint": .30}}
REORDER_ACTION = {"offer_reorder": .10, "offer_discount": -.10}


@dataclass(frozen=True)
class Chances:
    reply: float
    order: float  # the marginal chance of an order (what RESPONSE says, after the customer's own world)
    order_if_reply: float
    order_if_silent: float
    reorder: float  # given an order


def chances(business: str, c: TwinCustomer, action: str | None) -> Chances:
    """This customer's chances, from the twin's tables and their hidden world: cash on delivery loses some orders
    at the door, a price-sensitive customer answers a discount more, a returner reorders less, a wholesale buyer
    more. The reply and the order are linked: most orders follow a reply, so a reply is evidence of an order."""
    w = c.world
    if action is None:
        reply, order = REPLY_BASELINE[business][c.hidden_stage], BASELINE[business][c.hidden_stage]
    else:
        reply, order = REPLY[business][c.hidden_stage][action], RESPONSE[business][c.hidden_stage][action]
    if w.get("payment") == "COD":
        order *= 0.85
    if w.get("price_sensitive") and action == "offer_discount":
        reply, order = reply * 1.15, order * 1.25
    reorder = REORDER_BASE[business][c.hidden_stage] + REORDER_ACTION.get(action or "", 0.0)
    reorder *= (0.6 if w.get("return_prone") else 1.0) * (1.2 if w.get("segment") == "wholesale" else 1.0)
    reply, order, reorder = (min(0.95, max(0.0, x)) for x in (reply, order, reorder))
    # Split the order chance across replied / silent so the marginal stays exactly `order`.
    if_reply = min(0.95, (order - (1 - reply) * SILENT_ORDER_SHARE * order) / reply) if reply else 0.0
    if_silent = (order - reply * if_reply) / (1 - reply) if reply < 1 else 0.0
    return Chances(reply, order, if_reply, max(0.0, if_silent), reorder)


@lru_cache(maxsize=None)
def hidden_world(business: str) -> tuple[dict, ...]:
    """The shop's customers as they really are (data/synth/<business>/_truth.json "world"), in key order."""
    world = json.loads((OUT / business / "_truth.json").read_text(encoding="utf-8"))["world"]
    return tuple(world[k] for k in sorted(world))


def world_population(business: str, n: int = 200, rounds: int = 10, seed: int = 7,
                     holdout_share: float = HOLDOUT_SHARE) -> Twin:
    """Twin customers drawn from the shop's hidden world: each is a real (synthetic) customer's whole profile,
    picked with replacement. Each has three lucks fixed up front (reply, order, reorder), so two policies on the
    same twin meet the same luck. They arrive over ARRIVAL_DAYS days; `round` is their arrival bucket for charts."""
    pop, luck = random.Random(f"{seed}:population"), random.Random(f"{seed}:outcomes")
    world, seen = hidden_world(business), seen_given_hidden(business)
    customers = []
    for i in range(n):
        w = pop.choice(world)
        hidden = w["stage"]
        lo, hi = NEW_STAGES.get(hidden, (20, 700))
        day = i * ARRIVAL_DAYS // n
        customers.append(TwinCustomer(f"{business[:2]}-twin-{i:05d}", hidden, _pick(pop, seen[hidden]),
                                      pop.randint(lo, hi), w["country"], False, luck.random(),
                                      day * rounds // ARRIVAL_DAYS, world=w,
                                      lucks={"reply": luck.random(), "reorder": luck.random()}, day=day))
    for c in random.Random(f"{seed}:holdout").sample(customers, round(n * holdout_share)):
        c.holdout = True
    return Twin(business, customers, rounds, seed, TWIN_RULES[business])


@dataclass
class Event:
    """A milestone arriving: which decision it belongs to, which milestone, what happened, and when."""
    decision: Record
    milestone: str
    outcome: bool
    day: int


def simulate_milestones(twin: Twin, policy, observe_holdout: bool = False) -> list[Record]:
    """Day by day: first the milestones due today reach the policy (each credited to the decision that caused
    it, never to a later one), then today's customers get their action. Runs until the last reorder is in."""
    b = twin.business
    offsets = dict(MILESTONES[b])
    arrivals: dict[int, list[TwinCustomer]] = {}
    for c in twin.customers:
        arrivals.setdefault(c.day, []).append(c)
    due: dict[int, list[Event]] = {}
    records: list[Record] = []
    for day in range(ARRIVAL_DAYS + max(offsets.values()) + 1):
        for ev in due.pop(day, []):
            policy.observe(ev)
        if hasattr(policy, "end_of_day"):
            policy.end_of_day(day)
        for c in arrivals.get(day, []):
            allowed = () if c.holdout else c.allowed(b, twin.rules)
            action = policy.choose(c.seen_stage, allowed) if allowed else None
            p = chances(b, c, action)
            replied = c.lucks["reply"] < p.reply
            ordered = c.luck < (p.order_if_reply if replied else p.order_if_silent)
            reordered = ordered and c.lucks["reorder"] < p.reorder
            rec = Record(c.id, c.round, c.hidden_stage, c.seen_stage, c.holdout, action, p.order, ordered,
                         replied=replied, reordered=reordered, day=day, decision_id=f"{c.id}:d{day}")
            records.append(rec)
            if action:
                for name, outcome in (("reply", replied), ("order", ordered), ("reorder", reordered)):
                    due.setdefault(day + offsets[name], []).append(Event(rec, name, outcome, day + offsets[name]))
    return records


class MilestoneThompson(ThompsonPolicy):
    """Thompson sampling on the order, the outcome that matters, fed as the milestones arrive.

    Day 1, the reply: provisional evidence. A reply counts as `w` of an order and `1 - w` of a miss, where `w` is
    how often a reply has really led to an order so far (and `w0`, likewise, for no reply). Day 3, the order:
    the provisional evidence for that decision is taken back and the real outcome put in. Day 30, the reorder:
    counted per stage and action, for the report. learn_from="reply" is the learner that never corrects: it
    takes a reply as success, the way a dashboard counting replies would."""

    def __init__(self, seed: int = 0, min_tries: int = 0, learn_from: str = "milestones"):
        super().__init__(seed, min_tries)
        self.learn_from = learn_from
        # replied? -> [orders, decisions]. The prior: a reply is worth half an order and silence a tenth, until the
        # shop's own orders say otherwise (worth 2 and 10 decisions: the data takes over within days).
        self.link = {True: [1.0, 2.0], False: [1.0, 10.0]}
        self.provisional: dict[str, tuple[str, str, float, bool]] = {}  # decision id -> (stage, action, w, replied)
        self.reorders: dict[tuple[str, str], list[int]] = {}  # (stage, action) -> [reorders, orders]
        self.credited: list[tuple[str, str, str, str]] = []  # (decision id, milestone, stage, action): the audit
        self.leaders: dict[int, dict[str, str]] = {}  # day -> stage -> the action Thompson would back

    def observe(self, ev: Event) -> None:
        d = ev.decision
        key = (d.seen_stage, d.action)
        self.credited.append((d.decision_id, ev.milestone, d.seen_stage, d.action))
        ab = self._beta(*key)
        if self.learn_from == "reply":
            if ev.milestone == "reply":
                ab[0 if ev.outcome else 1] += 1
            return
        if ev.milestone == "reply":
            orders, total = self.link[ev.outcome]
            w = orders / total
            ab[0] += w
            ab[1] += 1 - w
            self.provisional[d.decision_id] = (d.seen_stage, d.action, w, ev.outcome)
        elif ev.milestone == "order":
            stage, action, w, replied = self.provisional.pop(d.decision_id)
            ab[0] += (1 if ev.outcome else 0) - w
            ab[1] += (0 if ev.outcome else 1) - (1 - w)
            self.link[replied][0] += ev.outcome
            self.link[replied][1] += 1
        elif ev.milestone == "reorder" and d.responded:
            k = self.reorders.setdefault(key, [0, 0])
            k[0] += ev.outcome
            k[1] += 1

    def update(self, seen_stage: str, action: str, responded: bool) -> None:
        pass  # outcomes arrive through observe(), on the day they happen

    def end_of_day(self, day: int) -> None:
        board = {}
        for (stage, action), _ in self.ab.items():
            best = board.get(stage)
            if best is None or self.posterior_mean(stage, action) > self.posterior_mean(stage, best):
                board[stage] = action
        self.leaders[day] = board


def run_milestones(business: str, n: int, rounds: int, seed: int, min_tries: int) -> dict:
    twin = world_population(business, n, rounds, seed)
    policy = MilestoneThompson(seed, min_tries)
    records = simulate_milestones(twin, policy)
    random_records = simulate_milestones(twin, RandomPolicy(seed))
    reply_only = MilestoneThompson(seed, min_tries, learn_from="reply")
    reply_records = simulate_milestones(twin, reply_only)
    res = report(twin, records, policy, random_records)
    b = twin.business
    treated = [r for r in records if not r.holdout]
    holdout = [r for r in records if r.holdout]

    def as_outcome(rs: list[Record], what: str) -> list[Record]:
        return [dataclasses.replace(r, responded=getattr(r, what)) for r in rs]

    res["milestones"] = {
        "days": dict(MILESTONES[b]), "objective": OBJECTIVE,
        "reply": _lift(as_outcome(treated, "replied"), as_outcome(holdout, "replied")),
        "order": res["overall"],
        "reorder": _lift(as_outcome(treated, "reordered"), as_outcome(holdout, "reordered")),
    }
    res["overall"]["reply_only_policy"] = {**_group([r for r in reply_records if not r.holdout]),
                                           "note": "the same Thompson sampling, learning from replies only"}
    # Where replies alone would have backed a different action than the orders did: the corrections.
    corrections = []
    for st in res["stages"]:
        tried = [a for a in st["actions"] if a["n"] >= 20]
        if len(tried) < 2:
            continue
        by_reply = max(tried, key=lambda a: _rate([r.replied for r in treated
                                                     if r.seen_stage == st["stage"] and r.action == a["action"]]))
        by_order = max(tried, key=lambda a: a["rate"])
        first_day = next((d for d, board in sorted(policy.leaders.items())
                          if board.get(st["stage"]) == by_order["action"]
                          and all(b2.get(st["stage"]) == by_order["action"] for d2, b2 in policy.leaders.items() if d2 >= d)),
                         None)
        if by_reply["action"] != by_order["action"]:
            corrections.append({"stage": st["stage"], "replies_say": by_reply["action"], "orders_say": by_order["action"],
                                "settled_on_day": first_day})
    res["corrections"] = corrections
    for st in res["stages"]:
        for a in st["actions"]:
            k = policy.reorders.get((st["stage"], a["action"]))
            a["reply_rate"] = _rate([r.replied for r in treated if r.seen_stage == st["stage"] and r.action == a["action"]])
            a["reorder_rate"] = round(k[0] / k[1], 4) if k and k[1] else None
    res["days"] = ARRIVAL_DAYS + max(dict(MILESTONES[b]).values())
    res["twin_truth"]["reply"] = REPLY[b]
    res["twin_truth"]["reorder_base"] = REORDER_BASE[b]
    return res


def _rate(xs: list[bool]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def table(res: dict) -> str:
    o = res["overall"]
    rnd = f"  (random policy {o['random_policy']['rate']:.1%})" if "random_policy" in o else ""
    lines = [f"{res['business']}: {res['customers']} customers, {res['rounds']} rounds, "
             f"holdout {res['holdout_share']:.0%}, seed {res['seed']}",
             f"  overall          treated {o['treated']['rate']:.1%} (n={o['treated']['n']}), "
             f"holdout {o['holdout']['rate']:.1%} (n={o['holdout']['n']}), lift {o['lift_pp']:+.1f} pp "
             f"[{o['ci_pp'][0]:+.1f}, {o['ci_pp'][1]:+.1f}] {o['verdict']}{rnd}"]
    for s in res["stages"]:
        if s["lift_pp"] is None:
            lines.append(f"  {s['stage']:16} too few to compare (treated {s['treated']['n']}, "
                         f"holdout {s['holdout']['n']})")
        else:
            lines.append(f"  {s['stage']:16} lift {s['lift_pp']:+6.1f} pp [{s['ci_pp'][0]:+6.1f}, "
                         f"{s['ci_pp'][1]:+6.1f}]  {s['verdict']:8} best {s['best_action']:18} "
                         f"(treated {s['treated']['n']}, holdout {s['holdout']['n']})")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    from .config import REPO_ROOT

    ap = argparse.ArgumentParser(description="Run the customer twin with Thompson sampling (maths only, $0).")
    ap.add_argument("business", choices=sorted(RESPONSE))
    ap.add_argument("--customers", type=int, default=200, help="200 while developing; 5000 for the full run")
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=None, help="results JSON (default .pheri/twin/<business>-n<N>-seed<S>.json)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    res = run(args.business, args.customers, args.rounds, args.seed)
    out = Path(args.out or REPO_ROOT / ".pheri" / "twin" / f"{args.business}-n{args.customers}-seed{args.seed}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(table(res))
    print(f"\nChart-ready results: {out}")
