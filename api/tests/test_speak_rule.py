"""Speak a rule (1 Nov): the owner's recorded voice note -> Muse Voice -> the rule compiler -> the owner confirms ->
every step still waiting that breaks it is blocked, with the rule as the reason. Offline (mock models)."""

import wave

import pytest

from pheri.config import REPO_ROOT, Settings
from pheri.llm import LLM
from pheri.rules import Rule, MaxDiscountPct, active_rules, confirm, propose
from pheri.store import MemoryStore
from pheri.synth import MORNING
from pheri.rules import CheckContext


@pytest.fixture
def llm(tmp_path):
    return LLM(Settings(llm_mode="mock", record_path=None, database_url=None, ledger_path=str(tmp_path / "l.sqlite")))


def test_the_owners_clip_is_16_khz_mono_pcm16_and_listed():
    from pheri.voice import RULE_CLIPS

    w = wave.open(str(REPO_ROOT / "data" / "voice" / RULE_CLIPS["owner-rule-hi"]["file"]))
    assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
    assert 5 < w.getnframes() / w.getframerate() < 10
    assert (REPO_ROOT / "web" / "public" / "voice" / "owner-rule-hi.wav").read_bytes() == \
        (REPO_ROOT / "data" / "voice" / "owner-rule-hi.wav").read_bytes()  # the page plays the same clip


def test_the_recorded_transcript_matches_the_owners_words_up_to_the_nukta():
    """The live Muse Voice reading (recorded 1 Nov, replayed by audio hash) against what the owner said."""
    import os

    from pheri.voice import RULE_CLIPS, transcribe_rule_clip

    os.environ.setdefault("PHERI_LLM_REPLAY", str(REPO_ROOT / "data" / "recorded" / "llm.jsonl"))
    replay = LLM(Settings(llm_mode="replay", replay_path=str(REPO_ROOT / "data" / "recorded" / "llm.jsonl"),
                          record_path=None, database_url=None, ledger_path=str(REPO_ROOT / ".pheri" / "t.sqlite")))
    text, clip = transcribe_rule_clip(replay, "owner-rule-hi")
    assert clip["recorded"] and text.replace("ज्या", "ज़्या") == RULE_CLIPS["owner-rule-hi"]["said"]


def _waiting(store, key, kind, pct=None, status="awaiting_approval"):
    """A step drafted before the rule existed (this test is about the flip, not the drafting)."""
    payload = {"channel": "whatsapp", "discount_pct": pct, "message": "Hi", "send_at": None}
    aid = store.add_action(key, kind, payload, "why", [], "ask_owner", {"allowed": True, "results": []}, status)
    if status == "awaiting_approval":
        store.add_approval(aid)
    return aid


def test_confirming_a_new_rule_blocks_the_waiting_steps_that_break_it_and_only_those(llm):
    from pheri.autonomy import block_for_new_rule, would_block

    store = MemoryStore("birgunj")
    ctx = lambda k: CheckContext("birgunj", {"country": "NP"}, MORNING)  # noqa: E731
    big = _waiting(store, "+9779800000001", "offer_discount", 15)
    small = _waiting(store, "+9779800000002", "offer_discount", 10, status="scheduled")
    nudge = _waiting(store, "+9779800000003", "answer_question")
    draft = propose(store, llm, "किसी भी ग्राहक को दस परसेंट से ज़्यादा डिस्काउंट मत देना।", actor="owner:test")
    assert draft.checks == [MaxDiscountPct(pct=10)]
    rule = Rule(draft.id, draft.source_text, draft.checks)
    assert [x["action_id"] for x in would_block(store, rule, ctx)] == [big]  # a preview changes nothing
    assert store.get_action(big)["status"] == "awaiting_approval"
    confirm(store, draft.id, by="owner:test")
    rule = next(r for r in active_rules(store) if r.id == draft.id)
    flipped = block_for_new_rule(store, rule, ctx, "owner:test")
    assert [x["action_id"] for x in flipped] == [big]
    a = store.get_action(big)
    assert a["status"] == "blocked" and a["rule_check"]["blocked_by_rule"]["text"] == draft.source_text
    assert "15" in a["rule_check"]["blocked_by_rule"]["reason"]
    assert store.approvals() == [p for p in store.approvals() if p["action_id"] != big]  # its approval closed
    assert store.get_action(small)["status"] == "scheduled" and store.get_action(nudge)["status"] == "awaiting_approval"
    assert any(e["event"] == "blocked_by_new_rule" for e in store.audit_log(big))


def test_speak_a_rule_end_to_end_through_the_api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api = TestClient(create_app(LLM(Settings())))
    assert api.post("/businesses/birgunj/rules/voice", json={"clip": "upload.wav", "by": "owner:test"}).status_code == 404
    r = api.post("/businesses/birgunj/rules/voice", json={"clip": "owner-rule-hi", "by": "owner:test"}).json()
    assert r["transcript"] == "किसी भी ग्राहक को दस परसेंट से ज़्यादा डिस्काउंट मत देना।"
    assert r["described"] == ["Block any discount over 10%."] and r["confirmable"] and "would_block" in r
    done = api.post(f"/businesses/birgunj/rules/{r['id']}/confirm", json={"by": "owner:test"}).json()
    assert done["active"] and isinstance(done["blocked"], list)


def test_a_visitor_approves_the_15_percent_offer_then_speaks_the_10_percent_rule_and_the_offer_flips(monkeypatch,
                                                                                                       tmp_path):
    """The demo, in one visitor's sandbox: the seed rule allows up to 15%; the owner picks "Offer up to 15% off (your
    limit)" on a money card, so a code-written 15% offer waits for 08:00; the owner's voice note (10%) is confirmed
    and the offer is blocked by it. Reset demo puts it all back; another visitor's copy never changes."""
    from fastapi.testclient import TestClient

    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_PUBLIC_DEMO", "1")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(LLM(Settings()))
    me, other = TestClient(app), TestClient(app)
    B = "/businesses/birgunj"
    offer = "Offer up to 15% off (your limit)"
    card = next(c for c in me.get(f"{B}/next-steps").json() if offer in (c.get("owner_options") or []))
    override = not card["verification"]["passed"]  # offline the stand-in writes English: a soft failure to override
    done = me.post(f"{B}/approvals/{card['approval']['id']}/approve", json={"by": "x", "choice": offer,
                                                                            "override": override})
    assert done.status_code == 200
    mine = lambda: next(c for c in me.get(f"{B}/next-steps").json()  # noqa: E731
                        if c["customer"]["key"] == card["customer"]["key"])
    o = mine()["owner_offer"]
    assert o["status"] == "scheduled" and o["pct"] == 15 and "15%" in o["message"] and o["blocked_by_rule"] is None
    spoken = me.post(f"{B}/rules/voice", json={"clip": "owner-rule-hi", "by": "x"}).json()
    assert [x["name"] for x in spoken["would_block"]] == [card["customer"]["name"]]
    confirmed = me.post(f"{B}/rules/{spoken['id']}/confirm", json={"by": "x"}).json()
    assert [x["name"] for x in confirmed["blocked"]] == [card["customer"]["name"]]
    o = mine()["owner_offer"]
    assert o["status"] == "blocked" and o["blocked_by_rule"]["text"] == spoken["transcript"]
    moments = me.get(f"{B}/brief").json()["rule_moments"]
    assert any(m["rule"].startswith("Your new rule") and m["customer"]["name"] == card["customer"]["name"]
               for m in moments)
    theirs = next(c for c in other.get(f"{B}/next-steps").json() if c["customer"]["key"] == card["customer"]["key"])
    assert theirs["owner_offer"] is None  # another visitor's sandbox: untouched
    me.post("/demo/reset")
    assert mine()["owner_offer"] is None and mine()["approval"]["decision"] == "pending"
    assert not any(r["source_text"] == spoken["transcript"] for r in me.get(f"{B}/rules").json())
