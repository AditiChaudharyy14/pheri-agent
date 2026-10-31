"""50 judge cases for Birgunj, labelled by code: 25 drafts that say only what their cited facts say, and the same
25 with one planted claim no fact backs (a reason, an outcome, a preference, a competitor, a contradiction), in
words only, so no code check can see it. Every case passes every code check offline (checked here), so the
judge is the only thing that can tell the two apart. English drafts, for customers who write in English or have
not written, so the language check stays out of it."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "api"))

T = " - The Birgunj Saree Ghar team"
PAIRS = 25

# stage -> (action, message, why_this, why_now, fact keys); {f[...]} are the customer's own facts.
SUPPORTED = {
    # Messages follow the rules of 31 Oct: no counts about the customer (they stay in why), no photos offered or
    # promised by Pheri (the owner shares them), no "we will update you today".
    "loyal": ("offer_reorder", "Hi {first}, thank you for ordering with us again and again. When it is time for the next one, just reply here.",
              "{first} is a loyal regular with {orders} orders.", "{first} last ordered {days_since_last_order} days ago.",
              ["journey_stage", "orders", "days_since_last_order"]),
    "wholesale": ("offer_reorder", "Hi {first}, your last lot was {last_order_items}. Shall we keep the same for the next one?",
                  "{first} buys wholesale; the last order was {last_order_items}.",
                  "{first} reorders about every {reorder_every_days} days and last ordered {days_since_last_order} days ago.",
                  ["journey_stage", "segment", "last_order_items", "reorder_every_days", "days_since_last_order"]),
    "festival": ("recommend_product", "Hi {first}, {fest} is {days_to_next_festival} days away. Would you like the owner to show you some festival sarees this morning?",
                 "{first} has only ever bought for festivals, {orders} orders in all.", "{fest} is in {days_to_next_festival} days.",
                 ["journey_stage", "festival_only", "orders", "next_festival", "days_to_next_festival"]),
    "asked_no_order": ("send_reminder", "Hi {first}, you asked about an item recently. Would you like to go ahead with the order?",
                       "{first} asked {days_since_enquiry} days ago and has not ordered since.", "{first} asked {days_since_enquiry} days ago.",
                       ["journey_stage", "days_since_enquiry", "days_since_last_order"]),
    "complaint": ("send_help", "Hi {first}, we are sorry your order has a problem. The owner will look into it this morning and reply to you.",
                  "{first} has {open_complaints} order with a problem that is still open.", "The problem is still open.",
                  ["journey_stage", "open_complaints", "complaint_kind"]),
    "gone_quiet": ("send_checkin", "Hi {first}, it has been a while since your last order. Is there anything we can help with?",
                   "{first} has not ordered for {days_since_last_order} days.", "{first} last ordered {days_since_last_order} days ago.",
                   ["journey_stage", "days_since_last_order", "orders"]),
    "new": ("recommend_product", "Hi {first}, welcome to Birgunj Saree Ghar. Would you like the owner to show you some sarees this morning?",
            "{first} joined {days_since_signup} days ago.", "{first} is in the first weeks.",
            ["journey_stage", "days_since_signup", "orders"]),
}
# One planted claim per case, rotating: where it goes, and what it says.
PLANTED = [
    ("why_this", "reason", " The real reason is that the delivery charge was too high."),
    ("message", "outcome", " Your last saree was loved by the whole family."),
    ("why_this", "preference", " {first} always chooses red."),
    ("why_now", "competitor", " {first} has been buying from another shop in the meantime."),
    ("message", "contradiction", " As this is your very first order with us, welcome."),
]


def judge_cases() -> list[dict]:
    from pheri.config import Settings
    from pheri.journey import stages
    from pheri.llm import LLM
    from pheri.profile import compute_facts, load

    import tempfile

    sys.path.insert(0, str(HERE))
    from run import verify_drafts  # noqa: E402

    ds = load("birgunj")
    st = stages(ds)
    order = list(SUPPORTED)
    by_stage: dict[str, list[str]] = {s: [] for s in order}
    for k, j in st.items():
        c = ds.customers[k]
        if j.stage in by_stage and all(s.lang in (None, "en") for s in c.sources):
            by_stage[j.stage].append(k)
    offline = LLM(Settings(llm_mode="mock", record_path=None, database_url=None,
                           ledger_path=str(Path(tempfile.mkdtemp()) / "l.sqlite")))
    cases, n = [], 0
    while len(cases) < 2 * PAIRS and any(by_stage.values()):
        for s in order:
            if len(cases) >= 2 * PAIRS or not by_stage[s]:
                continue
            k = by_stage[s].pop(0)
            f, _ = compute_facts(ds.customers[k], "birgunj")
            if any(f.get(x) is None for x in SUPPORTED[s][4] if x != "journey_stage"):
                continue
            first = ds.customers[k].name.split()[0]
            vals = {**{x: v for x, v in f.items()}, "first": first, "fest": (f.get("next_festival") or "").title()}
            action, msg, why, now, keys = SUPPORTED[s]
            draft = {"action": action, "channel": "whatsapp", "discount_pct": None, "message": msg.format(**vals) + T,
                     "why_this": why.format(**vals), "why_now": now.format(**vals), "fact_keys": keys, "quote_ids": []}
            where, kind, claim = PLANTED[n % len(PLANTED)]
            if kind == "contradiction" and s == "new":  # "your very first order" is true for a new customer (31 Oct:
                claim = " Thank you for shopping with us for so many years."  # 3 such labels were wrong; this isn't)
            planted = dict(draft)
            if where == "message":
                planted["message"] = draft["message"].replace(T, claim.format(**vals) + T)
            else:
                planted[where] = draft[where] + claim.format(**vals)
            pair = [{"id": f"JS{n + 1:02d}", "business": "birgunj", "customer": k, "expect": [],
                     "note": f"supported ({s})", "draft": draft},
                    {"id": f"JP{n + 1:02d}", "business": "birgunj", "customer": k, "expect": ["judge"],
                     "note": f"planted {kind} ({s})", "draft": planted}]
            # Code must pass both, or the judge is not what tells them apart.
            if all(not r["failed"] for r in verify_drafts(offline, cases=pair)["rows"]):
                cases += pair
                n += 1
    return cases
