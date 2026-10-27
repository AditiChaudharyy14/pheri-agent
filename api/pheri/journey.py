"""Journey stage per customer, decided in code from code-computed facts. No model is involved.

    python -m pheri.journey          # accuracy against data/synth/*/_truth.json

Each stage comes with the facts that decided it and the rows those facts were counted from, so
"why is Maya stuck?" always has an answer a person can check. Rules are tried in order and the
first match wins: a customer who is both new and failing exports is onboarding first.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .profile import Dataset, compute_facts, load
from .synth import OUT, TODAY

BRIGHTDESK_STAGES = ("onboarding", "stuck", "quiet", "healthy", "expanding", "at_risk_renewal")
KETTLE_STAGES = ("new", "loyal", "subscriber", "lapsing", "cart_abandoner", "gift_buyer")
STAGES = {"brightdesk": BRIGHTDESK_STAGES, "kettle": KETTLE_STAGES}

ONBOARDING_DAYS = 14  # Brightdesk: the first two weeks are onboarding
RENEWAL_WINDOW_DAYS = 30
USAGE_FALL_PCT = -60  # Brightdesk: active days down 60% or more against their usual pace
NEW_CUSTOMER_DAYS = 30  # Kettle: joined within a month
LAPSED_AFTER_DAYS = 60  # Kettle: no order in two months
CART_RECENT_DAYS = 7


@dataclass
class Journey:
    stage: str
    because: list[dict] = field(default_factory=list)  # {"fact", "value", "refs"}

    def as_dict(self) -> dict:
        return {"stage": self.stage, "because": self.because}


def _why(facts: dict, prov: dict, *keys: str) -> list[dict]:
    return [{"fact": k, "value": facts.get(k), "refs": prov.get(k, [])} for k in keys]


def _brightdesk(f: dict, p: dict) -> Journey:
    if f.get("days_since_signup") is not None and f["days_since_signup"] <= ONBOARDING_DAYS:
        return Journey("onboarding", _why(f, p, "days_since_signup"))
    if f["failed_exports_30d"] > 0:
        return Journey("stuck", _why(f, p, "failed_exports_30d", "days_quiet"))
    if f["price_complaints"] > 0 and f["renewal_in_days"] <= RENEWAL_WINDOW_DAYS:
        return Journey("at_risk_renewal", _why(f, p, "price_complaints", "renewal_in_days"))
    if f["seat_limit_hits_30d"] > 0:
        return Journey("expanding", _why(f, p, "seat_limit_hits_30d", "seats"))
    change = f.get("usage_change_pct")
    if (change is not None and change <= USAGE_FALL_PCT and f["active_days_30d"] >= 1
            and f["renewal_in_days"] <= RENEWAL_WINDOW_DAYS):  # fading before renewal, not gone (that is quiet)
        return Journey("at_risk_renewal", _why(f, p, "usage_change_pct", "active_days_30d", "renewal_in_days"))
    if f["active_days_30d"] == 0:
        return Journey("quiet", _why(f, p, "active_days_30d", "days_quiet"))
    return Journey("healthy", _why(f, p, "active_days_30d"))


def _kettle(f: dict, p: dict) -> Journey:
    if f["subscription"] == "monthly":
        return Journey("subscriber", _why(f, p, "subscription"))
    cart, last_order = f["days_since_cart_abandoned"], f["days_since_last_order"]
    if cart is not None and cart <= CART_RECENT_DAYS and (last_order is None or last_order > cart):
        return Journey("cart_abandoner", _why(f, p, "days_since_cart_abandoned"))
    if f.get("days_since_signup") is not None and f["days_since_signup"] <= NEW_CUSTOMER_DAYS:
        return Journey("new", _why(f, p, "days_since_signup", "orders"))
    if last_order is None or last_order >= LAPSED_AFTER_DAYS:
        return Journey("lapsing", _why(f, p, "days_since_last_order", "orders"))
    if f["gift_only"]:
        return Journey("gift_buyer", _why(f, p, "gift_only", "orders"))
    return Journey("loyal", _why(f, p, "orders", "days_since_last_order"))


RULES = {"brightdesk": _brightdesk, "kettle": _kettle}


def stage(business: str, facts: dict, provenance: dict | None = None) -> Journey:
    """`provenance` is the fact provenance from compute_facts (or Profile.provenance["facts"])."""
    return RULES[business](facts, provenance or {})


def stages(ds: Dataset, today=TODAY) -> dict[str, Journey]:
    out = {}
    for key, c in ds.customers.items():
        facts, prov = compute_facts(c, ds.business, today)
        out[key] = stage(ds.business, facts, prov)
    return out


# ---- accuracy ---------------------------------------------------------------------
@dataclass
class Accuracy:
    business: str
    correct: int
    total: int
    confusion: Counter  # (true, predicted) -> count

    @property
    def rate(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def per_stage(self) -> dict[str, tuple[int, int]]:
        """stage -> (correct, how many customers truly are in it)."""
        out = {}
        for s in STAGES[self.business]:
            n = sum(v for (t, _), v in self.confusion.items() if t == s)
            out[s] = (self.confusion[(s, s)], n)
        return out

    def report(self) -> str:
        lines = [f"{self.business}: {self.correct}/{self.total} = {self.rate:.1%}"]
        for s, (ok, n) in self.per_stage().items():
            wrong = {p: v for (t, p), v in self.confusion.items() if t == s and p != s}
            miss = ", ".join(f"{v} as {p}" for p, v in sorted(wrong.items(), key=lambda kv: -kv[1]))
            lines.append(f"  {s:16} {ok:3}/{n:<3}" + (f"  (missed: {miss})" if miss else ""))
        return "\n".join(lines)


def accuracy(business: str, folder: Path | None = None) -> Accuracy:
    folder = folder or OUT / business
    truth = json.loads((folder / "_truth.json").read_text(encoding="utf-8"))["stages"]
    predicted = stages(load(business, folder))
    confusion = Counter((truth[k], predicted[k].stage) for k in truth if k in predicted)
    correct = sum(v for (t, p), v in confusion.items() if t == p)
    return Accuracy(business, correct, sum(confusion.values()), confusion)


if __name__ == "__main__":
    for slug in sys.argv[1:] or list(STAGES):
        print(accuracy(slug).report())
