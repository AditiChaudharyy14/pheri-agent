"""Delayed outcomes (Agents 102): learn from the early milestone, correct with the later ones, and credit every
milestone to the decision that caused it. Maths only: no model, no network."""

import json
import random

import pytest

from pheri.config import REPO_ROOT
from pheri.twin import (MILESTONES, REPLY, RESPONSE, Event, MilestoneThompson, Record, chances, min_tries_for, run,
                        simulate_milestones, world_population)


def _decision(i: int, stage: str, action: str) -> Record:
    return Record(f"c{i}", 0, stage, stage, False, action, 0.0, False, day=0, decision_id=f"d{i}")


def test_replies_lead_first_and_orders_correct_them():
    """A planted case. Action A draws more replies (60%) but fewer orders (20%); B fewer replies (40%), more
    orders (40%). On replies alone Thompson backs A; once the orders are in it backs B, and the provisional
    evidence is gone: the posterior is exactly the orders."""
    policy = MilestoneThompson(seed=1)
    rng = random.Random(3)
    plan = {"A": (0.6, 0.2), "B": (0.4, 0.4)}
    decisions = []
    for i in range(400):
        action = "AB"[i % 2]
        reply_p, order_p = plan[action]
        replied = rng.random() < reply_p
        # orders follow replies, as in the twin: most orders come from people who replied
        ordered = rng.random() < (min(0.95, order_p / reply_p * 0.8) if replied else order_p * 0.2)
        decisions.append((_decision(i, "s", action), replied, ordered))
    for d, replied, _ in decisions:
        policy.observe(Event(d, "reply", replied, 1))
    assert policy.posterior_mean("s", "A") > policy.posterior_mean("s", "B")  # the early signal misleads
    for d, _, ordered in decisions:
        policy.observe(Event(d, "order", ordered, 3))
    assert policy.posterior_mean("s", "B") > policy.posterior_mean("s", "A")  # the orders correct it
    assert not policy.provisional
    for action in "AB":
        orders = sum(o for d, _, o in decisions if d.action == action)
        n = sum(d.action == action for d, _, _ in decisions)
        assert policy.ab[("s", action)] == pytest.approx([1 + orders, 1 + n - orders])


def test_a_learner_on_replies_alone_never_corrects():
    policy = MilestoneThompson(seed=1, learn_from="reply")
    d = _decision(0, "s", "A")
    policy.observe(Event(d, "reply", True, 1))
    policy.observe(Event(d, "order", False, 3))
    assert policy.ab[("s", "A")] == [2, 1]  # the reply counted as a win; the missing order changed nothing


def test_every_milestone_is_credited_to_the_decision_that_caused_it_on_its_day():
    twin = world_population("birgunj", n=600, seed=5)
    log: list = []  # ("event", Event) and ("day", day) in the order the simulation makes them
    policy = MilestoneThompson(seed=5, min_tries=min_tries_for("birgunj", 600))
    real_observe, real_end = policy.observe, policy.end_of_day
    policy.observe = lambda ev: (log.append(("event", ev)), real_observe(ev))
    policy.end_of_day = lambda day: (log.append(("day", day)), real_end(day))
    records = simulate_milestones(twin, policy)
    by_id = {r.decision_id: r for r in records}
    offsets = dict(MILESTONES["birgunj"])
    events = [ev for kind, ev in log if kind == "event"]
    assert events and {ev.milestone for ev in events} == set(offsets)
    closed = -1  # the last day whose end has passed
    for kind, x in log:
        if kind == "day":
            closed = x
            continue
        assert x.day == closed + 1  # it arrives on its own day, before that day's customers are decided
        assert x.day == x.decision.day + offsets[x.milestone]  # never early, never late
        r = by_id[x.decision.decision_id]
        assert x.decision is r and not r.holdout and r.action  # the holdout's outcomes teach nothing
        assert x.outcome == {"reply": r.replied, "order": r.responded, "reorder": r.reordered}[x.milestone]
    for decision_id, milestone, stage, action in policy.credited:
        assert (stage, action) == (by_id[decision_id].seen_stage, by_id[decision_id].action)
    treated = [r for r in records if r.action]
    assert len(policy.credited) == 3 * len(treated)  # three milestones per treated decision, once each


def test_the_reply_and_the_order_are_linked_but_the_order_chance_is_kept():
    twin = world_population("birgunj", n=300, seed=2)
    for c in twin.customers:
        for action in (None, *REPLY["birgunj"][c.hidden_stage]):
            p = chances("birgunj", c, action)
            assert p.reply * p.order_if_reply + (1 - p.reply) * p.order_if_silent == pytest.approx(p.order)
            assert 0 <= p.order_if_silent <= p.order <= p.order_if_reply <= 0.95 or p.reply == 0
            assert 0 <= p.reorder <= 0.95


def test_the_twin_draws_customers_from_the_shops_hidden_world():
    world = json.loads((REPO_ROOT / "data" / "synth" / "birgunj" / "_truth.json").read_text(encoding="utf-8"))["world"]
    profiles = [json.dumps(w, sort_keys=True) for w in world.values()]
    twin = world_population("birgunj", n=500, seed=7)
    assert all(json.dumps(c.world, sort_keys=True) in profiles for c in twin.customers)
    assert all(c.hidden_stage == c.world["stage"] for c in twin.customers)
    assert sum(c.holdout for c in twin.customers) == 100


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_correcting_with_orders_beats_learning_from_replies(seed):
    """At the shop's size (5,000), on every seed: learning from replies and correcting with orders wins more
    orders than learning from replies alone, and both beat random. Asked-no-order is the planted trap: a
    discount gets the most replies, the reminder the most orders. Measured, and kept: at 2,000 customers the
    faster, biased signal does as well or a little better (seeds 1-3: 20.9-22.1% vs 20.1-21.2%); the
    correction pays off with volume."""
    res = run("birgunj", n=5000, seed=seed)
    o = res["overall"]
    assert o["treated"]["rate"] > o["reply_only_policy"]["rate"] > o["random_policy"]["rate"], seed
    asked = next(s for s in res["stages"] if s["stage"] == "asked_no_order")
    # In the shop's own world the gap is narrow (price-sensitive customers order more with a discount: about .32
    # against .29), so either the reminder wins or the results say it is a close call, out loud.
    assert asked["best_action"] == "send_reminder" or asked["best_call"] == "close call", seed
    assert RESPONSE["birgunj"]["asked_no_order"]["send_reminder"] > RESPONSE["birgunj"]["asked_no_order"]["offer_discount"]
    assert REPLY["birgunj"]["asked_no_order"]["offer_discount"] > REPLY["birgunj"]["asked_no_order"]["send_reminder"]


def test_results_say_what_replies_said_and_what_orders_said():
    res = run("birgunj", n=2000, seed=7)
    assert res == run("birgunj", n=2000, seed=7)  # seeded
    m = res["milestones"]
    assert m["days"] == {"reply": 1, "order": 3, "reorder": 30} and m["objective"] == "order"
    assert m["order"] is res["overall"] or m["order"] == res["overall"]
    for k in ("reply", "order", "reorder"):
        assert m[k]["verdict"] in ("works", "unclear", "hurts")
    assert any(c["stage"] == "asked_no_order" and c["replies_say"] == "offer_discount"
               and c["orders_say"] == "send_reminder" for c in res["corrections"])
    json.dumps(res)


def test_brightdesk_keeps_its_one_outcome_and_its_recorded_results():
    """Brightdesk's Muse Wonder report was recorded on these exact results: the milestone twin must not touch
    them by a single value."""
    res = run("brightdesk", n=5000, seed=7)
    assert "milestones" not in res
    saved = json.loads((REPO_ROOT / "data" / "twin" / "brightdesk-n5000-seed7.json").read_text(encoding="utf-8"))
    assert res == saved
