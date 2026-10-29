"""Pheri checks its own work: code checks first, the judge second, the reasons go back, and nothing unverified is sent."""

import json
import re

import pytest

from pheri import llm as llm_module
from pheri.actions import CATALOG, ProposedAction
from pheri.autonomy import approve, queue, set_mode
from pheri.config import REPO_ROOT, Settings
from pheri.decide import PURPOSE, decide, decide_customer
from pheri.journey import stage
from pheri.llm import LLM
from pheri.profile import build_profile, load
from pheri.rules import CheckContext, seed
from pheri.store import MemoryStore
from pheri.synth import NOW
from pheri.verify import (CODE_CHECKS, JUDGE_PURPOSE, THRESHOLDS, Draft, claims, context, middle_step,
                          payload_sha, verify_draft)

MAYA = "maya.okafor@pinecrest.example"
PABLO = "pablo.nasser@brightwater.example"
DRAFTS = [json.loads(x) for x in (REPO_ROOT / "evals" / "drafts.jsonl").read_text(encoding="utf-8").splitlines() if x]


@pytest.fixture
def llm(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PHERI_LLM_RECORD", raising=False)
    return LLM(Settings())


@pytest.fixture(scope="module")
def data():
    return {b: load(b) for b in ("brightdesk", "kettle")}


def _vc(data, llm, business, key, store=None):
    p = build_profile(data[business], key, llm)
    store = store or MemoryStore(business)
    if not store.rules(active_only=False):
        seed(store, llm)
    j = stage(business, p.facts, p.provenance.get("facts"))
    return context(p, j, CheckContext(business, p.facts, NOW), store, llm)


def _draft(d: dict) -> Draft:
    return Draft(ProposedAction(kind=d["action"], channel=d["channel"], discount_pct=d["discount_pct"],
                                message=d["message"], send_at=NOW), d["why_this"], d["why_now"], d["fact_keys"],
                 d["quote_ids"])


def _judge_calls(llm, monkeypatch):
    calls = []
    real = llm.complete
    monkeypatch.setattr(llm, "complete", lambda m, **kw: calls.append(kw["purpose"]) or real(m, **kw))
    return calls


# ---- layer 1: code, one check per broken draft ------------------------------------------
@pytest.mark.parametrize("row", [r for r in DRAFTS if r["expect"] != ["judge"]], ids=lambda r: r["id"])
def test_every_labelled_draft_is_caught_by_its_check_and_clean_ones_pass(row, data, llm):
    v = verify_draft(_draft(row["draft"]), _vc(data, llm, row["business"], row["customer"]))
    failed = {c["name"] for c in v.checks if c["applies"] and not c["passed"]}
    if row["expect"]:
        assert set(row["expect"]) <= failed and v.caught_by == "code" and not v.passed, (row["note"], v.reasons)
        assert not v.judge_ran  # the judge only reads drafts code has passed
    else:
        assert v.passed and v.judge_ran and v.code_checks == len(CODE_CHECKS), v.reasons


def test_the_judge_is_asked_only_after_every_code_check_passes(data, llm, monkeypatch):
    calls = _judge_calls(llm, monkeypatch)
    vc = _vc(data, llm, "brightdesk", MAYA)
    bad = next(r for r in DRAFTS if r["id"] == "B04")["draft"]
    verify_draft(_draft(bad), vc)
    assert JUDGE_PURPOSE not in calls
    good = next(r for r in DRAFTS if r["id"] == "G01")["draft"]
    v = verify_draft(_draft(good), vc)
    assert calls.count(JUDGE_PURPOSE) == 1 and v.judge_model == "meta-models/muse-spark-open-1026"
    verify_draft(_draft(good), vc)  # the same draft again (submit verifies itself): the answer is not paid twice
    assert calls.count(JUDGE_PURPOSE) == 1


def test_the_judge_gets_claims_and_only_the_cited_facts(data, llm, monkeypatch):
    seen = []
    real = llm_module._mock_responders[JUDGE_PURPOSE]
    monkeypatch.setitem(llm_module._mock_responders, JUDGE_PURPOSE, lambda m, s: seen.append(m) or real(m, s))
    good = next(r for r in DRAFTS if r["id"] == "G01")["draft"]
    verify_draft(_draft(good), _vc(data, llm, "brightdesk", MAYA))
    sent = json.loads(seen[0][-1]["content"])
    assert set(sent["cited_facts"]) == set(good["fact_keys"])  # nothing she did not cite
    texts = [c["text"] for c in sent["claims"]]
    assert "Hi Maya" not in " ".join(texts) and "Brightdesk team" not in " ".join(texts)  # no greeting, no sign-off
    assert any("renews in 8 days" in t for t in texts)
    assert [c["id"] for c in sent["claims"]] == [f"c{i + 1}" for i in range(len(texts))]


def test_claims_skip_the_greeting_and_the_sign_off():
    d = Draft(ProposedAction(kind="send_help", channel="email", message="Hi Maya, the fix is ready. Reply to try it. "
                             "— The Brightdesk team"), "Maya is stuck.", "Maya renews soon.", [], [])
    assert claims(d) == ["Maya is stuck.", "Maya renews soon.", "The fix is ready.", "Reply to try it."]


def test_the_word_after_the_greeting_comma_is_lowercased_before_verifying():
    """Recorded live: "Hi Maya, Your weekly report export..." A name, a product or "I" keeps its capital."""
    from pheri.verify import tidy_message

    assert tidy_message("Hi Maya, Your weekly report export fails.") == "Hi Maya, your weekly report export fails."
    assert tidy_message("Hello Pablo, You recently hit your seat limit.") == "Hello Pablo, you recently hit your seat limit."
    assert tidy_message("Hi Bikash, I hear you.") == "Hi Bikash, I hear you."
    assert tidy_message("Hi Isha, Ilam Green is back.") == "Hi Isha, Ilam Green is back."
    assert tidy_message("Please pause Zara's subscription.") == "Please pause Zara's subscription."


# ---- the address fix that started this --------------------------------------------------------
def test_the_name_said_to_the_customers_face_is_caught(data, llm):
    """Recorded on 29 Oct: "Hi Aarav, Aarav joined Brightdesk 3 days ago..." and why-text saying "you"."""
    vc = _vc(data, llm, "brightdesk", PABLO)
    d = Draft(ProposedAction(kind="offer_upgrade", channel="email", message="Hi Pablo, Pablo hit the seat limit. Want "
                             "more seats? - The Brightdesk team"),
              "This fits because you hit the seat limit.", "Your plan renews in 10 days.",
              ["journey_stage", "seat_limit_hits_30d", "renewal_in_days"], [])
    v = verify_draft(d, vc)
    address = v.check("address")["reasons"]
    assert any("says 'Pablo' outside the greeting" in r for r in address)
    assert any(r.startswith("why_this says 'you'") for r in address) and any("why_now says 'Your'" in r for r in address)


# ---- the middle step --------------------------------------------------------------------------
def test_the_middle_step_bar_is_per_business_and_per_kind_of_action():
    assert THRESHOLDS["brightdesk"] == {"money": 1.0, "nudge": 0.8} and THRESHOLDS["kettle"]["money"] == 1.0
    checkin = middle_step("brightdesk", "quiet", "send_checkin")  # stage right for 82%: enough for a nudge
    assert checkin["passed"] and checkin["class"] == "nudge" and 0.8 <= checkin["stage_score"] < 0.85
    discount = middle_step("brightdesk", "quiet", "offer_discount")  # fits 97% of them: not enough for money
    assert not discount["passed"] and discount["class"] == "money"
    assert any("needs 100%" in r for r in discount["reasons"])
    assert middle_step("brightdesk", "expanding", "offer_upgrade")["passed"]  # 100% and 100%
    assert middle_step("brightdesk", "stuck", "task_for_owner") == {
        "stage": "stuck", "action": "task_for_owner", "applies": False, "passed": True, "reasons": []}


def test_the_plans_in_the_truth_set_come_from_the_twins_hidden_table():
    from pheri.twin import fitting_plans

    for b in ("brightdesk", "kettle"):
        truth = json.loads((REPO_ROOT / "data" / "synth" / b / "_truth.json").read_text(encoding="utf-8"))
        assert truth["plans"] == fitting_plans(b)
    assert fitting_plans("brightdesk")["stuck"] == ["send_help", "book_call"]


# ---- the loop: reasons go back, at most N drafts, then the owner ----------------------------------
def test_a_claim_the_judge_rejects_goes_back_and_the_next_draft_passes(data, llm, monkeypatch):
    real = llm_module._mock_responders[JUDGE_PURPOSE]
    judged = []

    def strict_once(messages, schema):
        judged.append(1)
        out = json.loads(real(messages, schema))
        if len(judged) == 1:
            out["verdicts"][0] = {**out["verdicts"][0], "supported": False, "reason": "no fact says this"}
        return json.dumps(out)

    monkeypatch.setitem(llm_module._mock_responders, JUDGE_PURPOSE, strict_once)
    model = llm_module._mock_responders[PURPOSE]

    def revises(messages, schema):  # after the reasons come back, the model rewrites its why
        out = model(messages, schema)
        told = any(m.get("role") == "user" and str(m.get("content", "")).startswith("Code checked") for m in messages)
        return out.replace("is the most direct next step", "is the next step") if told and isinstance(out, str) else out

    monkeypatch.setitem(llm_module._mock_responders, PURPOSE, revises)
    store = MemoryStore("brightdesk")
    seed(store, llm)
    out = decide(build_profile(data["brightdesk"], MAYA, llm), store, llm)
    assert [a["verification"]["caught_by"] for a in out.attempts] == ["judge", None]
    assert out.verification["passed"] and out.action["status"] == "awaiting_approval"
    fed = [x["text"] for t in out.turn_log for x in t["sent"] if x["kind"] == "feedback"]
    assert len(fed) == 1 and "judge:" in fed[0] and "no fact says this" in fed[0]
    assert [t["attempt"] for t in out.turn_log][-1] == 2


def test_the_number_of_drafts_is_a_setting_and_then_a_person_takes_over(data, llm, monkeypatch):
    monkeypatch.setenv("PHERI_VERIFY_MAX_ATTEMPTS", "2")
    llm2 = LLM(Settings())
    bad = next(r for r in DRAFTS if r["id"] == "B08")["draft"]  # her name outside the greeting, every time
    monkeypatch.setitem(llm_module._mock_responders, PURPOSE, lambda m, s: json.dumps(bad))
    store = MemoryStore("brightdesk")
    seed(store, llm2)
    set_mode(store, "send_help", "act_alone", by="owner")
    out = decide(build_profile(data["brightdesk"], MAYA, llm2), store, llm2)
    assert len(out.attempts) == 2 and not out.verification["passed"]
    assert out.action["status"] == "awaiting_approval" and out.action["mode"] == "ask_owner"
    assert out.action["payload"]["verification"]["failed"] == ["address"]
    assert [i["action"]["id"] for i in queue(store)] == [out.action["id"]]


def test_a_judge_that_cannot_answer_sends_the_draft_to_a_person_without_retrying(data, llm, monkeypatch):
    monkeypatch.setitem(llm_module._mock_responders, JUDGE_PURPOSE, lambda m, s: "not json")
    store = MemoryStore("brightdesk")
    seed(store, llm)
    out = decide(build_profile(data["brightdesk"], MAYA, llm), store, llm)
    assert len(out.attempts) == 1 and out.verification["caught_by"] == "judge"
    assert out.verification["judge_error"] and out.action["status"] == "awaiting_approval"


def test_the_model_cannot_call_verification_or_send_anything_itself(data, llm, monkeypatch):
    real = llm_module._mock_responders[PURPOSE]

    def sneaky(messages, schema):
        if not any(m.get("type") == "function_call" for m in messages):
            return {"function_calls": [{"name": "verify_draft", "arguments": {"passed": True}},
                                       {"name": "send_message", "arguments": {"text": "hi"}}]}
        return real(messages, schema)

    monkeypatch.setitem(llm_module._mock_responders, PURPOSE, sneaky)
    store = MemoryStore("brightdesk")
    seed(store, llm)
    out = decide(build_profile(data["brightdesk"], MAYA, llm), store, llm)
    assert out.discarded_tools == ["verify_draft", "send_message"]
    assert [a["details"]["tool"] for a in store.audit_log() if a["event"] == "tool_call_discarded"] == \
        ["verify_draft", "send_message"]
    # An unknown tool call is a hard failure: no second draft (it cannot be undone), and no one can send it.
    v = out.action["payload"]["verification"]
    assert not out.verification["passed"] and len(out.attempts) == 1 and v["hard_failed"] == ["tools"]
    with pytest.raises(ValueError, match=r"no one can override \(tools\)"):
        approve(store, queue(store)[0]["id"], by="owner", override=True,
                context_for=lambda k: CheckContext("brightdesk", build_profile(data["brightdesk"], k, llm).facts, NOW))


# ---- no path sends a message without passing verification ----------------------------------------
def _sample(ds, per_stage=3):
    """A few customers from every journey stage, plus the hero."""
    from pheri.journey import stages

    picked, seen = [], {}
    for k, j in stages(ds).items():
        if seen.get(j.stage, 0) < per_stage:
            seen[j.stage] = seen.get(j.stage, 0) + 1
            picked.append(k)
    return picked


def _send_everything(data, llm):
    """Every customer-facing action on act alone, then the owner approves everything left in the queue, with an
    override wherever one is allowed. Returns the stores and how many approvals were refused."""
    stores, refused = {}, []
    for b, ds in data.items():
        store = stores[b] = MemoryStore(b)
        seed(store, llm)
        for kind in CATALOG:
            if CATALOG[kind].customer_facing and kind in __import__("pheri.actions", fromlist=["x"]).BUSINESS_ACTIONS[b]:
                set_mode(store, kind, "act_alone", by="owner")
        for key in _sample(ds) + ([MAYA] if b == "brightdesk" else []):
            decide_customer(ds, key, store, llm)
        for item in queue(store):
            v = item["action"]["payload"].get("verification") or {}
            try:
                approve(store, item["id"], by="owner", override=bool(v.get("overridable")),
                        context_for=lambda k, b=b, store=store: CheckContext(b, build_profile(data[b], k, llm).facts, NOW))
            except ValueError:
                refused.append(item["action"]["id"])
    return stores, refused


def test_no_path_sends_a_message_without_passing_verification(data, llm):
    """Every message that went out passed verification for its exact text, or failed only soft checks and an owner
    overrode them, on the record, for that exact text. Nothing that failed a hard check went out."""
    stores, _ = _send_everything(data, llm)
    sent = overridden = 0
    for store in stores.values():
        for a in store.actions():
            if a["status"] != "executed" or not CATALOG[a["kind"]].customer_facing:
                continue
            sent += 1
            p, v = a["payload"], a["payload"]["verification"]
            sha = payload_sha(a["kind"], p["channel"], p["discount_pct"], p["message"])
            events = [e["event"] for e in store.audit_log(a["id"])]
            if v["passed"]:
                assert v["sha"] == sha and events.index("verified") < events.index("executed")
                continue
            overridden += 1
            o = next(e["details"] for e in store.audit_log(a["id"]) if e["event"] == "owner_override")
            assert v["hard_failed"] == [] and set(v["soft_failed"]) <= set(o["overridden"])
            assert o["sha"] == sha and o["text"] == p["message"] and events.index("owner_override") < events.index("executed")
        for a in store.actions():
            v = a["payload"].get("verification") or {}
            if v.get("hard_failed"):
                assert a["status"] != "executed", a  # hard: never sent, override or not
    assert sent >= 10 and overridden >= 1  # the sample really did send, both ways


def test_with_verification_failing_nothing_is_sent_even_on_act_alone_and_owner_approval(data, llm, monkeypatch):
    from pheri import autonomy
    from pheri.verify import Verification

    facts_failed = [{"name": "facts", "applies": True, "passed": False, "reasons": ["writes 30, forced"]}]
    monkeypatch.setattr(autonomy, "verify_draft", lambda d, vc: Verification(
        False, facts_failed, caught_by="code", reasons=["facts: writes 30, forced"],
        rule_check={"allowed": True, "results": []},
        sha=payload_sha(d.action.kind, d.action.channel, d.action.discount_pct, d.action.message)))
    stores, refused = _send_everything(data, llm)
    for store in stores.values():
        assert not [a for a in store.actions() if a["status"] == "executed" and CATALOG[a["kind"]].customer_facing]
    assert refused  # the owner tried, with an override: an invented number is a hard check


def test_only_the_send_step_marks_a_message_executed():
    """Structural: the one place that sets "executed" on an action that reaches a customer is _execute, which
    checks the stored verification. (The other sets it on an escalation, which sends nothing.)"""
    src = (REPO_ROOT / "api" / "pheri" / "autonomy.py").read_text(encoding="utf-8")
    sites = [m.start() for m in re.finditer(r'set_action\([^)]*"executed"', src)]
    assert len(sites) == 2
    execute = src.index("def _execute(")
    escalation = src.index('if action["kind"] == ESCALATE:')
    assert any(execute < s < src.index("def approve(") for s in sites)
    assert any(escalation < s < escalation + 400 for s in sites)
    assert src.index("verified_to_send(action, override)", execute) < sites[[execute < s for s in sites].index(True)]
    for path in (REPO_ROOT / "api" / "pheri").glob("*.py"):
        if path.name != "autonomy.py":
            assert not re.search(r'"executed"\s*,\s*executed_at', path.read_text(encoding="utf-8")), path.name
