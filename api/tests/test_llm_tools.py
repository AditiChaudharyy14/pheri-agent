"""Tool loops through llm.py: request shape, chained turns, honest cost estimates. Mock mode only."""

import json

import pytest
from pydantic import BaseModel

from pheri.config import Settings
from pheri.ledger import SpendCapExceeded
from pheri.llm import LLM, build_responses_request, register_mock

TOOLS = [{"type": "function", "name": "lookup", "description": "x", "strict": True,
          "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}]


class Answer(BaseModel):
    answer: str


@pytest.fixture
def llm(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return LLM(Settings())


def test_request_carries_tools_auto_choice_and_previous_response():
    req = build_responses_request("muse-spark-1.3", [], 100, Answer, "medium", "pheri-decide", TOOLS, "resp_1")
    assert req["tools"] == TOOLS and req["tool_choice"] == "auto"
    assert req["previous_response_id"] == "resp_1"
    assert req["reasoning"] == {"effort": "medium"} and req["text"]["format"]["name"] == "Answer"
    plain = build_responses_request("muse-spark-1.3", [], 100, None, None, None)
    assert "tools" not in plain and "tool_choice" not in plain and "previous_response_id" not in plain


def test_mock_tool_loop_sees_the_whole_conversation(llm):
    seen = []

    def responder(messages, schema):
        seen.append(messages)
        outputs = [m for m in messages if m.get("type") == "function_call_output"]
        return {"function_calls": [{"name": "lookup", "arguments": {}}]} if not outputs else '{"answer": "42"}'

    register_mock("loop", responder)
    first = llm.complete([{"role": "user", "content": "q"}], purpose="loop", schema=Answer, tools=TOOLS)
    assert first.parsed is None and [c.name for c in first.function_calls] == ["lookup"]
    call = first.function_calls[0]
    second = llm.complete([{"type": "function_call_output", "call_id": call.call_id, "output": "{}"}],
                          purpose="loop", schema=Answer, tools=TOOLS, previous_response_id=first.response_id)
    assert second.parsed.answer == "42"
    # The second turn saw the question, its own tool call and the tool output, as the server keeps them.
    assert [m.get("type", m.get("role")) for m in seen[1]] == ["user", "function_call", "function_call_output"]
    assert json.loads(seen[1][1]["arguments"]) == {}


def test_plain_text_with_tools_is_reported_not_raised(llm):
    register_mock("chatty", lambda m, s: "Sure! I think she needs help with exports.")
    r = llm.complete([{"role": "user", "content": "q"}], purpose="chatty", schema=Answer, tools=TOOLS)
    assert r.parsed is None and r.parse_error and r.text.startswith("Sure")


def test_unknown_previous_response_is_refused(llm):
    register_mock("loop2", lambda m, s: '{"answer": "x"}')
    with pytest.raises(RuntimeError, match="previous_response_id"):
        llm.complete([], purpose="loop2", tools=TOOLS, previous_response_id="mock_nope")


def test_tools_only_on_the_responses_api(llm):
    with pytest.raises(ValueError, match="Responses API"):
        llm.complete([{"role": "user", "content": "q"}], purpose="x", provider="baseten", tools=TOOLS)


def test_chained_call_is_costed_against_the_whole_conversation(tmp_path, monkeypatch):
    # ~10k tokens of context, then a ~3k-token follow-up. Alone the follow-up is well under the
    # per-call limit; together with the context it re-reads, it is over, so it must be refused.
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.setenv("PHERI_MAX_CALL_USD", "0.015")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    llm = LLM(Settings())
    register_mock("long", lambda m, s: {"function_calls": [{"name": "lookup", "arguments": {}}]})
    first = llm.complete([{"role": "user", "content": "x" * 30_000}], purpose="long", tools=TOOLS, max_tokens=100)
    follow_up = [{"type": "function_call_output", "call_id": first.function_calls[0].call_id, "output": "y" * 9_000}]
    llm.complete(follow_up, purpose="long", tools=TOOLS, max_tokens=100)  # no chain: fits
    with pytest.raises(SpendCapExceeded, match="per-call limit"):
        llm.complete(follow_up, purpose="long", tools=TOOLS, max_tokens=100, previous_response_id=first.response_id)


def test_stateless_request_keeps_nothing_on_the_server_and_asks_for_encrypted_reasoning():
    req = build_responses_request("muse-spark-1.3", [], 100, Answer, "medium", "pheri-decide", TOOLS, None, True)
    assert req["store"] is False and req["include"] == ["reasoning.encrypted_content"]
    assert "previous_response_id" not in req
    plain = build_responses_request("muse-spark-1.3", [], 100, Answer, "medium", "pheri-decide", TOOLS)
    assert "store" not in plain and "include" not in plain


def test_stateless_and_previous_response_cannot_be_mixed(llm):
    with pytest.raises(ValueError, match="stateless"):
        llm.complete([], purpose="x", tools=TOOLS, stateless=True, previous_response_id="resp_1")


def test_stateless_mock_returns_replayable_items_and_keeps_no_thread(llm):
    register_mock("sl", lambda m, s: {"function_calls": [{"name": "lookup", "arguments": {}}]})
    r = llm.complete([{"role": "user", "content": "q"}], purpose="sl", tools=TOOLS, stateless=True)
    assert [i["type"] for i in r.output_items] == ["reasoning", "function_call"]
    assert r.output_items[1]["call_id"] == r.function_calls[0].call_id
    assert llm._mock_threads == {} and llm._context_tokens == {}


def test_reasoning_items_always_carry_a_summary_when_replayed():
    from pheri.llm import _replayable

    class Item:  # stands in for the SDK's output item objects
        def __init__(self, **kw):
            self.kw = kw

        def model_dump(self, exclude_none=False):
            return {k: v for k, v in self.kw.items() if not (exclude_none and v is None)}

    assert _replayable(Item(type="reasoning", id="rs_1", encrypted_content="abc", summary=None)) == {
        "type": "reasoning", "id": "rs_1", "encrypted_content": "abc", "summary": []}
    call = _replayable(Item(type="function_call", name="lookup", arguments="{}", call_id="c1", status=None))
    assert call == {"type": "function_call", "name": "lookup", "arguments": "{}", "call_id": "c1"}
