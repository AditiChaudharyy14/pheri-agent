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
         "message": "Hi Maya, here are the steps that fix the CSV export. - The Brightdesk team",
         "why_this": "Her exports fail.", "why_now": "She has been quiet for 12 days.",
         "fact_keys": ["failed_exports_30d", "days_quiet"], "quote_ids": []}
    return json.dumps({**d, **over})


def _quote_id(p, source_id):
    from pheri.decide import quote_index

    return next(qid for qid, q in quote_index(p).items() if q["source_id"] == source_id)


def _model(monkeypatch, fn):
    monkeypatch.setitem(llm_module._mock_responders, PURPOSE, fn)


# ---- the hero -----------------------------------------------------------------------
def test_maya_is_told_about_her_actual_problem_and_why_now(maya, store, llm):
    """Specific, not generic: her problem, her goal, the renewal, and her own pronoun."""
    out = decide(maya, store, llm)
    d = out.decision
    assert maya.pronouns == "she/her"
    assert "CSV export" in d["message"] and "weekly reports" in d["message"]
    assert "CSV export" in d["why_this"] and "her goal of weekly reports" in d["why_this"]
    assert "she reported" in d["why_this"] and " they " not in f" {d['why_this']} "
    assert "renews in 8 days" in d["why_now"]
    refs = {e["ref"] for e in out.evidence}
    assert {"renewal_in_days", "T0999", "sales_notes.txt#L41"} <= refs  # every claim cites its source


def test_no_pronoun_is_guessed_when_the_customer_gave_none(brightdesk, store, llm):
    """One customer from every journey stage, each without pronouns: the why-text uses the name only."""
    from pheri.journey import stage

    by_stage = {}
    for k, c in brightdesk.customers.items():
        p = build_profile(brightdesk, k, llm)
        if c.pronouns is None:
            by_stage.setdefault(stage("brightdesk", p.facts, p.provenance.get("facts")).stage, p)
    assert len(by_stage) == 6
    for p in by_stage.values():
        d = decide(p, store, llm).decision
        words = f" {d['why_this']} {d['why_now']} ".replace(",", " ").replace(".", " ").split()
        assert not {"she", "he", "her", "his", "they", "their", "them"} & set(words), d
        assert d["why_this"].startswith(p.name.split()[0])


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
    assert out.turns == 2 and "not valid decision JSON" in out.fallback
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
def test_the_schema_only_offers_this_customers_facts_and_quotes(maya, store, llm, monkeypatch):
    from pheri.decide import fact_names, quote_index

    schemas = []
    _model(monkeypatch, lambda m, s: schemas.append(s) or _answer())
    decide(maya, store, llm)
    props = schemas[0]["properties"]
    assert set(props) >= {"fact_keys", "quote_ids"} and "evidence" not in props  # no free-text evidence
    assert set(props["fact_keys"]["items"]["enum"]) == set(fact_names(maya))
    assert set(props["quote_ids"]["items"]["enum"]) == set(quote_index(maya))
    assert all("#" in qid for qid in quote_index(maya))  # "T0999#1": source and position


def test_code_attaches_the_real_values_and_quotes(maya, store, llm, monkeypatch):
    from pheri.decide import quote_index

    qid = _quote_id(maya, "T1001")
    _model(monkeypatch, lambda m, s: _answer(fact_keys=["days_quiet", "journey_stage"], quote_ids=[qid]))
    out = decide(maya, store, llm)
    assert out.evidence == [
        {"kind": "fact", "ref": "days_quiet", "value": "12"},
        {"kind": "fact", "ref": "journey_stage", "value": "stuck"},
        {"kind": "quote", "ref": "T1001", "value": quote_index(maya)[qid]["quote"], "quote_id": qid}]


def test_a_key_or_id_outside_the_lists_is_an_invalid_answer(maya, store, llm, monkeypatch):
    _model(monkeypatch, lambda m, s: _answer(fact_keys=["credit_score"]))  # not in her profile
    out = decide(maya, store, llm)
    assert out.decision["action"] == "task_for_owner" and "not valid decision JSON" in out.fallback
    _model(monkeypatch, lambda m, s: _answer(quote_ids=["T0999#99"]))  # no such verified quote
    assert "not valid decision JSON" in decide(maya, store, llm).fallback


def test_no_evidence_picked_means_pheri_may_not_act_alone(maya, store, llm, monkeypatch):
    set_mode(store, "send_help", "act_alone", by="owner")
    _model(monkeypatch, lambda m, s: _answer(why_now="She is quiet.", fact_keys=[], quote_ids=[]))
    out = decide(maya, store, llm)
    assert out.evidence == [] and out.action["status"] == "awaiting_approval"  # executed with evidence


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
    "fact_keys": ["journey_stage"], "quote_ids": []}


def test_the_tool_loop_names_the_business_and_asks_for_the_facts_behind_numbers(maya, store, llm, monkeypatch):
    from pheri.decide import SYSTEM

    prompt = " ".join(SYSTEM.split())  # wording, not line breaks
    assert "never as the customer's own company" in prompt
    assert "fact_keys" in prompt and "quote_ids" in prompt and "at most 8 of each" in prompt
    assert "code attaches the real values and quotes" in prompt
    calls = []
    real = llm.complete
    monkeypatch.setattr(llm, "complete", lambda items, **kw: calls.append(items) or real(items, **kw))
    decide(maya, store, llm)
    assert json.loads(calls[0][1]["content"])["business_name"] == "Brightdesk"


def test_the_private_prompt_differs_from_the_713_run_only_in_signature_and_evidence(maya, store, llm, monkeypatch):
    """tests/data/private_prompt_713.txt is the private prompt of the one run that worked (713 tokens, ab38399)."""
    from pheri.config import REPO_ROOT
    from pheri.decide import PRIVATE_SYSTEM
    from pheri.privacy import set_private_mode

    old = (REPO_ROOT / "api" / "tests" / "data" / "private_prompt_713.txt").read_text(encoding="utf-8").splitlines()
    new = PRIVATE_SYSTEM.splitlines()
    removed = [line for line in old if line not in new]
    added = [line for line in new if line not in old]
    sig = next(i for i, line in enumerate(old) if line.startswith("- message:"))
    ev = next(i for i, line in enumerate(old) if line.startswith("- evidence:"))
    assert removed == old[sig:sig + 2] + old[ev:ev + 4]  # the signature and the free-text evidence lines
    assert added[0].startswith("- message:") and "business_name team" in added[0]
    assert added[2].startswith("- fact_keys:") and all("evidence" not in line for line in added)
    assert len(added) == 6  # 2 signature lines + 4 evidence lines; every other line is word for word
    set_private_mode(store, decide=True, by="owner")
    calls = []
    real = llm.complete
    monkeypatch.setattr(llm, "complete", lambda items, **kw: calls.append(items) or real(items, **kw))
    decide(maya, store, llm)
    payload = json.loads(calls[0][-1]["content"])
    assert payload["business_name"] == "Brightdesk" and payload["allowed"]["business_name"] == "Brightdesk"


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
             "fact_keys": ["journey_stage", "failed_exports_30d", "open_tickets", "days_quiet", "renewal_in_days"],
             "quote_ids": [_quote_id(maya, "T1001")]}
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
    keys = list(maya.facts)  # more than 8, with repeats on top: a runaway list
    assert len(keys) > 8
    _model(monkeypatch, lambda m, s: _answer(fact_keys=keys + keys))
    out = decide(maya, store, llm)
    assert [e["ref"] for e in out.evidence] == keys[:8]


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


def test_the_turn_log_shows_the_agents_loop(maya, store, llm):
    out = decide(maya, store, llm)
    kinds = [([x["kind"] for x in t["sent"]], [x.get("tool", x["kind"]) for x in t["got"]]) for t in out.turn_log]
    assert kinds == [
        (["instructions", "brief"], ["get_profile", "list_allowed_actions"]),  # it asks for what it needs
        (["tool_result", "tool_result"], ["check_rules"]),  # tries the goodwill discount...
        (["tool_result"], ["check_rules"]),  # ...is refused by the first-month rule, tries help
        (["tool_result"], ["answer"]),
    ]
    refused = out.turn_log[2]["sent"][0]["output"]
    assert refused["action"] == "offer_discount" and refused["violations"] == [FIRST_MONTH]
    assert out.turn_log[-1]["got"][0]["decision"]["action"] == "send_help"
    assert all(t["usage"]["model"] == "muse-spark-1.3" for t in out.turn_log)
    assert [t["turn"] for t in out.turn_log] == list(range(1, out.turns + 1))


def test_a_private_decision_logs_its_one_turn(maya, store, llm):
    from pheri.privacy import set_private_mode

    set_private_mode(store, decide=True, by="owner")
    out = decide(maya, store, llm)
    assert len(out.turn_log) == 1 and out.turn_log[0]["usage"]["provider"] == "baseten"
    assert set(out.turn_log[0]["sent"][1]["data"]) == {"today", "business_name", "profile", "allowed", "dry_run"}
