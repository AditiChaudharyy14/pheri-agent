"""Customer twin: maths only, seeded, inside the owner's rules, with a true 20% holdout."""

from collections import Counter

import pytest

from pheri.journey import STAGES
from pheri.llm import LLM
from pheri.twin import ACTIONS, BASELINE, RESPONSE, RandomPolicy, population, seen_given_hidden, simulate


@pytest.mark.parametrize("business", ["brightdesk", "kettle"])
def test_the_truth_table_covers_every_stage_and_action(business):
    assert set(RESPONSE[business]) == set(STAGES[business]) == set(BASELINE[business])
    for stage, row in RESPONSE[business].items():
        assert set(row) == set(ACTIONS[business])
        assert all(0 <= p <= 1 for p in row.values()) and 0 <= BASELINE[business][stage] <= 1


def test_population_is_seeded_sized_and_holds_out_exactly_20_percent():
    a, b = population("brightdesk", n=200, seed=7), population("brightdesk", n=200, seed=7)
    assert [c.__dict__ for c in a.customers] == [c.__dict__ for c in b.customers]
    assert len(a.customers) == 200 and sum(c.holdout for c in a.customers) == 40
    assert population("brightdesk", n=200, seed=8).customers[0].__dict__ != a.customers[0].__dict__
    assert {c.round for c in a.customers} == set(range(a.rounds))


def test_pheri_sees_the_stage_through_its_own_measured_mistakes():
    # Kettle's journey rules are 300/300 right; Brightdesk's mix up quiet, healthy and at-risk.
    assert all(c.seen_stage == c.hidden_stage for c in population("kettle", n=300).customers)
    bd = population("brightdesk", n=1000)
    wrong = Counter((c.hidden_stage, c.seen_stage) for c in bd.customers if c.seen_stage != c.hidden_stage)
    assert wrong and {h for h, _ in wrong} <= {"quiet", "healthy", "at_risk_renewal"}
    assert seen_given_hidden("brightdesk")["stuck"] == {s: (1.0 if s == "stuck" else 0.0) for s in STAGES["brightdesk"]}


def test_the_owners_rule_holds_in_the_twin():
    twin = population("brightdesk", n=500)
    for c in twin.customers:
        allowed = c.allowed("brightdesk", twin.rules)
        assert ("offer_discount" in allowed) is (c.days_since_signup >= 30)
    records = simulate(twin, RandomPolicy())
    by_id = {c.id: c for c in twin.customers}
    assert all(by_id[r.customer].days_since_signup >= 30 for r in records if r.action == "offer_discount")


def test_holdout_gets_no_action_and_responds_at_the_baseline():
    twin = population("kettle", n=200)
    records = simulate(twin, RandomPolicy())
    luck = {c.id: c.luck for c in twin.customers}
    for r in records:
        if r.holdout:
            assert r.action is None and r.chance == BASELINE["kettle"][r.hidden_stage]
        else:
            assert r.chance == RESPONSE["kettle"][r.hidden_stage][r.action]
        assert r.responded is (luck[r.customer] < r.chance)
    assert len(records) == 200 and sum(r.holdout for r in records) == 40


def test_two_policies_meet_the_same_luck():
    twin = population("brightdesk", n=200)
    a = {r.customer: r for r in simulate(twin, RandomPolicy(seed=1))}
    b = {r.customer: r for r in simulate(twin, RandomPolicy(seed=2))}
    assert all(a[k].responded == b[k].responded for k in a if a[k].holdout)  # holdout: identical
    assert any(a[k].action != b[k].action for k in a if not a[k].holdout)  # treated: different picks


def test_no_model_is_ever_called(monkeypatch):
    monkeypatch.setattr(LLM, "complete", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called")))
    simulate(population("brightdesk", n=200), RandomPolicy())
