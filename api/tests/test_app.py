"""The HTTP API, end to end through FastAPI's test client. Mock mode only: no network, no spend."""

import re
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from pheri.config import Settings
from pheri.llm import LLM
from pheri.profile import compute_facts, load

MAYA = "maya.okafor@pinecrest.example"
BD = "/businesses/brightdesk"
FIRST_MONTH = "the customer is 22 days in; no discounts in the first 30 days"


@pytest.fixture
def llm(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PHERI_BASETEN_JSON", raising=False)
    return LLM(Settings())


@pytest.fixture
def client(llm):
    from pheri.app import create_app

    return TestClient(create_app(llm))


def c(key: str) -> str:
    return f"{BD}/customers/{quote(key)}"


@pytest.fixture(scope="module")
def veteran():
    """A Brightdesk customer well past their first month: a discount is theirs to have."""
    ds = load("brightdesk")
    return next(k for k, cu in ds.customers.items() if compute_facts(cu, "brightdesk")[0]["days_since_signup"] > 90)


@pytest.fixture(scope="module")
def attacker():
    ds = load("brightdesk")
    return next(cu.key for cu in ds.customers.values() if any(s.id == "T1098" for s in cu.sources))


# ---- the basics ---------------------------------------------------------------------
def test_health_and_businesses(client):
    from pheri.verify import CODE_CHECKS

    assert client.get("/health").json() == {"ok": True, "mode": "mock", "public_demo": False,
                                            "code_checks": len(CODE_CHECKS)}
    assert [b["slug"] for b in client.get("/businesses").json()] == ["brightdesk", "birgunj"]
    assert client.get("/businesses/acme/customers").status_code == 404


def test_live_mode_is_refused_unless_asked_for(monkeypatch, tmp_path):
    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "live")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("PHERI_API_ALLOW_LIVE", raising=False)
    with pytest.raises(RuntimeError, match="mock mode"):
        create_app()


# ---- customers -------------------------------------------------------------------------
def test_customers_with_their_stage(client):
    body = client.get(f"{BD}/customers", params={"stage": "stuck", "limit": 500}).json()
    assert body["total"] == 35 and all(x["stage"] == "stuck" for x in body["items"])
    maya = next(x for x in body["items"] if x["key"] == MAYA)
    assert maya["because"][0] == {"fact": "failed_exports_30d", "value": 5}
    page = client.get(f"{BD}/customers", params={"limit": 10, "offset": 230}).json()
    assert page["total"] == 240 and len(page["items"]) == 10


def test_one_customer_and_their_profile(client, llm, monkeypatch):
    one = client.get(c(MAYA)).json()
    assert one["journey"]["stage"] == "stuck" and one["facts"]["days_since_signup"] == 22
    assert client.get(c("nobody@nowhere.example")).status_code == 404
    calls = []
    real = llm.complete
    monkeypatch.setattr(llm, "complete", lambda m, **kw: calls.append(kw["purpose"]) or real(m, **kw))
    p = client.get(f"{c(MAYA)}/profile").json()
    assert p["facts"]["failed_exports"] == 5 and p["insights"]["blockers"]
    client.get(f"{c(MAYA)}/profile")
    assert calls == ["profile_insights"]  # read once, then served from memory


# ---- decision, approvals --------------------------------------------------------------
def test_maya_decision_then_approval(client):
    out = client.post(f"{c(MAYA)}/decision").json()
    assert out["decision"]["action"] == "send_help" and out["action"]["status"] == "awaiting_approval"
    first = out["prechecks"][0]  # refused by the owner's rule, and by the middle-step check of the plan
    assert first["action"] == "offer_discount" and not first["allowed"] and first["violations"][0] == FIRST_MONTH
    assert out["verification"]["passed"] and out["action"]["payload"]["verification"]["passed"]
    assert {e["kind"] for e in out["evidence"]} == {"fact", "quote"}
    q = client.get(f"{BD}/approvals").json()
    assert [x["action"]["id"] for x in q] == [out["action"]["id"]]
    done = client.post(f"{BD}/approvals/{q[0]['id']}/approve", json={"by": "owner:aditi"})
    assert done.status_code == 200 and done.json()["status"] == "executed"
    again = client.post(f"{BD}/approvals/{q[0]['id']}/approve", json={"by": "owner:aditi"})
    assert again.status_code == 409
    assert client.post(f"{BD}/approvals/nope/approve", json={"by": "owner"}).status_code == 404
    assert client.post(f"{BD}/approvals/{q[0]['id']}/approve", json={"by": ""}).status_code == 422  # who decides


def test_reject_with_a_note(client):
    client.post(f"{c(MAYA)}/decision")
    pid = client.get(f"{BD}/approvals").json()[0]["id"]
    done = client.post(f"{BD}/approvals/{pid}/reject", json={"by": "owner:aditi", "note": "I'll call her"}).json()
    assert done["status"] == "rejected" and client.get(f"{BD}/approvals").json() == []
    trail = client.get(f"{BD}/audit", params={"subject_id": done["id"]}).json()
    assert trail[-1]["event"] == "rejected" and trail[-1]["details"]["note"] == "I'll call her"


def test_an_attack_becomes_an_escalation_not_an_action(client, attacker):
    out = client.post(f"{c(attacker)}/decision").json()
    assert out["skipped"] in ("escalated", "open_escalation")
    q = client.get(f"{BD}/approvals").json()
    assert [x["action"]["kind"] for x in q] == ["escalate_to_human"]
    closed = client.post(f"{BD}/approvals/{q[0]['id']}/approve", json={"by": "owner:aditi"}).json()
    assert closed["status"] == "executed"  # the owner read it; nothing went to the customer


# ---- the discount check and the rules ---------------------------------------------------------
def test_offer_a_discount_check(client, veteran):
    maya = client.post(f"{c(MAYA)}/discount-check", json={"discount_pct": 10}).json()
    assert maya["allowed"] is False and maya["violations"] == [FIRST_MONTH]
    assert client.post(f"{c(veteran)}/discount-check", json={"discount_pct": 10}).json()["allowed"] is True
    assert client.post(f"{c(MAYA)}/discount-check", json={"discount_pct": 0}).status_code == 422
    assert client.post(f"{c(MAYA)}/discount-check", json={"discount_pct": 150}).status_code == 422


def test_rules_add_confirm_list_and_enforce(client, veteran):
    seeded = client.get(f"{BD}/rules").json()
    assert [r["active"] for r in seeded] == [True]
    assert seeded[0]["described"] == ["Block any discount for customers in their first 30 days."]
    draft = client.post(f"{BD}/rules", json={"text": "No discounts above 15%", "by": "owner:aditi"})
    assert draft.status_code == 201 and draft.json()["active"] is False and draft.json()["confirmable"]
    rid = draft.json()["id"]
    assert client.post(f"{c(veteran)}/discount-check", json={"discount_pct": 20}).json()["allowed"]  # not yet
    confirmed = client.post(f"{BD}/rules/{rid}/confirm", json={"by": "owner:aditi"}).json()
    assert confirmed["active"] and confirmed["described"] == ["Block any discount over 15%."]
    blocked = client.post(f"{c(veteran)}/discount-check", json={"discount_pct": 20}).json()
    assert not blocked["allowed"] and blocked["violations"] == ["a 20% discount is over the 15% limit"]
    assert len(client.get(f"{BD}/rules").json()) == 2


def test_a_rule_code_cannot_enforce_cannot_be_confirmed(client):
    draft = client.post(f"{BD}/rules", json={"text": "Always be polite to customers.", "by": "owner"}).json()
    assert draft["unsupported"] == ["Always be polite to customers."] and not draft["confirmable"]
    assert client.post(f"{BD}/rules/{draft['id']}/confirm", json={"by": "owner"}).status_code == 409
    assert client.post(f"{BD}/rules/nope/confirm", json={"by": "owner"}).status_code == 404
    assert client.post(f"{BD}/rules", json={"text": "x" * 600, "by": "owner"}).status_code == 422


# ---- private mode ------------------------------------------------------------------------------
def test_the_private_mode_switch(client, llm, monkeypatch):
    off = {"guard": False, "profile": False, "decide": False, "rules": False}
    assert client.get(f"{BD}/private-mode").json() == off
    assert client.put(f"{BD}/private-mode", json={"by": "owner:aditi", "full": True}).json() == {
        k: True for k in off}
    calls = []
    real = llm.complete
    monkeypatch.setattr(llm, "complete", lambda m, **kw: calls.append(kw.get("provider", "meta")) or real(m, **kw))
    out = client.post(f"{c(MAYA)}/decision").json()
    assert out["private"] and set(calls) == {"baseten"}  # full private mode: nothing to the Meta API
    assert client.get("/businesses/birgunj/private-mode").json() == off  # per business


# ---- what worked, and spend ----------------------------------------------------------------------
def test_twin_results_and_the_learned_report(client):
    twin = client.get(f"{BD}/twin").json()
    assert twin["customers"] == 5000 and twin["overall"]["verdict"] == "works" and len(twin["stages"]) == 6
    assert client.get(f"{BD}/twin", params={"seed": 99}).status_code == 404
    rep = client.get(f"{BD}/learned").json()
    assert rep["rejected"] == [] and len(rep["findings"]) == 6
    assert rep["markdown"].startswith("## What Pheri learned")
    assert rep["source"] == "stand-in"  # never credited to Muse Wonder unless Wonder wrote it


def test_spend_summary(client):
    client.post(f"{c(MAYA)}/decision")
    s = client.get("/spend").json()
    assert s["mode"] == "mock" and set(s["providers"]) == {"meta", "baseten"}
    meta = s["providers"]["meta"]
    assert meta["settled_usd"] == 0 and meta["cap_usd"] > 0  # mock mode spends nothing
    assert meta["remaining_usd"] == pytest.approx(max(0.0, meta["cap_usd"] - meta["offset_usd"]))
    assert s["by_purpose"] and all(r["usd"] == 0 for r in s["by_purpose"])  # mock calls are counted, at $0
    live = s["live_runs"]  # this week's live runs, a checked-in snapshot of totals only
    if live:
        for p, t in live["providers"].items():
            assert sum(r["usd"] for r in live["calls"] if r["provider"] == p) == pytest.approx(t["settled_usd"], abs=1e-4)
            assert t["settled_usd"] <= t["cap_usd"]


# ---- what the web app reads --------------------------------------------------------------
def test_next_steps_one_card_per_showcase_customer(client):
    cards = client.get(f"{BD}/next-steps").json()
    assert cards[0]["customer"]["key"] == MAYA and cards[0]["decision"]["action"] == "send_help"
    stages_shown = [x["customer"]["stage"] for x in cards]
    assert len(stages_shown) == len(set(stages_shown)) == 6  # one per stage, Maya the stuck one
    maya = cards[0]
    assert maya["approval"]["decision"] == "pending" and maya["action"]["mode"] == "ask_owner"
    assert {e["kind"] for e in maya["evidence"]} == {"fact", "quote"} and maya["cost_usd"] == 0
    client.post(f"{BD}/approvals/{maya['approval']['id']}/approve", json={"by": "owner:aditi"})
    again = client.get(f"{BD}/next-steps").json()[0]
    assert again["action"]["status"] == "executed" and again["approval"]["decision"] == "approved"  # live status


def test_replies_with_label_language_and_escalations(client):
    replies = client.get(f"{BD}/replies").json()
    by_id = {r["source_id"]: r for r in replies}
    assert by_id["T1098"]["label"] == "attack" and by_id["T1098"]["escalation"]["status"] == "awaiting_approval"
    assert "override_rules" in by_id["T1098"]["screen_before"]
    assert {r["language"] for r in replies} >= {"en", "es", "hi", "ne", "pt"}  # every language in the data
    assert all(r["text"] and r["summary"] for r in replies)


def test_runs_on_names_the_model_for_each_step(client):
    meta = client.get(f"{BD}/private-mode/runs-on").json()
    assert meta["full_private"] is False and meta["steps"]["decide"]["model"] == "muse-spark-1.3"
    client.put(f"{BD}/private-mode", json={"by": "owner", "full": True})
    private = client.get(f"{BD}/private-mode/runs-on").json()
    assert private["full_private"] and private["steps"]["guard"]["model"] == "meta-models/muse-spark-open-1026"
    assert "open-weight model, served by a partner" in private["steps"]["guard"]["label"]


def test_the_discount_refusal_comes_with_the_rules_plain_words(client):
    out = client.post(f"{c(MAYA)}/discount-check", json={"discount_pct": 10}).json()
    assert out["refused_by"] == [{"rule_id": out["refused_by"][0]["rule_id"],
                                  "source_text": "Never offer discounts in a customer's first month.",
                                  "described": ["Block any discount for customers in their first 30 days."],
                                  "reason": FIRST_MONTH}]


def test_the_stored_decision_and_its_trace(client):
    first = client.get(f"{c(MAYA)}/decision").json()
    again = client.get(f"{c(MAYA)}/decision").json()
    assert first["action"]["id"] == again["action"]["id"]  # read, not decided twice
    assert len(client.get(f"{BD}/approvals").json()) == 1
    t = client.get(f"{c(MAYA)}/trace").json()
    assert [x["turn"] for x in t["turns"]] == [1, 2, 3, 4] and t["prechecks"][0]["allowed"] is False
    assert t["action"]["rule_check"]["allowed"] and t["action"]["mode"] == "ask_owner"
    fresh = client.post(f"{c(MAYA)}/decision").json()
    assert client.get(f"{c(MAYA)}/decision").json()["action"]["id"] == fresh["action"]["id"]  # replaced


# ---- who decided: live, recorded, or the stand-in ----------------------------------------
def test_a_mock_card_says_the_stand_in_decided(client):
    card = client.get(f"{c(MAYA)}/decision").json()
    assert card["decided_by"] == {"provider": "meta", "model": "muse-spark-1.3", "source": "stand-in"}
    assert card["cost_usd"] == 0 and card["turns"] == 4


def test_replay_serves_mayas_recorded_live_run(monkeypatch, tmp_path):
    """The demo's recording still matches the code: if a prompt or the data changes, re-record
    (python scripts/record_demo.py --live) rather than let the site fall back to the stand-in."""
    from pheri.app import create_app
    from pheri.config import REPO_ROOT

    monkeypatch.setenv("PHERI_LLM_MODE", "replay")
    monkeypatch.setenv("PHERI_LLM_REPLAY", str(REPO_ROOT / "data" / "recorded" / "llm.jsonl"))
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("PHERI_LLM_RECORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    llm = LLM(Settings())
    card = TestClient(create_app(llm)).get(f"{c(MAYA)}/decision").json()
    assert card["decided_by"] == {"provider": "meta", "model": "muse-spark-1.3", "source": "recorded"}
    d = card["decision"]
    assert d["action"] == "send_help" and "90%" in d["message"] and "weekly client reports" in d["message"]
    assert "renews in 8 days" in d["why_now"] and re.search(r"\b(she|her)\b", f"{d['why_this']} {d['why_now']}")
    assert "Maya" not in d["message"].split(",", 1)[1]  # "you" to her face: her name only in the greeting
    assert d["message"].startswith("Hi Maya, your weekly report")  # the model wrote "Your"; code lowercased it
    assert card["verification"]["passed"] and card["verification"]["judge"] and card["verification"]["judge_recorded"]
    assert "inbox" not in d["message"]  # one problem: the export behind her stage, not her second ticket
    assert card["cost_usd"] > 0 and card["turns"] == 3  # what the live run paid, for its turns
    assert llm.ledger.totals("meta").settled_usd == 0  # replaying it spent nothing
    api = TestClient(create_app(llm))
    assert api.get("/health").json()["mode"] == "replay"
    # Muse Wonder's report on the 5,000-customer twin is recorded too: its first headline stated no result, code
    # sent the reason back, and the second attempt passed every check.
    rep = api.get(f"{BD}/learned").json()
    assert rep["source"] == "recorded" and rep["model"] == "muse-wonder-1.0" and len(rep["findings"]) == 6
    assert [(a["attempt"], a["passed"], a["rejected"]) for a in rep["attempts"]] == [(1, False, ["headline"]), (2, True, [])]
    assert rep["rejected"] == [] and not rep["headline"].startswith("Across 5000")  # Wonder's own, checked
    cards = api.get(f"{BD}/next-steps").json()
    for card in cards:
        assert card["decided_by"]["source"] == "recorded", card["customer"]["name"]
        assert card["verification"]["judge_recorded"], card["customer"]["name"]  # the judge's verdicts too
    # A real failure, kept: the judge rejected claims in all three of Aarav's drafts, so he is with the owner.
    held = [c["customer"]["name"] for c in cards if not c["verification"]["passed"]]
    assert held == ["Aarav Silva"]
    aarav = next(c for c in cards if c["customer"]["name"] == "Aarav Silva")
    assert aarav["verification"]["caught_by"] == "judge" and aarav["verification"]["attempts"] == 3
    assert aarav["action"]["status"] == "awaiting_approval" and not aarav["action"]["payload"]["verification"]["passed"]
    # The judge is a soft check: the owner may send Aarav's draft anyway, on the record; a plain approve is refused.
    v = aarav["action"]["payload"]["verification"]
    assert v["soft_failed"] == ["judge"] and v["hard_failed"] == [] and v["judge_flagged"] == 2
    pid = aarav["approval"]["id"]
    refused = api.post(f"{BD}/approvals/{pid}/approve", json={"by": "owner:aditi"})
    assert refused.status_code == 409 and "owner override" in refused.json()["detail"]
    sent = api.post(f"{BD}/approvals/{pid}/approve", json={"by": "owner:aditi", "override": True}).json()
    assert sent["status"] == "executed"
    card = next(c for c in api.get(f"{BD}/next-steps").json() if c["customer"]["name"] == "Aarav Silva")
    assert card["override"]["summary"] == "judge flagged 2 claims" and card["override"]["by"] == "owner:aditi"
    assert card["override"]["line"] == "Sent by owner override: judge flagged 2 claims"
    assert card["override"]["text"] == aarav["decision"]["message"] and card["override"]["overridden"] == ["judge"]
    log = api.get(f"{BD}/audit", params={"subject_id": sent["id"]}).json()
    assert [e["event"] for e in log][-3:] == ["approved", "owner_override", "executed"]
    totals = api.get(f"{BD}/verification").json()
    assert totals["decisions"] == 6 and totals["sent_to_owner"] == 1 and totals["drafts"] > totals["decisions"]


@pytest.mark.xfail(strict=True, reason="Birgunj's night is recorded once, after the scheduling change (plan, Step 3) "
                                       "changes what the decide tools return; strict: remove this mark when it passes")
def test_replay_serves_birgunjs_recorded_night(monkeypatch, tmp_path):
    from pheri.app import create_app
    from pheri.config import REPO_ROOT

    monkeypatch.setenv("PHERI_LLM_MODE", "replay")
    monkeypatch.setenv("PHERI_LLM_REPLAY", str(REPO_ROOT / "data" / "recorded" / "llm.jsonl"))
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("PHERI_LLM_RECORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api = TestClient(create_app(LLM(Settings())))
    cards = api.get("/businesses/birgunj/next-steps").json()
    assert len(cards) >= 20
    for card in cards:
        assert card["decided_by"]["source"] == "recorded", card["customer"]["name"]
        assert card["verification"]["judge_recorded"], card["customer"]["name"]
    assert api.get("/businesses/birgunj/learned").json()["source"] == "recorded"


# ---- the public demo: a sandbox per visitor, and no pretend owner ------------------------------------
@pytest.fixture
def public(llm, monkeypatch):
    from pheri import app as app_module

    monkeypatch.setenv("PHERI_PUBLIC_DEMO", "1")
    return app_module, app_module.create_app(LLM(Settings()))


def test_each_visitor_gets_their_own_sandbox_and_the_log_names_no_owner(public):
    app_module, app = public
    alice, bob = TestClient(app), TestClient(app)
    assert alice.get("/health").json()["public_demo"] is True
    pid = alice.get(f"{BD}/next-steps") and alice.get(f"{BD}/approvals").json()[0]["id"]
    done = alice.post(f"{BD}/approvals/{pid}/approve", json={"by": "owner:aditi"}).json()  # the name sent is ignored
    assert done["status"] == "executed"
    approved = [e for e in alice.get(f"{BD}/audit").json() if e["event"] == "approved"]
    assert [e["actor"] for e in approved] == [app_module.DEMO_ACTOR] == ["demo visitor (public demo, no login)"]
    assert pid in [a["id"] for a in bob.get(f"{BD}/approvals").json()]  # Bob's copy is untouched
    assert all(e["event"] != "approved" for e in bob.get(f"{BD}/audit").json())
    rules = alice.get(f"{BD}/rules").json()
    assert rules[0]["confirmed_by"] == app_module.DEMO_SETUP  # the starting rules: the demo's, not an owner's
    assert alice.cookies.get(app_module.SANDBOX_COOKIE) != bob.cookies.get(app_module.SANDBOX_COOKIE)


def test_reset_demo_puts_only_this_visitors_sandbox_back(public):
    _, app = public
    alice, bob = TestClient(app), TestClient(app)
    for v in (alice, bob):
        v.get(f"{BD}/next-steps")
        pid = v.get(f"{BD}/approvals").json()[0]["id"]
        v.post(f"{BD}/approvals/{pid}/reject", json={"by": "x"})
    assert alice.post("/demo/reset").json() == {"reset": True, "public_demo": True}
    assert alice.get(f"{BD}/approvals").json() and not any(
        e["event"] == "rejected" for e in alice.get(f"{BD}/audit").json())
    assert any(e["event"] == "rejected" for e in bob.get(f"{BD}/audit").json())  # Bob's stays as he left it


def test_at_most_max_sandboxes_the_idle_longest_dropped_and_each_expires(public, monkeypatch):
    app_module, app = public
    monkeypatch.setattr(app_module, "MAX_SANDBOXES", 2)
    state = app.state.pheri
    visitors = [TestClient(app) for _ in range(3)]
    for v in visitors:
        v.get(f"{BD}/approvals")
    ids = [v.cookies.get(app_module.SANDBOX_COOKIE) for v in visitors]
    assert list(state.sandboxes) == ids[1:]  # the first, idle longest, was dropped
    # The web app's server forwards the cookie as a header: the same sandbox.
    raw = TestClient(app)
    raw.get(f"{BD}/approvals", headers={app_module.SANDBOX_HEADER: ids[2]})
    assert list(state.sandboxes)[-1] == ids[2] and len(state.sandboxes) == 2
    monkeypatch.setattr(app_module, "SANDBOX_IDLE_S", -1)  # every sandbox is now past its 30 minutes
    visitors[1].get(f"{BD}/approvals")
    assert list(state.sandboxes) == [ids[1]]  # the others expired; this one was made again, fresh
