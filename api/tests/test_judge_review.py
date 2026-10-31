"""The judges' review of the screens (31 Oct), one fix at a time:
1. questions get answers; 2. no internal ids on screen; 3. no promise without a fact; 4. a fair Slop vs Pheri;
5. the customer's script; 6. the customer's own numbers stay out of the message, Bhojpuri counted on its own.
Offline (mock models), except the replay test that scans everything an owner reads."""

import json
import re
from datetime import datetime, timezone

import pytest

from pheri.actions import ProposedAction
from pheri.config import REPO_ROOT, Settings
from pheri.journey import stage
from pheri.llm import LLM
from pheri.profile import build_profile, load
from pheri.rules import CheckContext, seed
from pheri.store import MemoryStore
from pheri.synth import NIGHT_RUN
from pheri.verify import HARD_CHECKS, Draft, context, middle_step, verify_draft
from pheri.words import internal_ids, open_question, plain, plain_reason, promises, read_language

BIKASH = "+9779730782013"  # loyal, writes Roman Nepali, asked about new designs
KIRAN = "+919158674439"  # gone quiet: 108 days since the last order
SHANTI = "+919325638241"  # wholesale, asked for nothing (a request, no question)
TEAM = " - The Birgunj Saree Ghar team"


@pytest.fixture(scope="module")
def birgunj():
    return load("birgunj")


@pytest.fixture
def llm(tmp_path):
    return LLM(Settings(llm_mode="mock", record_path=None, database_url=None, ledger_path=str(tmp_path / "l.sqlite")))


def check(ds, llm, key, kind, message, why="They wrote to the shop.", facts=("journey_stage",)):
    store = MemoryStore("birgunj")
    seed(store, llm, by="test")
    p = build_profile(ds, key, llm)
    j = stage("birgunj", p.facts, p.provenance.get("facts"))
    d = Draft(ProposedAction(kind=kind, channel="whatsapp", message=message, send_at=NIGHT_RUN), why, why,
              list(facts), [])
    return p, verify_draft(d, context(p, j, CheckContext("birgunj", p.facts, NIGHT_RUN), store, llm))


def failed(v):
    return {c["name"] for c in v.checks if c["applies"] and not c["passed"]}


# ---- 1. questions get answers -------------------------------------------------------------------------
def test_code_reads_whether_a_customer_asked_something():
    assert open_question("rato saree ajhai stock ma chha? tihar ma lagaunu chha.")
    assert open_question("ब्लाउजको साइज कसरी छान्ने")  # no question mark: the question word is enough
    assert not open_question("अगले हफ्ते पिछली बार जैसा लॉट भेज दीजिए।")  # a request, not a question


def test_an_open_question_gets_an_answer_first_and_an_answer_needs_a_question():
    asked = middle_step("birgunj", "loyal", "recommend_product", open_question=True)
    assert not asked["passed"] and "answer it first" in asked["reasons"][0]
    assert middle_step("birgunj", "loyal", "answer_question", open_question=True)["passed"]
    assert middle_step("birgunj", "complaint", "send_help", open_question=True)["passed"]  # help answers a problem
    nothing = middle_step("birgunj", "wholesale", "answer_question", open_question=False)
    assert not nothing["passed"] and "no question" in nothing["reasons"][0]
    assert middle_step("birgunj", "loyal", "recommend_product", open_question=False)["passed"]


def test_the_judge_is_asked_whether_the_message_answers_the_question(birgunj, llm, monkeypatch):
    from pheri import llm as llm_module

    seen = []
    real = llm_module._mock_responders["judge"]
    monkeypatch.setitem(llm_module._mock_responders, "judge", lambda m, s: seen.append(json.loads(m[-1]["content"]))
                        or real(m, s))
    msg = "Hi Bikash, thank you for asking. The owner will answer your question this morning." + TEAM
    _, v = check(birgunj, llm, BIKASH, "answer_question", "Hi Bikash, " + "dhanyabad sodhnu bhayeko ma. Sahuji le "
                 "aaja bihana jawaf dinuhunchha." + TEAM)
    sent = seen[-1]
    assert sent["customer_question"].startswith("pohor ko dhaka saree") and sent["claims"][-1]["id"] == "q"
    assert any(r["claim_id"] == "q" and r["supported"] for r in v.judge)
    seen.clear()
    _, v = check(birgunj, llm, BIKASH, "recommend_product", msg)  # ignores the question: the plan check and judge
    assert "middle_step" in failed(v)


def test_the_offline_stand_in_answers_a_question_before_anything_else(birgunj, llm):
    from pheri.decide import decide

    store = MemoryStore("birgunj")
    seed(store, llm, by="test")
    out = decide(build_profile(birgunj, BIKASH, llm), store, llm, NIGHT_RUN)
    assert out.decision["action"] == "answer_question"


# ---- 2. no internal ids in what an owner or a customer reads --------------------------------------------
def test_internal_ids_are_found_and_said_in_plain_words():
    assert internal_ids("Kiran is gone_quiet; send_checkin fits; the message reads as 'en'") == \
        ["gone_quiet", "send_checkin", "'en'"]
    assert plain("send_help for a return_requested order, 'ne-Latn'") == \
        "send help for a asked to return it order, Roman Nepali"
    assert plain_reason("middle_step: offer_reorder fits 0%") == "The plan: time to reorder fits 0%"
    assert internal_ids("Hi Asha, the owner will reply this morning.") == []


def test_a_draft_that_uses_internal_names_fails_plain_words(birgunj, llm):
    _, v = check(birgunj, llm, SHANTI, "offer_reorder", "Hi Shanti, would you like the same lot as last time?" + TEAM,
                 why="Shanti is wholesale, so offer_reorder fits the days_since_last_order.")
    assert "plain_words" in failed(v) and "offer_reorder" in " ".join(v.reasons)


# ---- 3. promises need a fact or an allowed action (hard) ---------------------------------------------------
@pytest.mark.parametrize("message,kind", [
    ("We can deliver it tomorrow.", "delivery"),
    ("bholi samma pugchha.", "delivery"),
    ("I've sent you the photos already.", "photos"),
    ("फोटो पठाएको छु।", "photos"),
    ("The red saree is still in stock, only 2 left!", "stock"),
    ("rato saree ajhai stock ma chha.", "stock"),
    ("नयाँ डिजाइन राखेका छौं।", "stock"),
    ("चाडबाडमा छिटो सकिन्छ।", "stock"),  # fake scarcity, from a recorded plain draft
    ("फोटो भर्खरै पठाइदिएको छु।", "photos"),  # "I just sent the photo", from a recorded plain draft
    ("It is Rs 4500 for the set.", "price"),
    ("Here is 20% off for Tihar.", "discount"),
])
def test_a_promise_no_fact_backs_is_found_in_every_language(message, kind):
    assert [k for k, _, _ in promises(message, "", "send_checkin")] == [kind]


def test_handing_it_to_the_owner_is_not_a_promise_and_an_offer_carries_its_discount():
    assert promises("The owner will confirm the delivery date and send photos this morning.", "", "answer_question") == []
    assert promises("साहुजीले आज बिहान फोटो पठाउनुहुन्छ।", "", "answer_question") == []
    assert promises("Here is 10% off your next order.", "", "offer_discount") == []
    assert promises("Hi Asha, how are you finding the saree?", "", "send_checkin") == []


def test_a_promise_fails_the_draft_hard(birgunj, llm):
    _, v = check(birgunj, llm, BIKASH, "answer_question", "Hi Bikash, naya design aayeko chha, bholi pathaunchhau."
                 + TEAM)
    assert "promises" in failed(v) and "promises" in HARD_CHECKS and not v.overridable
    assert v.judge_ran is False  # code stopped it: the judge is not paid to read it


# ---- 4. Slop vs Pheri: the plain draft is judged too, its lies first ----------------------------------------
def test_the_plain_draft_gets_the_judge_and_the_promise_check_and_lies_come_first(birgunj, llm):
    from pheri import slop

    key = next(k for k, c in birgunj.customers.items() if c.name == "Kiran Chaudhary")
    out = slop.compare(birgunj, key, MemoryStore("birgunj"), llm, NIGHT_RUN)["plain"]
    checks = [f["check"] for f in out["failed"]]
    assert "promises" in checks and out["judged"] >= 1  # the stand-in's "Rs 3000" is in no record
    first_generic = min((i for i, c in enumerate(checks) if c not in ("promises", "facts", "money", "rules", "links",
                                                                         "pronouns")), default=len(checks))
    assert all(c in ("promises", "facts", "money", "rules", "links", "pronouns") for c in checks[:first_generic])
    assert any(s["struck"] and any("Offers money off" in r for r in s["reasons"]) for s in out["sentences"])
    assert any("Gives no reason" in x for x in out["structural"])  # the generic failure: last, in one line


# ---- 5. the customer's script -----------------------------------------------------------------------------
def test_roman_nepali_in_roman_nepali_out(birgunj, llm):
    p, v = check(birgunj, llm, BIKASH, "answer_question",
                 "Hi Bikash, सोध्नुभएकोमा धन्यवाद। साहुजीले आज बिहान जवाफ दिनुहुन्छ।" + TEAM)
    assert p.writes_in == "ne-Latn"
    assert "language" in failed(v) and "writes Nepali in Latin letters" in " ".join(v.reasons)
    _, v = check(birgunj, llm, BIKASH, "answer_question",
                 "Hi Bikash, sodhnu bhayeko ma dhanyabad. Sahuji le aaja bihana jawaf dinuhunchha." + TEAM)
    assert "language" not in failed(v)


def test_code_reads_roman_nepali_and_bhojpuri_on_messages_it_was_not_tuned_on():
    """evals/scale/messages.jsonl, the test split (markers were added from dev-split misses only). Pinned as
    measured on 31 Oct; Bhojpuri shares most of its small words with Hindi, so it stays the weakest."""
    rows = [json.loads(x) for x in (REPO_ROOT / "evals" / "scale" / "messages.jsonl").read_text(encoding="utf-8")
            .splitlines()]
    test = [r for r in rows if r["split"] == "test"]
    right = {lang: sum(read_language(r["text"]) == lang for r in test if r["lang"] == lang)
             for lang in ("ne", "ne-Latn", "hi", "bho", "en")}
    assert right == {"ne": 49, "ne-Latn": 53, "hi": 55, "bho": 36, "en": 59}  # of 60, 60, 57, 60, 59


# ---- 6. their own numbers stay in why; Bhojpuri is counted on its own; quotes are plain ----------------------
def test_a_message_never_quotes_the_customers_own_numbers(birgunj, llm):
    _, v = check(birgunj, llm, KIRAN, "send_checkin",
                 "Hi Kiran, it has been 108 days since your last order. How are you?" + TEAM,
                 facts=("journey_stage", "days_since_last_order"))
    assert "private_stats" in failed(v) and "108 (days since their last order)" in " ".join(v.reasons)
    _, v = check(birgunj, llm, KIRAN, "send_checkin", "Hi Kiran, it has been a while. How are you?" + TEAM,
                 why="Kiran last ordered 108 days ago.", facts=("journey_stage", "days_since_last_order"))
    assert "private_stats" not in failed(v)  # the number stays in why, for the owner


def test_the_night_counts_bhojpuri_on_its_own(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    brief = TestClient(create_app(LLM(Settings()))).get("/businesses/birgunj/brief").json()
    by = brief["read"]["by_language"]
    night = json.loads((REPO_ROOT / "data" / "synth" / "birgunj" / "_truth.json").read_text(encoding="utf-8"))["night"]
    assert by.get("bho") == sum(n["lang"] == "bho" for n in night if n["role"] != "voice_ne") == 4
    assert by.get("ne-Latn", 0) > 0  # Roman Nepali counted on its own too


ID = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b|(['\"])(en|ne|hi|bho|ne-Latn)\1")


def owner_texts(obj, path=""):
    """Every string an owner or a customer reads in an API answer (ids, keys and raw records excluded)."""
    skip = {"key", "customer_key", "id", "action_id", "source_id", "quote_id", "ref", "kind", "status", "stage",
            "action", "label", "language", "lang", "written_in", "check", "caught_by", "provider", "model", "channel",
            "hard_failed", "soft_failed", "failed", "detail", "receipt", "evidence", "approval", "payload",
            "rule_check", "mode", "event", "at", "night", "morning", "sha", "fact", "screen_before", "screen_after",
            "by_language", "proof", "fact_keys", "quote_ids", "outcome", "refused", "decided_by", "override",
            "unsupported_numbers", "message_problems", "skipped", "fallback"}  # ids by design, shown through labels
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in skip and not (k == "then" and obj.get("refused")):  # "then" is an action id after a refusal
                yield from owner_texts(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from owner_texts(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def test_nothing_an_owner_reads_carries_an_internal_id(monkeypatch, tmp_path):
    """The recorded night, replayed: the brief, every card (message, why, the reasons a draft was caught), Slop vs
    Pheri and the replies. Each string an owner (or customer) reads is scanned for snake_case ids and quoted
    language codes. The web pages are scanned too (web/scripts/evidence.mjs)."""
    from fastapi.testclient import TestClient

    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "replay")
    monkeypatch.setenv("PHERI_LLM_REPLAY", str(REPO_ROOT / "data" / "recorded" / "llm.jsonl"))
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("PHERI_LLM_RECORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api = TestClient(create_app(LLM(Settings())))
    found = []
    for b in ("birgunj", "brightdesk"):
        for url in (f"/businesses/{b}/brief", f"/businesses/{b}/next-steps", f"/businesses/{b}/slop",
                    f"/businesses/{b}/replies"):
            for path, text in owner_texts(api.get(url).json()):
                if m := ID.search(text):
                    found.append(f"{url}{path}: {m.group(0)!r} in {text[:80]!r}")
    assert found == []


# ---- follow-up (31 Oct): the danda splits claims; the shop's style guide reaches the prompt -----------------
NISHA = "+9779844919678"  # new, writes Nepali in Devanagari, asked about blouse sizes


def test_a_devanagari_draft_is_judged_sentence_by_sentence_and_one_false_claim_fails_alone(birgunj, llm, monkeypatch):
    """Three sentences ended by the danda: three claims, not one. The judge (scripted here) rejects only the false
    one, and the reason names that sentence alone."""
    from pheri import llm as llm_module

    false = "हजुरको अर्डर हिजो नै पठाइसकेका छौं।"  # "we sent your order yesterday": nothing in the record says so
    seen = []

    def judge(messages, schema):
        data = json.loads(messages[-1]["content"])
        seen.append(data["claims"])
        return json.dumps({"verdicts": [{"claim_id": c["id"], "supported": c["text"] != false,
                                         "reason": "no cited fact says it was sent" if c["text"] == false else "ok"}
                                        for c in data["claims"]]})
    monkeypatch.setitem(llm_module._mock_responders, "judge", judge)
    msg = f"नमस्ते निशा, सोध्नुभएकोमा धन्यवाद। {false} साहुजीले आज बिहान साइजको जवाफ दिनुहुन्छ। - Birgunj Saree Ghar टिम"
    _, v = check(birgunj, llm, NISHA, "answer_question", msg)
    said = [c["text"] for c in seen[-1] if c["id"] != "q"]
    assert said[:3] == ["नमस्ते निशा, सोध्नुभएकोमा धन्यवाद।", false, "साहुजीले आज बिहान साइजको जवाफ दिनुहुन्छ।"]
    flagged = [r["claim"] for r in v.judge if not r["supported"]]
    assert flagged == [false] and v.caught_by == "judge" and not v.passed


def test_the_shops_style_guide_reaches_its_brief_line_by_line(birgunj, llm, tmp_path, monkeypatch):
    """style_ne_hi.md, every "- " line, word for word, in Birgunj's brief (the first user turn); never in the system
    prompt (Pheri's behaviour, the same for every shop) and never in Brightdesk's brief. A rule the owner adds to
    the file reaches the next brief."""
    from pheri import decide
    from pheri import llm as llm_module

    rules = [x for x in decide.STYLE_GUIDE.read_text(encoding="utf-8").splitlines() if x.startswith("- ")]
    assert len(rules) >= 5 and any("साहुजी" in r and "ओनर" in r for r in rules)
    assert not any(r in decide.SYSTEM or r in decide.PRIVATE_SYSTEM for r in rules)
    briefs = {}
    real = llm_module._mock_responders[decide.PURPOSE]

    def spy(messages, schema):
        first = json.loads(messages[1]["content"])
        briefs[first["business"]] = first
        return real(messages, schema)
    monkeypatch.setitem(llm_module._mock_responders, decide.PURPOSE, spy)
    guide = tmp_path / "style_ne_hi.md"
    guide.write_text(decide.STYLE_GUIDE.read_text(encoding="utf-8") + "- Never use the word 'ग्राहक'.\n",
                     encoding="utf-8")
    monkeypatch.setattr(decide, "STYLE_GUIDE", guide)
    store = MemoryStore("birgunj")
    seed(store, llm, by="test")
    decide.decide(build_profile(birgunj, NISHA, llm), store, llm, NIGHT_RUN)
    assert briefs["birgunj"]["style_guide"]["rules"] == rules + ["- Never use the word 'ग्राहक'."]
    assert "Nepali, Hindi or Bhojpuri" in briefs["birgunj"]["style_guide"]["follow_when"]
    bd = load("brightdesk")
    decide.decide(build_profile(bd, next(iter(bd.customers)), llm), MemoryStore("brightdesk"), llm)
    assert "style_guide" not in briefs["brightdesk"]


def test_code_written_replies_follow_the_style_guide_too():
    from pheri.holding import TEMPLATES

    for lang in ("ne", "hi", "bho"):
        assert "साहुजी" in TEMPLATES[lang] and "ओनर" not in TEMPLATES[lang] and "मालिक" not in TEMPLATES[lang]
    assert "Sahuji" in TEMPLATES["ne-Latn"]
