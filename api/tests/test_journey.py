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


# Measured on the seeded demo data (python -m pheri.journey): Brightdesk 92.1%, Kettle 100%.
# Day 4: at-risk customers' usage now falls before renewal (synth.py), and a rule sees it: at-risk
# recall went from 23/42 to 35/42. Those who went silent look exactly like quiet ones; the floor
# sits just under what we measured.
def test_brightdesk_accuracy_floor():
    acc = accuracy("brightdesk")
    print(acc.report())
    assert acc.total == 240
    assert acc.rate >= 0.92
    ok, n = acc.per_stage()["at_risk_renewal"]
    assert ok / n >= 0.83
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
            "seat_limit_hits_30d": 0, "active_days_30d": 8, "days_quiet": 1, "seats": 5, "usage_change_pct": 0}
    return {**base, **over}


def test_first_matching_rule_wins():
    assert stage("brightdesk", _bd()).stage == "healthy"
    assert stage("brightdesk", _bd(days_since_signup=5, failed_exports_30d=3)).stage == "onboarding"
    assert stage("brightdesk", _bd(failed_exports_30d=1, price_complaints=1)).stage == "stuck"
    assert stage("brightdesk", _bd(price_complaints=1, seat_limit_hits_30d=1)).stage == "at_risk_renewal"
    assert stage("brightdesk", _bd(price_complaints=1, renewal_in_days=90)).stage == "healthy"
    assert stage("brightdesk", _bd(active_days_30d=0, days_quiet=40)).stage == "quiet"
    # Usage falling before renewal: at risk; gone entirely is quiet; with renewal far off it is not a renewal risk.
    assert stage("brightdesk", _bd(usage_change_pct=-75, active_days_30d=2)).stage == "at_risk_renewal"
    assert stage("brightdesk", _bd(usage_change_pct=-100, active_days_30d=0)).stage == "quiet"
    assert stage("brightdesk", _bd(usage_change_pct=-75, active_days_30d=2, renewal_in_days=60)).stage == "healthy"
    assert stage("brightdesk", _bd(usage_change_pct=-40, active_days_30d=4)).stage == "healthy"
    assert stage("brightdesk", _bd(usage_change_pct=None, active_days_30d=2)).stage == "healthy"  # no history
    assert stage("brightdesk", _bd(usage_change_pct=-75, seat_limit_hits_30d=1)).stage == "expanding"


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


def test_the_usage_fall_changes_only_at_risk_customers(tmp_path):
    """synth.py's fix for at-risk customers runs on its own random stream: everyone else, Maya included,
    is identical value for value, and every other file is identical byte for byte."""
    import json

    from datetime import timedelta

    from pheri.synth import TODAY, generate

    generate(tmp_path / "off", fall_before_renewal=False)
    generate(tmp_path / "on")
    for slug in ("brightdesk", "kettle"):
        for f in (tmp_path / "off" / slug).iterdir():
            if not (slug == "brightdesk" and f.name == "events.jsonl"):
                assert f.read_bytes() == (tmp_path / "on" / slug / f.name).read_bytes(), f.name
    truth = json.loads((tmp_path / "on" / "brightdesk" / "_truth.json").read_text(encoding="utf-8"))["stages"]

    def by_customer(folder):
        out = {}
        for line in (folder / "brightdesk" / "events.jsonl").read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            out.setdefault(e["user"].strip().lower(), []).append(line)
        return out

    off, on = by_customer(tmp_path / "off"), by_customer(tmp_path / "on")
    changed = {k for k in off.keys() | on.keys() if off.get(k) != on.get(k)}
    assert changed and {truth[k] for k in changed} == {"at_risk_renewal"}
    assert off["maya.okafor@pinecrest.example"] == on["maya.okafor@pinecrest.example"]
    start = (TODAY - timedelta(days=30)).isoformat()

    def recent(lines):
        return {x for x in lines if json.loads(x)["ts"][:10] >= start}

    for k in changed:  # in the last 30 days they only lost events; before that they gained a usual pace
        assert recent(on[k]) <= recent(off[k])
