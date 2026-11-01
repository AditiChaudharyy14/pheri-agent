"""The native review (31 Oct): answers from the shop's own facts, a voice note no model can read, festival names,
the shop's sign-off and the customer's name, and the style guide. Offline (mock models)."""

import json

import pytest

from pheri.actions import ProposedAction
from pheri.config import REPO_ROOT, Settings
from pheri.journey import stage
from pheri.llm import LLM
from pheri.profile import build_profile, compute_facts, load
from pheri.rules import CheckContext, seed
from pheri.shop import facts_for
from pheri.store import MemoryStore
from pheri.synth import NIGHT_RUN
from pheri.verify import Draft, claims, context, verify_draft
from pheri.words import SIGN_OFF, festival_word, festivals_named, promises, sign_and_greet

ANITA = "+9779831380373"  # new, Hetauda, asked "Do you deliver to Hetauda?"
RANJU = "+9779820823938"  # asked whether the Banarasi saree is still there, and about cash on delivery
SITA_KARNA = "+918965164000"  # Raxaul wholesale, asked for a lower rate (money: the owner's)
ROHIT_ANSARI = "+9779732136611"  # newest message: a voice note in Nepali, which no model reads


@pytest.fixture(scope="module")
def birgunj():
    return load("birgunj")


@pytest.fixture
def llm(tmp_path):
    return LLM(Settings(llm_mode="mock", record_path=None, database_url=None, ledger_path=str(tmp_path / "l.sqlite")))


def check(ds, llm, key, kind, message, facts=("journey_stage",), why="They asked the shop something."):
    store = MemoryStore("birgunj")
    seed(store, llm, by="test")
    p = build_profile(ds, key, llm)
    j = stage("birgunj", p.facts, p.provenance.get("facts"))
    d = Draft(ProposedAction(kind=kind, channel="whatsapp", message=message, send_at=NIGHT_RUN), why, why,
              list(facts), [])
    return p, verify_draft(d, context(p, j, CheckContext("birgunj", p.facts, NIGHT_RUN), store, llm))


def failed(v):
    return {c["name"] for c in v.checks if c["applies"] and not c["passed"]}


# ---- 1. the shop's own facts ------------------------------------------------------------------------------
def test_the_shop_file_answers_what_the_message_asks_and_nothing_else():
    shop = json.loads((REPO_ROOT / "data" / "synth" / "birgunj" / "shop.json").read_text(encoding="utf-8"))
    assert {"catalog", "size_guide", "delivery", "cod", "returns", "collections", "festival_names"} <= set(shop)
    assert all({"ne", "hi", "bho"} <= set(it["names"]) for it in shop["catalog"])  # a name in every language
    assert {"Birgunj", "Kalaiya", "Janakpur", "Hetauda", "Bettiah", "Raxaul"} <= set(shop["delivery"])
    f, prov = facts_for("First time ordering here. Do you deliver to Hetauda?", "Birgunj", "NP", "tihar")
    assert f == {"shop_delivery": "Hetauda: 2 days, delivery charge Rs 150"} and prov["shop_delivery"] == ["shop:delivery"]
    f, _ = facts_for("यो बनारसी साडी अझै छ? क्यास अन डेलिभरी हुन्छ?", "Birgunj", "NP", "tihar")
    assert f["shop_stock"].startswith("रातो बनारसी सिल्क साडी: स्टकमा छ, रु 8500")  # their language; retail: no count
    assert f["shop_cod"].startswith("नेपालभित्र रु 15000")  # the rule in their language
    f, _ = facts_for("cash on delivery milega?", "Raxaul", "IN", "tihar")
    assert "no cash on delivery" in f["shop_cod"]  # across the border: pay first
    f, _ = facts_for("ब्लाउजको साइज कसरी छान्ने?", "Birgunj", "NP", "tihar")
    assert "छातीको सबैभन्दा फराकिलो भाग नापेर १ इन्च थप्नुहोस्" in f["shop_size_guide"]  # the Nepali size line
    assert facts_for("Thank you, the saree was lovely.", "Birgunj", "NP", "tihar")[0] == {}
    # "any more like last time?" names nothing: the last order does, if it is the kind of thing they named
    assert "Kurta set" in facts_for("is there the same again, like last time?", "Birgunj", "NP", None,
                                    last_item="Kurta set")[0]["shop_stock"]
    assert facts_for("वैसी साड़ी और है?", "Birgunj", "NP", None, last_item="Kurta set")[0] == {}


def test_a_deferral_on_a_question_the_shop_can_answer_fails(birgunj, llm):
    p, v = check(birgunj, llm, ANITA, "answer_question",
                 "Hi Anita, thank you for asking. The owner will answer your question this morning.")
    assert "shop_delivery" in p.facts and "answers" in failed(v) and not v.passed
    _, v = check(birgunj, llm, ANITA, "answer_question", "Hi Anita, yes: Hetauda is 2 days away, delivery NPR 150.",
                 facts=("journey_stage", "shop_delivery"))
    assert "answers" not in failed(v) and "promises" not in failed(v) and "facts" not in failed(v)


def test_money_stays_the_owners_so_deferring_it_is_right(birgunj, llm):
    p, v = check(birgunj, llm, SITA_KARNA, "offer_reorder",
                 "Hi Sita, your request for the next lot is noted. The owner will reply about the rate this morning.")
    assert p.facts["asks_about_money"] and "answers" not in failed(v)


def test_a_cited_shop_fact_backs_a_delivery_time_and_stock():
    assert promises("It reaches Hetauda within 2 days.", "hetauda: 2 days", "answer_question", ["shop_delivery"]) == []
    assert [k for k, _, _ in promises("It reaches Hetauda within 2 days.", "", "answer_question")] == ["delivery"]
    assert promises("The red saree is still in stock.", "4 in stock", "answer_question", ["shop_stock"]) == []
    assert promises("We have sent the photos.", "", "send_photos", ["shop_stock"]) == []  # code attaches them
    assert [k for k, _, _ in promises("We have sent the photos.", "", "answer_question", ["shop_stock"])] == ["photos"]


def test_the_brief_reports_the_deferral_rate(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    q = TestClient(create_app(LLM(Settings()))).get("/businesses/birgunj/brief").json()["questions"]
    assert q["asked"] > 0 and q["answered"] + q["deferred"] == q["asked"]
    assert q["deferral_rate"] == round(q["deferred"] / q["asked"], 3)


# ---- 2. a voice note no model can read -----------------------------------------------------------------------
def test_an_unreadable_voice_note_gets_only_the_fixed_reply_and_no_model(birgunj, llm, monkeypatch):
    from pheri.decide import decide_customer
    from pheri.holding import VOICE_TEMPLATES, holding_reply_for

    calls = []
    real = llm.complete
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: calls.append(kw.get("purpose")) or real(*a, **kw))
    store = MemoryStore("birgunj")
    seed(store, llm, by="test")
    calls.clear()
    out = decide_customer(birgunj, ROHIT_ANSARI, store, llm, NIGHT_RUN)
    assert calls == [] and out.skipped == "voice_note" and out.decision["action"] == "no_action"
    reply = holding_reply_for(store, ROHIT_ANSARI)
    assert reply["payload"]["message"] == VOICE_TEMPLATES["ne"].format(name="रोहित जी")
    assert "आवाज सन्देश पाइयो, साहुजीले सुनेर जवाफ दिनुहुन्छ" in reply["payload"]["message"]
    assert reply["status"] == "scheduled" and reply["payload"]["verification"]["passed"]


# ---- 3. festival names ------------------------------------------------------------------------------------------
def test_tihar_diwali_and_deepawali_are_one_festival_for_the_judge_and_the_customers_word_is_kept(birgunj, llm,
                                                                                                   monkeypatch):
    from pheri import llm as llm_module

    assert festival_word(["दिवाली से पहले चाहिए था।", "कब तक आएगा?"]) == "दिवाली"
    assert festival_word(["Dashain ko lagi"]) == "Dashain" and festival_word(["no festival"]) is None
    assert set(festivals_named("before Diwali")["tihar"]) >= {"Tihar", "Diwali", "Deepawali"}
    assert set(festivals_named("दशहरा")["dashain"]) >= {"Dashain", "Dussehra", "Vijayadashami"}
    seen = []
    real = llm_module._mock_responders["judge"]
    monkeypatch.setitem(llm_module._mock_responders, "judge",
                        lambda m, s: seen.append(json.loads(m[-1]["content"])) or real(m, s))
    check(birgunj, llm, "+9779844919678", "answer_question", "Hi Nisha, the Diwali collection is ready to see.",
          facts=("journey_stage", "next_festival"))
    if seen:  # the judge ran: it was told the names mean the same festival
        assert "Diwali" in seen[-1]["festival_names_that_mean_the_same"]["tihar"]


# ---- 4. the shop's sign-off and the customer's name, set by code -----------------------------------------------
@pytest.mark.parametrize("message,first,lang,out", [
    ("नमस्ते दिनेशज्यू। नयाँ डिजाइन छ। - Birgunj Saree Ghar टिम", "Dinesh", "ne",
     "नमस्ते दिनेश जी। नयाँ डिजाइन छ। – बिरगंज साडी घर"),
    ("नमस्ते Amit, आपका ऑर्डर निकल गया। - टीम", "Amit", "hi", "नमस्ते अमित जी, आपका ऑर्डर निकल गया। – बिरगंज साड़ी घर"),
    ("प्रणाम सीता, साहुजी जवाब दिहें। Birgunj Saree Ghar की टीम", "Sita", "bho", "प्रणाम सीता जी, साहुजी जवाब दिहें। – बिरगंज साड़ी घर"),
    ("Hi Bikash, naya design aayo. Birgunj Saree Ghar team", "Bikash", "ne-Latn",
     "Hi Bikash ji, naya design aayo. – Birgunj Saree Ghar"),
])
def test_code_sets_the_sign_off_and_the_name_in_the_replys_script(message, first, lang, out):
    assert sign_and_greet(message, first, lang) == out


def test_the_sign_off_is_not_a_claim_and_every_birgunj_draft_ends_with_it(birgunj, llm):
    from pheri.decide import decide

    d = Draft(ProposedAction(kind="answer_question", channel="whatsapp",
                             message="नमस्ते निशा जी। साइज ३२ देखि ४४ सम्म छ। – बिरगंज साडी घर"), "", "", [], [])
    assert claims(d) == ["नमस्ते निशा जी।", "साइज ३२ देखि ४४ सम्म छ।"]
    store = MemoryStore("birgunj")
    seed(store, llm, by="test")
    out = decide(build_profile(birgunj, ANITA, llm), store, llm, NIGHT_RUN)
    assert out.decision["message"].endswith(SIGN_OFF["en"]) and out.decision["message"].startswith("Hi Anita ji,")


# ---- 5. the style guide ---------------------------------------------------------------------------------------
def test_the_review_rules_are_in_the_style_guide():
    from pheri.decide import style_rules

    rules = "\n".join(style_rules("birgunj"))
    for must in ("दिहें", "भेजिहें", "देब", "आजु भोरे", "Never add context the customer didn't give",
                 "धन्यवाद for your question", "Never guess the owner's or the customer's gender",
                 "their_word_for_the_festival"):
        assert must in rules, must


def test_the_plan_check_refusing_an_answer_is_not_counted_as_the_owners_rule(monkeypatch, tmp_path):
    """Seen in the recorded night: answer_question refused for a customer who asked nothing showed as "your rules
    stopped" a step. Only the owner's rules (and do-not-contact) are rule moments."""
    from fastapi.testclient import TestClient

    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "replay")
    monkeypatch.setenv("PHERI_LLM_REPLAY", str(REPO_ROOT / "data" / "recorded" / "llm.jsonl"))
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("PHERI_LLM_RECORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    moments = TestClient(create_app(LLM(Settings()))).get("/businesses/birgunj/brief").json()["rule_moments"]
    assert moments and not any(m["rule"].startswith("they asked") for m in moments)


def test_a_devanagari_spelling_variant_of_the_name_still_gets_the_honorific():
    assert sign_and_greet("नमस्ते रन्जु, रातो साडी स्टकमा छ।", "Ranju", "ne") == \
        "नमस्ते रञ्जु जी, रातो साडी स्टकमा छ। – बिरगंज साडी घर"
    assert sign_and_greet("नमस्ते, तपाईंको अर्डर आयो।", "Ranju", "ne") == "नमस्ते, तपाईंको अर्डर आयो। – बिरगंज साडी घर"


def test_product_names_come_in_the_customers_language_never_english():
    f, _ = facts_for("छठ खातिर नया डिजाइन आइल बा? फोटो भेजीं।", "Birgunj", "NP", "chhath")
    assert f["shop_stock"] == "छठ खातिर पियर कॉटन साड़ी: स्टॉक में बा, रु 1800"
    assert f["shop_collection"].startswith("छठ कलेक्शन: छठ खातिर पियर कॉटन साड़ी")
    f, _ = facts_for("छठ के लिए नए डिज़ाइन आए हैं? फोटो भेजिए।", "Birgunj", "NP", "chhath")
    assert f["shop_stock"].startswith("छठ की पीली कॉटन साड़ी")
    f, _ = facts_for("Is the red saree still in stock?", "Birgunj", "NP", "tihar")
    assert f["shop_stock"].startswith("Red Banarasi silk saree: in stock, Rs 8500")
    import re
    for lang_text in ("यो बनारसी साडी अझै छ?", "छठ के लिए नए डिज़ाइन आए हैं?", "छठ खातिर नया डिजाइन आइल बा?"):
        values = " ".join(facts_for(lang_text, "Birgunj", "NP", "chhath")[0].values())
        assert not re.search(r"(saree|silk|cotton|Banarasi|in stock|photo)", values, re.I), values


def test_code_fixes_the_misspellings_the_model_wrote():
    from pheri.words import fix_spelling

    assert fix_spelling("साहुजी आफैं जवाफ दिनुहुछ आज बिहान। रङ्गको विषयमा कुरा हुछ।") ==         "साहुजी आफैं जवाफ दिनुहुन्छ आज बिहान। रङ्गको विषयमा कुरा हुन्छ।"
    assert sign_and_greet("नमस्ते अमित, साहुजी दिनुहछ।", "Amit", "ne").startswith("नमस्ते अमित जी, साहुजी दिनुहुन्छ।")
