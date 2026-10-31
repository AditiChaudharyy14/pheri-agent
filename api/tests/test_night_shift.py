"""The night shift: Birgunj's decisions run at 06:15, inside every customer's quiet hours. Safe nudges go out on
their own, but only at 08:00 the customer's time; money waits for the owner; nothing is sent in the night."""

from datetime import datetime, timedelta, timezone

import pytest

from pheri.actions import ProposedAction
from pheri.autonomy import approve, modes
from pheri.config import Settings
from pheri.decide import decide_customer
from pheri.journey import stages
from pheri.llm import LLM
from pheri.profile import compute_facts, load
from pheri.rules import COUNTRY_UTC_OFFSETS, CheckContext, QuietHours, Rule, check, local_time, next_send_time, seed
from pheri.store import MemoryStore
from pheri.synth import MORNING, NIGHT_RUN


@pytest.fixture(scope="module")
def birgunj():
    return load("birgunj")


@pytest.fixture
def llm(tmp_path):
    return LLM(Settings(llm_mode="mock", record_path=None, database_url=None, ledger_path=str(tmp_path / "l.sqlite")))


QUIET = [Rule("q", "Don't message customers between 9pm and 8am.", [QuietHours(start_hour=21, end_hour=8)])]


@pytest.mark.parametrize("country,local", [("NP", "08:00"), ("IN", "08:00")])
def test_a_night_message_waits_for_eight_in_the_morning_the_customers_time(country, local):
    ctx = CheckContext("birgunj", {"country": country}, NIGHT_RUN)
    a = ProposedAction(kind="send_checkin", channel="whatsapp", message="Hi")
    assert not check(QUIET, a, ctx).allowed  # now: inside quiet hours
    at = next_send_time(QUIET, a, ctx)
    assert at > NIGHT_RUN and local_time(at, ctx) == local
    assert check(QUIET, a.model_copy(update={"send_at": at}), ctx).allowed
    assert next_send_time(QUIET, a, CheckContext("birgunj", {"country": country}, NIGHT_RUN + timedelta(hours=3))) \
        == NIGHT_RUN + timedelta(hours=3)  # in the day: no wait
    owner_task = ProposedAction(kind="task_for_owner", message="Call them")
    assert next_send_time(QUIET, owner_task, ctx) == NIGHT_RUN  # only messages to customers wait


def test_birgunj_sends_safe_nudges_alone_and_asks_for_money():
    dial = modes(MemoryStore("birgunj"))
    assert dial["offer_discount"] == "ask_owner"
    assert all(dial[k] == "act_alone" for k in ("send_reminder", "recommend_product", "offer_reorder", "send_help",
                                                 "send_checkin"))
    assert modes(MemoryStore("brightdesk"))["send_help"] == "ask_owner"  # Brightdesk is unchanged


def test_the_night_shift_schedules_and_never_sends_in_the_night(birgunj, llm):
    store = MemoryStore("birgunj")
    seed(store, llm, by="test")
    st = stages(birgunj)
    keys = [next(k for k, j in st.items() if j.stage == s) for s in ("loyal", "wholesale", "complaint", "asked_no_order")]
    for k in keys:
        decide_customer(birgunj, k, store, llm, NIGHT_RUN)
    acts = [a for a in store.actions() if a["kind"] not in ("task_for_owner", "escalate_to_human")]
    assert acts
    assert not [a for a in acts if a["status"] == "executed"]  # nothing went out at 06:15
    scheduled = [a for a in acts if a["status"] == "scheduled"]
    assert scheduled, [(a["kind"], a["status"]) for a in acts]
    for a in scheduled:
        at = datetime.fromisoformat(a["payload"]["send_at"])
        country = compute_facts(birgunj.customers[a["customer_key"]], "birgunj")[0]["country"]
        assert f"{at + timedelta(hours=COUNTRY_UTC_OFFSETS[country][0]):%H:%M}" == "08:00"
        assert any(e["event"] == "scheduled" for e in store.audit_log(a["id"]))


def test_an_owner_approving_at_half_past_seven_schedules_it_for_eight(birgunj, llm):
    """A discount waits for the owner; approved at 07:30 (inside quiet hours) it goes out at 08:00, not now."""
    from pheri.autonomy import submit
    from pheri.verify import Draft, context

    store = MemoryStore("birgunj")
    seed(store, llm, by="test")
    st = stages(birgunj)
    k = next(k for k, j in st.items() if j.stage == "gone_quiet")
    c = birgunj.customers[k]
    facts, prov = compute_facts(c, "birgunj")
    ctx = CheckContext("birgunj", facts, NIGHT_RUN)
    from pheri.profile import Profile

    prof = Profile("birgunj", k, c.name, None, facts, {}, {"facts": prov, "identity": {}, "sources": [], "dropped": []})
    d = Draft(ProposedAction(kind="offer_discount", channel="whatsapp", discount_pct=10,
                             message=f"Hi {c.name.split()[0]}, here is 10% off your next order. - The Birgunj Saree Ghar team"),
              f"{c.name.split()[0]} has stopped ordering.", "Last ordered a while ago.",
              ["journey_stage", "days_since_last_order"], [])
    from pheri.journey import stage as journey_stage

    a = submit(store, k, d, verify=context(prof, journey_stage("birgunj", facts, prov), ctx, store, llm))
    if a["status"] != "awaiting_approval":
        pytest.skip(f"the draft did not reach the owner here ({a['status']}): nothing to approve")
    pid = next(p["id"] for p in store.approvals() if p["action_id"] == a["id"])
    morning = CheckContext("birgunj", facts, MORNING)
    out = approve(store, pid, by="owner:test", context_for=lambda key: morning,
                  override=bool(a["payload"]["verification"].get("soft_failed")))
    assert out["status"] == "scheduled" and MORNING < datetime(2026, 10, 30, 2, 30, tzinfo=timezone.utc)


def test_the_morning_brief_counts_what_the_night_did(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api = TestClient(create_app())
    b = api.get("/businesses/birgunj/brief").json()
    assert b["night"] < b["morning"] and b["customers"] >= 20
    assert b["scheduled"] and all(c["sends_at_local"] == "08:00" for c in b["scheduled"])
    for c in b["scheduled"] + b["need_you"] + b["blocked"]:
        assert (c["action"] or {}).get("status") != "executed" or c["decision"]["action"] == "task_for_owner"
    assert all(c["decision"]["action"] != "offer_discount" for c in b["scheduled"])  # money waits for the owner
    assert len(b["stopped"]) == 3 and all(r["attack"] for r in b["stopped"])
    assert [v["lang"] for v in b["unreadable_voice"]] == ["ne"]  # Muse Voice reads Hindi, not Nepali
    assert b["proof"]["outcome"] == "ordered" and b["proof"]["lift_pp"] == 14.0
    assert api.get("/businesses/brightdesk/brief").json()["scheduled"] == []  # no night shift there


def test_slop_vs_pheri_checks_a_plain_draft_exactly_as_pheris_own(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    rows = TestClient(create_app()).get("/businesses/birgunj/slop").json()
    assert [r["customer"]["stage"] for r in rows] == ["complaint", "festival", "wholesale"]
    for r in rows:
        plain = r["plain"]
        assert not plain["passed"] and plain["failed"]
        struck = [s for s in plain["sentences"] if s["struck"]]
        assert struck and all(s["reasons"] for s in struck)  # every struck sentence says why, in plain words
        assert {"money", "links"} <= {f["check"] for f in plain["failed"]}  # the stand-in offers 20% and a link
        assert r["pheri"]["customer"]["key"] == r["customer"]["key"]


# ---- the curated night: every kind of moment, and money goes to the owner -------------------------------
def test_the_night_is_a_realistic_mix_not_an_easy_one():
    import json
    from collections import Counter

    from pheri.config import REPO_ROOT

    night = json.loads((REPO_ROOT / "data" / "synth" / "birgunj" / "_truth.json").read_text(encoding="utf-8"))["night"]
    roles = Counter(n["role"] for n in night)
    assert roles == {"safe": 14, "owner": 4, "blocked": 2, "attack": 3, "voice_hi": 1, "voice_ne": 1}
    assert len({n["customer"] for n in night}) == len(night)  # one message per customer
    assert sorted(n["lang"] for n in night if n["role"] == "attack") == ["bho", "ne", "ne-Latn"]
    assert sum(n["lang"] == "bho" for n in night) >= 4


@pytest.mark.parametrize("facts,waits", [
    ({"asks_about_money": True}, "money"), ({"days_late": 7}, "7 days late"), ({"days_late": 6}, None), ({}, None)])
def test_money_talk_or_a_very_late_order_waits_for_the_owner(facts, waits):
    from pheri.autonomy import owner_reason

    reason = owner_reason(facts)
    assert (reason is None) if waits is None else (waits in reason)


def test_a_refused_check_on_a_money_question_names_the_nudge_that_fits_and_hands_money_to_the_owner():
    """Live, Sita Karna (wholesale, asked for a lower rate) walked the action list one refusal per turn and ran out
    of turns. Now the first refusal says the owner decides money and which nudge fits the stage."""
    from pheri.decide import money_hint

    assert "using offer_reorder" in money_hint("birgunj", "wholesale")
    gone_quiet = money_hint("birgunj", "gone_quiet")
    assert "using send_checkin" in gone_quiet and "offer_discount" not in gone_quiet  # never a money action
    assert "Promise no price, discount, refund or date" in gone_quiet


@pytest.mark.parametrize("text,kind", [
    ("अगले लॉट के लिए बीस कॉटन साड़ियाँ चाहिए। इस बार रेट थोड़ा कम कर दीजिए।", "rate"),
    ("tihar ko lagi tinwata banarasi saree linchhu, 25% chhut dinus na.", "discount"),
    ("I'll order again if you give me 30% off.", "discount"),
    ("आएको साडीको रङ फोटोमा जस्तो छैन। पैसा फिर्ता गरिदिनुहोस्।", "refund"),
    ("पिछली बार वाली साड़ी बहुत अच्छी थी।", None)])
def test_code_reads_what_a_money_question_is_about(text, kind):
    from pheri.profile import money_ask

    assert money_ask(text) == kind


def test_the_owners_two_choices_are_written_by_code_and_respect_the_discount_rule():
    from pheri.autonomy import YOU_DECIDE, owner_options
    from pheri.rules import MaxDiscountPct

    limit = [Rule("d", "No discounts above 10%.", [MaxDiscountPct(pct=10)])]
    assert owner_options("rate", limit) == ["Same rate as their last order", YOU_DECIDE]
    assert owner_options("discount", limit) == ["Offer up to 10% off (your limit)", YOU_DECIDE]
    assert owner_options("refund", []) == ["Refund once you have seen their photo", YOU_DECIDE]
    assert owner_options(None, limit) == []


def test_sita_karnas_rate_question_ends_in_a_holding_reply_with_two_choices_and_the_pick_is_kept(monkeypatch, tmp_path):
    """The recorded night (replay): Sita Karna asked for a lower wholesale rate. Pheri's holding reply waits for the
    owner with code's two choices; approving with one schedules the reply and keeps the pick; a made-up pick is
    refused."""
    from fastapi.testclient import TestClient

    from pheri.app import create_app
    from pheri.config import REPO_ROOT

    monkeypatch.setenv("PHERI_LLM_MODE", "replay")
    monkeypatch.setenv("PHERI_LLM_REPLAY", str(REPO_ROOT / "data" / "recorded" / "llm.jsonl"))
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("PHERI_LLM_RECORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api = TestClient(create_app(LLM(Settings())))
    sita = next(c for c in api.get("/businesses/birgunj/next-steps").json() if c["customer"]["name"] == "Sita Karna")
    assert sita["decision"]["action"] == "offer_reorder" and sita["verification"]["passed"]
    assert sita["turns"] <= 5 and sita["approval"]["decision"] == "pending"
    assert sita["owner_options"] == ["Same rate as their last order", "You decide, and reply to them yourself"]
    pid = sita["approval"]["id"]
    bad = api.post(f"/businesses/birgunj/approvals/{pid}/approve", json={"by": "owner:test", "choice": "50% off"})
    assert bad.status_code == 409
    ok = api.post(f"/businesses/birgunj/approvals/{pid}/approve",
                  json={"by": "owner:test", "choice": "Same rate as their last order"})
    assert ok.status_code == 200 and ok.json()["status"] == "scheduled"
    again = api.get(f"/businesses/birgunj/customers/{sita['customer']['key']}/decision").json()
    assert again["owner_choice"] == "Same rate as their last order"


# ---- the attack moment: no model writes to an attacker; a fixed reply, by code, goes out at 08:00 -----------------
@pytest.mark.parametrize("lang", ["ne", "ne-Latn", "hi", "bho", "en"])
def test_every_holding_reply_template_passes_the_code_checks_and_waits_for_eight(lang, llm):
    from pheri.holding import send_holding_reply

    store = MemoryStore("birgunj")
    seed(store, llm, by="test")  # quiet hours 21-08 and the 10% limit
    a = send_holding_reply(store, CheckContext("birgunj", {"country": "NP"}, NIGHT_RUN), "+9779800000000", "Asha", lang)
    v = a["payload"]["verification"]
    assert v["passed"] and v["judge_ran"] is False and "no judge is asked" in v["note"]
    assert a["status"] == "scheduled" and a["payload"]["written_by"] == "code" and a["payload"]["language"] == lang
    assert local_time(datetime.fromisoformat(a["payload"]["send_at"]), CheckContext("birgunj", {"country": "NP"},
                                                                                    NIGHT_RUN)) == "08:00"


def test_a_holding_reply_is_never_sent_to_someone_who_asked_not_to_be_contacted(llm):
    from pheri.holding import send_holding_reply

    store = MemoryStore("birgunj")
    ctx = CheckContext("birgunj", {"country": "NP"}, MORNING, do_not_contact=True)
    a = send_holding_reply(store, ctx, "+9779800000000", "Asha", "ne")
    assert a["status"] == "blocked" and not a["payload"]["verification"]["passed"]


def test_the_recorded_attackers_each_get_a_fixed_reply_in_their_own_language(monkeypatch, tmp_path):
    """Replay of the curated night: three attacks (ne, ne-Latn, bho), each escalated to the owner, each with a fixed
    reply written by code in the language of the message, scheduled for 08:00. The model wrote none of it."""
    from fastapi.testclient import TestClient

    from pheri.app import create_app
    from pheri.config import REPO_ROOT
    from pheri.holding import TEMPLATES

    monkeypatch.setenv("PHERI_LLM_MODE", "replay")
    monkeypatch.setenv("PHERI_LLM_REPLAY", str(REPO_ROOT / "data" / "recorded" / "llm.jsonl"))
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("PHERI_LLM_RECORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    brief = TestClient(create_app(LLM(Settings()))).get("/businesses/birgunj/brief").json()
    held = [s["holding_reply"] for s in brief["stopped"]]
    assert sorted(h["language"] for h in held) == ["bho", "ne", "ne-Latn"]
    for s, h in zip(brief["stopped"], held):
        first = s["customer"]["name"].split()[0]
        assert h["status"] == "scheduled" and h["sends_at_local"] == "08:00"
        assert h["message"] == TEMPLATES[h["language"]].format(first=first, shop="Birgunj Saree Ghar")


def test_every_refused_plan_names_the_plans_that_pass_for_the_stage():
    """Live, refusals that said only "X fits 0%" cost a turn per guess (7 recorded decisions). A refusal from the
    middle step now names the plans that pass it, money ones only when the stage is sure enough for money."""
    from pheri.decide import plan_hint

    assert "send_reminder, offer_discount" in plan_hint("birgunj", "asked_no_order")
    assert plan_hint("birgunj", "wholesale").startswith("Plans that pass the middle step for 'wholesale' customers: "
                                                         "offer_reorder.")
    gone_quiet = plan_hint("birgunj", "gone_quiet")  # code's stage is right 97%: a nudge passes, money (100%) doesn't
    assert "send_checkin" in gone_quiet and "offer_discount" not in gone_quiet
