"""Next best action through the tool loop (mock Muse Spark). Code checks evidence and rules every time."""

import json

import pytest

from pheri import llm as llm_module
from pheri.autonomy import set_mode
from pheri.config import Settings
from pheri.decide import MAX_TURNS, NUDGE, PURPOSE, TOOLS, decide
from pheri.llm import LLM
from pheri.profile import build_profile, build_profiles, load
from pheri.rules import seed
from pheri.store import MemoryStore

MAYA = "maya.okafor@pinecrest.example"
FIRST_MONTH = "the customer is 22 days in; no discounts in the first 30 days"


@pytest.fixture
def llm(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return LLM(Settings())


@pytest.fixture(scope="module")
def brightdesk():
    return load("brightdesk")


@pytest.fixture
def maya(brightdesk, llm):
    return build_profile(brightdesk, MAYA, llm)


@pytest.fixture
def store(llm):
    s = MemoryStore("brightdesk")
    seed(s, llm)  # "Never offer discounts in a customer's first month."
    return s


def _answer(**over):
    d = {"action": "send_help", "channel": "email", "discount_pct": None,
         "message": "Hi Maya, here are the steps that fix the CSV export. - The team",
         "why_this": "Her exports fail.", "why_now": "She has been quiet for 12 days.",
         "evidence": [{"ref": "failed_exports_30d", "value": "5"}, {"ref": "days_quiet", "value": "12"},
                      {"ref": "T0999", "value": "it fails at 90%"}]}
    return json.dumps({**d, **over})


def _model(monkeypatch, fn):
    monkeypatch.setitem(llm_module._mock_responders, PURPOSE, fn)


# ---- the hero -----------------------------------------------------------------------
def test_maya_discount_is_blocked_in_the_loop_and_she_gets_help(maya, store, llm):
    out = decide(maya, store, llm)

    # The model tried a goodwill discount first; check_rules refused it, so it moved on.
    assert out.prechecks[0] == {"action": "offer_discount", "allowed": False, "violations": [FIRST_MONTH]}
    assert out.prechecks[-1]["action"] == "send_help" and out.prechecks[-1]["allowed"]
    assert out.decision["action"] == "send_help" and out.fallback is None
    assert out.action["status"] == "awaiting_approval"  # the default dial: ask the owner
    assert out.action["rule_check"]["allowed"] is True  # code checked the final action again

    refs = {e["ref"]: e["value"] for e in out.evidence}
    assert refs["journey_stage"] == "stuck" and refs["failed_exports_30d"] == "5" and refs["days_quiet"] == "12"
    assert {"T0999", "T1001"} & set(refs) and out.dropped_evidence == []  # a quote from one of her own tickets
    assert "Why this:" in out.action["why"] and "Why now:" in out.action["why"]
    log = [a["event"] for a in store.audit_log()]
    assert log[:2] == ["rule_proposed", "rule_confirmed"]
    assert log[2:] == ["rule_precheck", "rule_precheck", "decided", "rule_passed", "approval_requested"]


def test_maya_discount_is_blocked_in_code_even_if_the_model_ignores_check_rules(maya, store, llm, monkeypatch):
    _model(monkeypatch, lambda m, s: _answer(action="offer_discount", discount_pct=20.0,
                                             message="Hi Maya, here is 20% off next month."))
    out = decide(maya, store, llm)
    assert out.turns == 1 and out.prechecks == []  # never asked check_rules
    assert out.action["status"] == "blocked"
    assert FIRST_MONTH in [r["reason"] for r in out.action["rule_check"]["results"]]
    blocked = [a for a in store.audit_log() if a["event"] == "rule_blocked"]
    assert blocked and blocked[0]["details"]["violations"] == [FIRST_MONTH]
    assert store.approvals() == []


def test_without_the_rule_the_same_discount_would_go_to_the_owner(maya, llm):
    out = decide(maya, MemoryStore("brightdesk"), llm)  # no rules confirmed
    assert out.decision["action"] == "offer_discount" and out.decision["discount_pct"] == 20
    assert out.action["status"] == "awaiting_approval"


# ---- the loop -------------------------------------------------------------------------
def test_tool_loop_replays_the_whole_conversation_statelessly(maya, store, llm, monkeypatch):
    calls = []
    real = llm.complete
    monkeypatch.setattr(llm, "complete", lambda items, **kw: calls.append((list(items), kw)) or real(items, **kw))
    decide(maya, store, llm)
    first_items, _ = calls[0]
    assert [i["role"] for i in first_items] == ["system", "user"]
    for items, kw in calls:
        assert kw["tools"] == TOOLS and kw["effort"] == "medium" and kw["stateless"] is True
        assert "previous_response_id" not in kw  # nothing depends on Meta keeping a stored response
    for (before, _), (after, _) in zip(calls, calls[1:]):
        assert after[:len(before)] == before  # each turn resends everything said so far...
        new = after[len(before):]
        assert new[0]["type"] == "reasoning" and new[0]["summary"] == []  # ...the model's reasoning first,
        call_ids = [i["call_id"] for i in new if i.get("type") == "function_call"]
        outputs = [i["call_id"] for i in new if i.get("type") == "function_call_output"]
        assert call_ids and outputs == call_ids  # ...and one output per tool call, in order
    assert {t["name"] for t in TOOLS} == {"get_profile", "list_allowed_actions", "check_rules"}
    assert all(t["type"] == "function" and t["parameters"]["additionalProperties"] is False for t in TOOLS)


def test_plain_text_gets_one_nudge(maya, store, llm, monkeypatch):
    def model(messages, schema):
        nudged = any(m.get("role") == "user" and m.get("content") == NUDGE for m in messages)
        return _answer() if nudged else "I would send her the export fix, I think."

    _model(monkeypatch, model)
    out = decide(maya, store, llm)
    assert out.turns == 2 and out.fallback is None and out.decision["action"] == "send_help"


def test_plain_text_twice_falls_back_to_the_owner(maya, store, llm, monkeypatch):
    _model(monkeypatch, lambda m, s: "Let me think about Maya some more.")
    out = decide(maya, store, llm)
    assert out.turns == 2 and "plain text" in out.fallback
    assert out.decision["action"] == "task_for_owner" and out.action["status"] == "executed"  # a task, nothing sent


def test_endless_tool_calls_stop_at_the_turn_limit(maya, store, llm, monkeypatch):
    _model(monkeypatch, lambda m, s: {"function_calls": [{"name": "get_profile", "arguments": {}}]})
    out = decide(maya, store, llm)
    assert out.turns == MAX_TURNS and "no decision" in out.fallback
    assert out.decision["action"] == "task_for_owner"


def test_bad_tool_arguments_and_unknown_tools_return_errors_to_the_model(maya, store, llm, monkeypatch):
    seen = []

    def model(messages, schema):
        outputs = [json.loads(m["output"]) for m in messages if m.get("type") == "function_call_output"]
        if not outputs:
            return {"function_calls": [{"name": "check_rules", "arguments": '{"action": "fly_to_moon"}'},
                                       {"name": "delete_everything", "arguments": {}}]}
        seen.extend(outputs)
        return _answer()

    _model(monkeypatch, model)
    decide(maya, store, llm)
    assert seen[0]["error"].startswith("bad arguments") and seen[1] == {"error": "unknown tool 'delete_everything'"}


# ---- evidence -------------------------------------------------------------------------
def test_made_up_evidence_is_dropped_and_pheri_may_not_act_alone(maya, store, llm, monkeypatch):
    set_mode(store, "send_help", "act_alone", by="owner")
    _model(monkeypatch, lambda m, s: _answer(why_now="She is quiet.", evidence=[
        {"ref": "days_quiet", "value": "3"},  # wrong value
        {"ref": "T0999", "value": "she said she will cancel"},  # not what she wrote
        {"ref": "credit_score", "value": "low"},  # not in the profile at all
    ]))
    out = decide(maya, store, llm)
    assert out.evidence == [] and len(out.dropped_evidence) == 3
    assert out.action["status"] == "awaiting_approval"  # would have been executed with real evidence


def test_a_number_nobody_can_back_caps_the_dial(maya, store, llm, monkeypatch):
    set_mode(store, "send_help", "act_alone", by="owner")
    _model(monkeypatch, lambda m, s: _answer(why_now="She has been quiet for 30 days."))
    assert decide(maya, store, llm).action["status"] == "awaiting_approval"
    _model(monkeypatch, lambda m, s: _answer())  # same decision, every number backed
    assert decide(maya, store, llm).action["status"] == "executed"


# ---- breadth --------------------------------------------------------------------------
def test_twenty_kettle_customers_each_get_a_checked_decision(llm):
    kettle, store = load("kettle"), MemoryStore("kettle")
    outs = [decide(p, store, llm) for p in build_profiles(kettle, llm)]
    assert len(outs) == 20
    for o in outs:
        assert o.fallback is None and o.evidence
        assert o.action is None or o.action["rule_check"]["allowed"] is not None
    assert llm.ledger.totals("meta").settled_usd == 0  # mock mode spends nothing
    decided = [a for a in store.audit_log() if a["event"] == "decided"]
    assert len(decided) == 20


# ---- what the first live run taught us ----------------------------------------------
def test_an_answer_cut_off_at_the_output_limit_falls_back_without_a_nudge(maya, store, llm, monkeypatch):
    def model(messages, schema):
        if not any(m.get("type") == "function_call_output" for m in messages):
            return {"function_calls": [{"name": "get_profile", "arguments": {}}]}
        return {"text": "", "incomplete": "max_output_tokens"}  # all reasoning, no JSON

    _model(monkeypatch, model)
    out = decide(maya, store, llm)
    assert out.turns == 2 and "cut off (max_output_tokens)" in out.fallback
    assert out.decision["action"] == "task_for_owner"


class _Refused(Exception):
    status_code = 400
    message = "referenced response not found or expired"


def test_a_refused_request_ends_only_this_customers_decision(maya, store, llm, monkeypatch):
    real, calls = llm.complete, []

    def flaky(items, **kw):
        calls.append(kw)
        if len(calls) == 2:
            raise _Refused()
        return real(items, **kw)

    monkeypatch.setattr(llm, "complete", flaky)
    out = decide(maya, store, llm)
    assert "refused turn 2 (400: referenced response not found or expired)" in out.fallback
    assert out.action["kind"] == "task_for_owner"


def test_spend_cap_still_stops_the_run(maya, store, llm, monkeypatch):
    from pheri.ledger import SpendCapExceeded

    monkeypatch.setattr(llm, "complete", lambda *a, **kw: (_ for _ in ()).throw(SpendCapExceeded("cap")))
    with pytest.raises(SpendCapExceeded):
        decide(maya, store, llm)


def test_repeat_profile_reads_are_answered_briefly_and_optional_args_may_be_left_out(maya, store, llm, monkeypatch):
    def model(messages, schema):
        n = sum(m.get("type") == "function_call_output" for m in messages)
        if n == 0:
            return {"function_calls": [{"name": "get_profile", "arguments": {}},
                                       {"name": "get_profile", "arguments": {}}]}
        if n == 2:
            return {"function_calls": [{"name": "check_rules", "arguments": {"action": "send_help"}}]}
        return _answer()

    _model(monkeypatch, model)
    out = decide(maya, store, llm)
    assert [t["tool"] for t in out.trace] == ["get_profile", "get_profile", "check_rules"]
    assert '"note"' in out.trace[1]["output"] and len(out.trace[0]["output"]) == 300  # full profile, clipped in trace
    assert out.prechecks[0]["action"] == "send_help" and "not one brightdesk uses" in out.prechecks[0]["violations"][0]


def test_the_string_null_means_no_value(maya, store, llm, monkeypatch):
    # Seen live: check_rules({"action": "send_help", "channel": "email", "discount_pct": "null"}).
    def model(messages, schema):
        if not any(m.get("type") == "function_call_output" for m in messages):
            return {"function_calls": [{"name": "check_rules", "arguments":
                                        '{"action": "send_help", "channel": "email", "discount_pct": "null"}'}]}
        return _answer(discount_pct="null", channel="email")

    _model(monkeypatch, model)
    out = decide(maya, store, llm)
    assert out.prechecks == [{"action": "send_help", "allowed": True, "violations": []}]
    assert out.decision["discount_pct"] is None and out.fallback is None


def test_a_discount_on_another_action_is_refused_with_what_to_do_instead(maya, store, llm, monkeypatch):
    # Seen live: book_call with a discount, three times in a row.
    from pheri.decide import SYSTEM

    _model(monkeypatch, lambda m, s: _answer(action="book_call", discount_pct=10.0))
    out = decide(maya, store, llm)
    assert out.action["status"] == "blocked"
    assert ("book_call cannot carry a discount: set discount_pct to null, or use offer_discount"
            in out.action["rule_check"]["results"][0]["reason"])
    assert "a discount cannot ride along" in SYSTEM and "the action is offer_discount" in SYSTEM


# ---- what the private live run showed (signature, numbers), and saving runs ------------------
LIVE_PRIVATE = {  # close to what Muse Spark Open answered for Maya, live
    "action": "book_call", "channel": "email", "discount_pct": None,
    "message": "Hi Maya, would a quick call help with the CSV export? — Pinecrest Team",
    "why_this": "Blocked with 5 failed exports and 2 open tickets.",
    "why_now": "Quiet for 12 days with renewal in 8 days.",
    "evidence": [{"ref": "journey_stage", "value": "stuck"}, {"ref": "T1001", "value": "Can't connect our email inbox"}]}


def test_the_tool_loop_names_the_business_and_asks_for_the_facts_behind_numbers(maya, store, llm, monkeypatch):
    from pheri.decide import SYSTEM

    prompt = " ".join(SYSTEM.split())  # wording, not line breaks
    assert "never as the customer's own company" in prompt
    assert "Cite the facts behind the numbers you use" in prompt and "At most 8 evidence items" in prompt
    calls = []
    real = llm.complete
    monkeypatch.setattr(llm, "complete", lambda items, **kw: calls.append(items) or real(items, **kw))
    decide(maya, store, llm)
    assert json.loads(calls[0][1]["content"])["business_name"] == "Brightdesk"


def test_the_private_prompt_is_pinned_to_the_run_that_worked(maya, store, llm, monkeypatch):
    """Live, the newer wording sent Muse Spark Open into whitespace-padded JSON; the private prompt is the one
    from the 713-token run, word for word, and code (not the prompt) checks signature and numbers."""
    from pheri.decide import PRIVATE_SYSTEM
    from pheri.privacy import set_private_mode

    text = " ".join(PRIVATE_SYSTEM.split())
    assert "signed by the team" in text and "Never use a number that is not in the profile" in text
    assert "business_name" not in text and "At most 8 evidence items" not in text
    set_private_mode(store, decide=True, by="owner")
    calls = []
    real = llm.complete
    monkeypatch.setattr(llm, "complete", lambda items, **kw: calls.append(items) or real(items, **kw))
    decide(maya, store, llm)
    payload = json.loads(calls[0][-1]["content"])
    assert set(payload) == {"today", "profile", "allowed", "dry_run"} and "business_name" not in payload["allowed"]


def test_signed_as_the_customers_company_is_caught_in_code(maya, store, llm, monkeypatch):
    from pheri.privacy import set_private_mode

    set_private_mode(store, decide=True, by="owner")
    set_mode(store, "book_call", "act_alone", by="owner")
    monkeypatch.setitem(llm_module._mock_responders, "decide_private", lambda m, s: json.dumps(LIVE_PRIVATE))
    out = decide(maya, store, llm)
    assert out.message_problems == ["signed as the customer's company (Pinecrest), not the business"]
    assert out.unsupported_numbers == ["12", "2", "5", "8"]  # in the why-text, not in any kept evidence
    assert out.action["status"] == "awaiting_approval"  # act_alone, capped: a person reads it first
    logged = [a for a in store.audit_log() if a["event"] == "decided"][-1]["details"]
    assert logged["message_problems"] and logged["unsupported_numbers"] == ["12", "2", "5", "8"]


def test_numbers_cited_as_facts_pass_and_the_business_signature_is_fine(maya, store, llm, monkeypatch):
    from pheri.privacy import set_private_mode

    set_private_mode(store, decide=True, by="owner")
    set_mode(store, "book_call", "act_alone", by="owner")
    fixed = {**LIVE_PRIVATE, "message": "Hi Maya, would a quick call help with the CSV export? — The Brightdesk team",
             "evidence": LIVE_PRIVATE["evidence"] + [
                 {"ref": "failed_exports_30d", "value": "5"}, {"ref": "open_tickets", "value": "2"},
                 {"ref": "days_quiet", "value": "12"}, {"ref": "renewal_in_days", "value": "8"}]}
    monkeypatch.setitem(llm_module._mock_responders, "decide_private", lambda m, s: json.dumps(fixed))
    out = decide(maya, store, llm)
    assert out.message_problems == [] and out.unsupported_numbers == [] and out.dropped_evidence == []
    assert out.action["status"] == "executed"  # every claim backed: the dial is honoured


def test_every_live_run_can_be_saved_in_full(tmp_path, maya, store, llm):
    import dataclasses

    from pheri.llm import register_mock
    from pheri.runlog import call_record, save_run

    out = decide(maya, store, llm)
    register_mock("runlog_probe", lambda m, s: "fine")
    res = llm.complete([{"role": "user", "content": "secret prompt text"}], purpose="runlog_probe")
    path = save_run("decide", {"outcomes": [dataclasses.asdict(out)], "calls": [call_record("runlog_probe", res)]},
                    folder=tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert path.parent == tmp_path and "-decide-" in path.name
    assert saved["kind"] == "decide" and saved["outcomes"][0]["customer_key"] == MAYA
    assert saved["outcomes"][0]["dropped_evidence"] == out.dropped_evidence  # the detail a printout can lose
    assert saved["calls"][0]["output_tokens"] == res.output_tokens
    assert saved["calls"][0]["answer_text"] == "fine"  # what the model wrote, so a failure can be read later
    assert "secret prompt text" not in path.read_text(encoding="utf-8")  # usage only, never the prompt


def test_evidence_is_capped_at_8_in_code(maya, store, llm, monkeypatch):
    many = [{"ref": "days_quiet", "value": "12"}] * 30  # a runaway list
    _model(monkeypatch, lambda m, s: _answer(evidence=many))
    out = decide(maya, store, llm)
    assert len(out.evidence) + len(out.dropped_evidence) == 8


def test_private_decide_is_strict_json_schema_only(maya, store, llm, monkeypatch):
    from pheri.privacy import set_private_mode

    class Refused(Exception):
        status_code = 400
        message = "response_format json_schema is not supported"

    set_private_mode(store, decide=True, by="owner")
    schemas = []

    def model(messages, schema):
        schemas.append(schema)
        raise Refused()

    monkeypatch.setitem(llm_module._mock_responders, "decide_private", model)
    out = decide(maya, store, llm)
    assert schemas and all(s is not None for s in schemas) and len(schemas) == 1  # no instructions fallback
    assert "refused the request (400)" in out.fallback
