"""Recorded replies: a live run saves them, replay mode plays them back offline. No network: the live
provider is faked at the one place llm.py talks to it."""

import json

import pytest
from pydantic import BaseModel

from pheri.config import Settings
from pheri.llm import LLM, FunctionCall, register_mock

TOOLS = [{"type": "function", "name": "lookup", "description": "x", "strict": True,
          "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}]
RULE_ID = "72089ba5-d640-4f21-a87e-407fa55f002e"


class Answer(BaseModel):
    answer: str


def _llm(monkeypatch, tmp_path, mode: str, **env) -> LLM:
    monkeypatch.setenv("PHERI_LLM_MODE", mode)
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / f"{mode}-ledger.sqlite"))
    monkeypatch.setenv("PHERI_LLM_REPLAY", str(tmp_path / "recorded.jsonl"))
    monkeypatch.delenv("PHERI_LLM_RECORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return LLM(Settings())


def _fake_meta(llm: LLM, monkeypatch):
    """Turn 1 calls the tool; turn 2 answers. Each reply starts with an encrypted reasoning item, as Meta's do."""
    def responses(req):
        outputs = [m for m in req["input"] if m.get("type") == "function_call_output"]
        reasoning = {"type": "reasoning", "summary": [], "encrypted_content": f"secret-{len(outputs)}"}
        if not outputs:
            call = {"type": "function_call", "name": "lookup", "arguments": "{}", "call_id": "call_live1",
                    "id": "fc_live1", "status": "completed"}
            return "", (900, 100, 60), None, "resp_1", [FunctionCall("lookup", "{}", "call_live1")], [reasoning, call]
        msg = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": '{"answer": "42"}'}]}
        return '{"answer": "42"}', (1200, 800, 40), None, "resp_2", [], [reasoning, msg]
    monkeypatch.setattr(llm, "_responses", responses)


def _loop(llm: LLM, rule_id: str = RULE_ID) -> list:
    """A stateless tool loop like decide.py's: the whole conversation goes out every turn."""
    items = [{"role": "system", "content": f"rules: {rule_id}"}, {"role": "user", "content": "q"}]
    results = []
    for _ in range(2):
        r = llm.complete(items, purpose="replay_test", schema=Answer, tools=TOOLS, stateless=True)
        results.append(r)
        items = [*items, *r.output_items,
                 *({"type": "function_call_output", "call_id": c.call_id, "output": '{"x": 1}'}
                   for c in r.function_calls)]
    return results


def test_a_live_run_records_and_replay_plays_it_back(monkeypatch, tmp_path):
    live = _llm(monkeypatch, tmp_path, "live", PHERI_LLM_RECORD=str(tmp_path / "recorded.jsonl"))
    _fake_meta(live, monkeypatch)
    recorded = _loop(live)
    rows = [json.loads(line) for line in (tmp_path / "recorded.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["purpose"] for r in rows] == ["replay_test", "replay_test"]
    assert all(i.get("type") != "reasoning" for r in rows for i in r["items"])  # encrypted reasoning is not kept
    assert "rules:" not in json.dumps(rows)  # replies only: the request is rebuilt from code and data

    def must_not_run(messages, schema):
        raise AssertionError("replay fell back to the stand-in")
    register_mock("replay_test", must_not_run)
    replay = _llm(monkeypatch, tmp_path, "replay")
    # A new rule id (rules are compiled again on every start) still finds the same recording.
    played = _loop(replay, rule_id="0736cebc-9423-4432-b659-17b5429e9be0")
    assert [r.recorded for r in played] == [True, True]
    assert played[0].function_calls[0].call_id == "call_live1" and played[1].parsed.answer == "42"
    assert [r.cost_usd for r in played] == pytest.approx([r.cost_usd for r in recorded])  # what the live run paid
    assert played[1].cost_usd > 0
    totals = replay.ledger.totals("meta")
    assert totals.settled_usd == 0 and totals.reserved_usd == 0  # replaying spends nothing


def test_a_conversation_never_recorded_falls_back_to_the_stand_in(monkeypatch, tmp_path):
    (tmp_path / "recorded.jsonl").write_text("", encoding="utf-8")
    register_mock("replay_test", lambda m, s: '{"answer": "offline"}')
    replay = _llm(monkeypatch, tmp_path, "replay")
    r = replay.complete([{"role": "user", "content": "never asked live"}], purpose="replay_test", schema=Answer)
    assert not r.recorded and r.parsed.answer == "offline" and r.cost_usd == 0


def test_replay_never_reaches_the_network(monkeypatch, tmp_path):
    replay = _llm(monkeypatch, tmp_path, "replay")
    monkeypatch.setattr(replay, "_client", lambda provider: (_ for _ in ()).throw(AssertionError("network")))
    register_mock("replay_test", lambda m, s: '{"answer": "offline"}')
    assert replay.complete([{"role": "user", "content": "q"}], purpose="replay_test", schema=Answer).text


def test_a_recording_run_resumes_without_paying_twice(monkeypatch, tmp_path):
    live = _llm(monkeypatch, tmp_path, "live", PHERI_LLM_RECORD=str(tmp_path / "recorded.jsonl"))
    _fake_meta(live, monkeypatch)
    _loop(live)
    spent = live.ledger.totals("meta").settled_usd
    again = _llm(monkeypatch, tmp_path, "live", PHERI_LLM_RECORD=str(tmp_path / "recorded.jsonl"))
    monkeypatch.setattr(again, "_responses", lambda req: (_ for _ in ()).throw(AssertionError("sent twice")))
    assert [r.recorded for r in _loop(again)] == [True, True]
    assert again.ledger.totals("meta").settled_usd == pytest.approx(spent)  # nothing new was billed
    assert len((tmp_path / "recorded.jsonl").read_text(encoding="utf-8").splitlines()) == 2  # nor recorded again


def test_a_refusal_is_recorded_and_replayed_as_the_same_refusal(monkeypatch, tmp_path):
    """Live, Meta sometimes answers 400. The guard sends such a reply to a person. Replay must take that same path,
    not ask the stand-in, or the replayed night differs from the recorded one."""
    from pheri.llm import _HTTPError

    rec = tmp_path / "recorded.jsonl"
    live = _llm(monkeypatch, tmp_path, "live", PHERI_LLM_RECORD=str(rec), MODEL_API_KEY="k")

    def refuse(req):
        raise _HTTPError(400, "not found")
    monkeypatch.setattr(live, "_responses", refuse)
    msgs = [{"role": "user", "content": "q"}]
    with pytest.raises(_HTTPError):
        live.complete(msgs, purpose="replay_test")
    assert json.loads(rec.read_text(encoding="utf-8").splitlines()[0])["error"]["status"] == 400

    replay = _llm(monkeypatch, tmp_path, "replay")
    register_mock("replay_test", lambda m, s: "stand-in")
    with pytest.raises(_HTTPError) as e:
        replay.complete(msgs, purpose="replay_test")
    assert e.value.status_code == 400
