"""Journey stages: decided in code from facts, measured against the hidden truth. No model calls."""

import pytest

from pheri.journey import STAGES, accuracy, stage, stages
from pheri.profile import compute_facts, load

MAYA = "maya.okafor@pinecrest.example"


@pytest.fixture(scope="module")
def brightdesk():
    return load("brightdesk")


def test_maya_is_stuck_because_of_failed_exports(brightdesk):
    facts, prov = compute_facts(brightdesk.customers[MAYA], "brightdesk")
    j = stage("brightdesk", facts, prov)
    assert j.stage == "stuck"
    first = j.because[0]
    assert first["fact"] == "failed_exports_30d" and first["value"] == 5
    assert len(first["refs"]) == 5 and all(r.startswith("events.jsonl#L") for r in first["refs"])


# Measured on the seeded demo data (python -m pheri.journey): Brightdesk 88.8%, Kettle 100%.
# At-risk Brightdesk customers who never mention price look exactly like quiet or healthy ones
# in the data, so code cannot see them; the floor sits just under what we measured.
def test_brightdesk_accuracy_floor():
    acc = accuracy("brightdesk")
    print(acc.report())
    assert acc.total == 240
    assert acc.rate >= 0.88
    per = acc.per_stage()
    for clear in ("onboarding", "stuck", "expanding"):  # these have a signal no other stage has
        assert per[clear][0] == per[clear][1], acc.report()


def test_kettle_accuracy_floor():
    acc = accuracy("kettle")
    print(acc.report())
    assert acc.total == 300
    assert acc.rate >= 0.99


def test_every_customer_gets_a_known_stage_with_reasons(brightdesk):
    for j in stages(brightdesk).values():
        assert j.stage in STAGES["brightdesk"]
        assert j.because and all("fact" in b and "refs" in b for b in j.because)


def _bd(**over):
    base = {"days_since_signup": 200, "failed_exports_30d": 0, "price_complaints": 0, "renewal_in_days": 10,
            "seat_limit_hits_30d": 0, "active_days_30d": 8, "days_quiet": 1, "seats": 5}
    return {**base, **over}


def test_first_matching_rule_wins():
    assert stage("brightdesk", _bd()).stage == "healthy"
    assert stage("brightdesk", _bd(days_since_signup=5, failed_exports_30d=3)).stage == "onboarding"
    assert stage("brightdesk", _bd(failed_exports_30d=1, price_complaints=1)).stage == "stuck"
    assert stage("brightdesk", _bd(price_complaints=1, seat_limit_hits_30d=1)).stage == "at_risk_renewal"
    assert stage("brightdesk", _bd(price_complaints=1, renewal_in_days=90)).stage == "healthy"
    assert stage("brightdesk", _bd(active_days_30d=0, days_quiet=40)).stage == "quiet"


def _kc(**over):
    base = {"days_since_signup": 300, "orders": 6, "days_since_last_order": 20, "subscription": None,
            "gift_only": False, "days_since_cart_abandoned": None}
    return {**base, **over}


def test_kettle_rules():
    assert stage("kettle", _kc()).stage == "loyal"
    assert stage("kettle", _kc(subscription="monthly", days_since_last_order=100)).stage == "subscriber"
    assert stage("kettle", _kc(days_since_cart_abandoned=2)).stage == "cart_abandoner"
    # They came back and ordered after leaving the cart: not an abandoner any more.
    assert stage("kettle", _kc(days_since_cart_abandoned=5, days_since_last_order=1)).stage == "loyal"
    assert stage("kettle", _kc(days_since_signup=10, orders=0, days_since_last_order=None)).stage == "new"
    assert stage("kettle", _kc(orders=0, days_since_last_order=None)).stage == "lapsing"
    assert stage("kettle", _kc(days_since_last_order=61)).stage == "lapsing"
    assert stage("kettle", _kc(gift_only=True)).stage == "gift_buyer"
