"""Customer twin: maths only, seeded, inside the owner's rules, with a true 20% holdout."""

from collections import Counter

import pytest

from pheri.journey import STAGES
from pheri.llm import LLM
from pheri.twin import (ACTIONS, BASELINE, RESPONSE, RandomPolicy, ThompsonPolicy, lift_ci, population, report, run,
                        seen_given_hidden, simulate, verdict, wilson)


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


# ---- Thompson sampling and lift ------------------------------------------------------------
def test_lift_interval_by_hand():
    # 30/100 treated vs 10/100 holdout: +20 pp, se = sqrt(.3*.7/100 + .1*.9/100) = 0.0548, 1.96 se = 10.7 pp
    assert lift_ci(30, 100, 10, 100) == (20.0, 9.3, 30.7)
    assert lift_ci(5, 10, 0, 0) is None  # no holdout, no lift
    assert wilson(0, 10) == [0.0, 0.2775] and wilson(10, 10) == [0.7225, 1.0]


def test_verdict_follows_the_interval():
    assert verdict((20.0, 9.3, 30.7)) == "works"
    assert verdict((-20.0, -30.7, -9.3)) == "hurts"
    assert verdict((6.9, -2.9, 16.7)) == "unclear" and verdict(None) == "unclear"


@pytest.mark.parametrize("business", ["brightdesk", "kettle"])
def test_thompson_beats_random_and_learns_on_every_seed(business):
    from pheri.twin import min_tries_for

    """1,000 customers and five seeds: whether it learns is a statistical claim, and 200 is too few to test it.
    On a single seed Thompson can still settle on the wrong action for one small stage (seen: Brightdesk stuck
    at 1,000, seed 7, about 127 customers), so the claims are the ones that hold on every seed."""
    stuck_right = 0
    for seed in range(1, 6):
        twin = population(business, n=1000, rounds=10, seed=seed)
        policy = ThompsonPolicy(seed, min_tries_for(business, 1000))
        res = report(twin, simulate(twin, policy), policy, simulate(twin, RandomPolicy(seed)))
        o = res["overall"]
        assert o["treated"]["rate"] > o["random_policy"]["rate"], seed  # learning beats picking at random
        curve = [c["best_pick_share"] for c in res["learning_curve"]]
        assert sum(curve[-3:]) / 3 > sum(curve[:3]) / 3, seed  # it picks the truly best action more over time
        stuck_right += any(s["stage"] == "stuck" and s["best_action"] == "send_help" for s in res["stages"])
    if business == "brightdesk":
        assert stuck_right >= 3  # the twin's truth for stuck: send_help .38, the highest


def test_results_are_chart_ready_and_honest():
    import json

    res = run("kettle", n=200)
    assert res == run("kettle", n=200)  # seeded: the same every time
    json.dumps(res)  # plain JSON
    assert set(res) >= {"overall", "stages", "learning_curve", "twin_truth", "holdout_share"}
    assert res["holdout_share"] == 0.2 and len(res["learning_curve"]) == res["rounds"]
    for s in [res["overall"], *res["stages"]]:
        if s["ci_pp"] is not None:
            assert verdict((s["lift_pp"], *s["ci_pp"])) == s["verdict"]
            assert s["ci_pp"][0] <= s["lift_pp"] <= s["ci_pp"][1]
    assert "never shown to the policy" in res["twin_truth"]["note"]
    assert "random_policy" in res["overall"]  # what learning adds, on the same twin and luck


def test_the_cli_writes_the_results_file(tmp_path):
    import json
    import subprocess
    import sys

    from pheri.config import REPO_ROOT

    out = tmp_path / "bd.json"
    done = subprocess.run([sys.executable, "-m", "pheri.twin", "brightdesk", "--out", str(out)],
                          capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT / "api")  # from any cwd
    assert done.returncode == 0, done.stderr
    assert "lift" in done.stdout and json.loads(out.read_text(encoding="utf-8"))["customers"] == 200


def test_every_allowed_action_gets_its_minimum_tries_before_thompson_exploits():
    from pheri.twin import min_tries_for

    assert [min_tries_for("brightdesk", n) for n in (5000, 1000, 200)] == [20, 4, 1]  # a little, at every size
    assert min_tries_for("kettle", 5000) == 20
    policy = ThompsonPolicy(seed=1, min_tries=3)
    allowed = ("a", "b", "c")
    first = [policy.choose("stuck", allowed) for _ in range(9)]
    assert sorted(first) == ["a"] * 3 + ["b"] * 3 + ["c"] * 3  # tries count when given, not when answered
    for _ in range(50):
        policy.update("stuck", "a", True)  # "a" looks great from here on, "b" and "c" poor
        policy.update("stuck", "b", False)
        policy.update("stuck", "c", False)
    assert {policy.choose("stuck", allowed) for _ in range(20)} == {"a"}  # minimum met: now it exploits


def test_the_minimum_fixes_the_healthy_stage_at_full_size():
    # Brightdesk at 5,000, seed 7: without the minimum, healthy settled on offer_discount (truth: offer_upgrade).
    from pheri.learn import learned_vs_truth

    twin = population("brightdesk", n=5000, rounds=10, seed=7)
    for min_tries, healthy_best in ((0, "offer_discount"), (20, "offer_upgrade")):
        policy = ThompsonPolicy(7, min_tries=min_tries)
        res = report(twin, simulate(twin, policy), policy)
        assert next(s for s in res["stages"] if s["stage"] == "healthy")["best_action"] == healthy_best
    assert all(x["match"] for x in learned_vs_truth(res))


def test_close_call_when_the_difference_between_the_top_two_includes_zero():
    from pheri.twin import best_call

    def a(k, n):
        return {"responded": k, "n": n}

    assert best_call([]) is None and best_call([a(5, 10)]) == "clear"
    assert best_call([a(178, 467), a(12, 48)]) == "clear"  # Brightdesk stuck at 5,000: +13.1 [+0.1, +26.1]
    assert best_call([a(98, 825), a(13, 160)]) == "close call"  # healthy: +3.8 [-1.0, +8.5]
    res = run("brightdesk", n=200)
    assert all(s["best_call"] in ("clear", "close call", None) for s in res["stages"])
    assert all(s["runner_up"] != s["best_action"] for s in res["stages"] if s["runner_up"])
