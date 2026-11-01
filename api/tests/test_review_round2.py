"""Native review, round 2 (1 Nov): photos sent by code, nothing unasked, policy answered from the shop file, nothing
said twice, late deliveries wait for the owner with an apology, the style rules, and histories that match their
messages. Offline (mock models)."""

import json

import pytest

from pheri.actions import ProposedAction
from pheri.config import REPO_ROOT, Settings
from pheri.journey import stage
from pheri.llm import LLM
from pheri.profile import build_profile, load
from pheri.rules import CheckContext, seed
from pheri.store import MemoryStore
from pheri.synth import NIGHT_RUN
from pheri.verify import Draft, context, verify_draft
from pheri.words import internal_ids, sign_and_greet

RAJESH = "+9779871054501"  # blouse didn't fit; asks to exchange it (shop policy, not the owner's call)
SHANTI = "+919325638241"  # wholesale: "the same lot as last time"
POOJA = "+917379003009"  # late delivery, Bhojpuri
DINESH = "+9779744844221"  # asks for new Tihar designs and photos


@pytest.fixture(scope="module")
def birgunj():
    return load("birgunj")


@pytest.fixture
def llm(tmp_path):
    return LLM(Settings(llm_mode="mock", record_path=None, database_url=None, ledger_path=str(tmp_path / "l.sqlite")))


def check(ds, llm, key, kind, message, facts=("journey_stage",), why="They wrote to the shop."):
    store = MemoryStore("birgunj")
    seed(store, llm, by="test")
    p = build_profile(ds, key, llm)
    j = stage("birgunj", p.facts, p.provenance.get("facts"))
    d = Draft(ProposedAction(kind=kind, channel="whatsapp", message=message, send_at=NIGHT_RUN), why, why,
              list(facts), [])
    return p, verify_draft(d, context(p, j, CheckContext("birgunj", p.facts, NIGHT_RUN), store, llm))


def failed(v):
    return {c["name"] for c in v.checks if c["applies"] and not c["passed"]}


# ---- 1. photos, sent by code; no photo id ever reaches a customer -------------------------------------------------
def test_send_photos_attaches_the_shops_own_photo_files_and_the_text_names_no_id(birgunj, llm):
    from pheri.shop import photos_for

    p = build_profile(birgunj, DINESH, llm)
    prov = p.provenance["facts"]
    photos = photos_for(prov["shop_stock"] + prov.get("shop_collection", []))
    assert photos and all((REPO_ROOT / "web" / "public" / p_["src"].lstrip("/")).exists() for p_ in photos)
    assert all((REPO_ROOT / "data" / "synth" / "birgunj" / "photos" / f"{p_['photo']}.png").exists() for p_ in photos)
    assert not any("PH-" in v for k, v in p.facts.items() if k.startswith("shop_"))  # no id in any fact
    _, v = check(birgunj, llm, DINESH, "send_photos", "नमस्ते दिनेश जी, तिहारका नयाँ डिजाइनको फोटो पठाएका छौं।",
                 facts=("journey_stage", "shop_collection"))
    assert "promises" not in failed(v) and "plain_words" not in failed(v)
    _, v = check(birgunj, llm, DINESH, "send_photos", "नमस्ते दिनेश जी, फोटो PH-101 पठाएका छौं।",
                 facts=("journey_stage", "shop_collection"))
    assert "plain_words" in failed(v) and "PH-101" in " ".join(v.reasons)
    assert internal_ids("photo BSG-S01") == ["BSG-S01"] and internal_ids("order BSG-7245") == []


def test_the_decision_carries_the_photos_code_attached(birgunj, llm, monkeypatch):
    from pheri import llm as llm_module
    from pheri.decide import PURPOSE, decide

    answer = {"action": "send_photos", "channel": "whatsapp", "discount_pct": None,
              "message": "नमस्ते दिनेश, तिहारका नयाँ डिजाइनको फोटो पठाएका छौं।", "why_this": "Dinesh asked for photos.",
              "why_now": "Tihar is coming.", "fact_keys": ["journey_stage", "shop_collection"], "quote_ids": []}
    monkeypatch.setitem(llm_module._mock_responders, PURPOSE, lambda m, s: json.dumps(answer, ensure_ascii=False))
    store = MemoryStore("birgunj")
    seed(store, llm, by="test")
    out = decide(build_profile(birgunj, DINESH, llm), store, llm, NIGHT_RUN)
    att = out.action["payload"]["attachments"]
    assert att and all(a["src"].startswith("/catalog/PH-") for a in att)
    assert "PH-" not in out.action["payload"]["message"]


# ---- 2. nothing unasked: the judge's claim x -----------------------------------------------------------------------
def test_the_judge_is_asked_whether_the_message_adds_anything_unasked(birgunj, llm, monkeypatch):
    from pheri import llm as llm_module

    seen = []
    real = llm_module._mock_responders["judge"]
    monkeypatch.setitem(llm_module._mock_responders, "judge",
                        lambda m, s: seen.append(json.loads(m[-1]["content"])) or real(m, s))
    check(birgunj, llm, DINESH, "answer_question", "नमस्ते दिनेश जी, तिहार कलेक्सन तयार छ।",
          facts=("journey_stage", "shop_collection"))
    x = next(c for c in seen[-1]["claims"] if c["id"] == "x")
    assert "adds nothing the customer didn't ask" in x["text"] and "cash on delivery" in seen[-1]["how_to_judge_x"]


# ---- 3. policy questions answered from the shop file -----------------------------------------------------------
def test_an_exchange_is_policy_so_handing_it_to_the_owner_fails(birgunj, llm):
    p, v = check(birgunj, llm, RAJESH, "answer_question",
                 "Hi Rajesh ji, exchange ko lagi sahuji aafai jawaf dinuhunchha.")
    assert p.facts["complaint_kind"] == "return_requested" and "shop_returns" in p.facts
    assert "answers" in failed(v)
    _, v = check(birgunj, llm, RAJESH, "answer_question",
                 "Hi Rajesh ji, size satna 7 din bhitra nishulka milchha, tag bhayeko hunu parchha.",
                 facts=("journey_stage", "shop_returns"))
    assert "answers" not in failed(v)


def test_the_same_as_last_time_is_answered_from_the_last_order_on_record(birgunj, llm):
    p, v = check(birgunj, llm, SHANTI, "offer_reorder", "नमस्ते शान्ति जी, साहुजी आज सुबह जवाब देंगे।")
    assert p.facts["asks_reorder"] and "जॉर्जेट" in p.facts["shop_last_order"]
    assert "answers" in failed(v)


# ---- 4. nothing said twice -----------------------------------------------------------------------------------------
def test_a_message_that_says_the_same_thing_twice_fails(birgunj, llm):
    _, v = check(birgunj, llm, "+9779748817775", "answer_question",
                 "नमस्ते रोहित जी, इस बारे में पक्की जानकारी साहुजी के पास है। साहुजी आज सुबह जवाब देंगे।")
    assert "repeats" in failed(v) and "once" in " ".join(v.reasons)


# ---- 5. late deliveries: always the owner's, and sorry first --------------------------------------------------------
def test_a_late_delivery_waits_for_the_owner_and_the_reply_opens_with_an_apology(birgunj, llm):
    from pheri.autonomy import owner_reason
    from pheri.decide import decide

    p = build_profile(birgunj, POOJA, llm)
    assert p.facts["complaint_kind"] == "late" and owner_reason(p.facts).startswith("Their order is")
    store = MemoryStore("birgunj")
    seed(store, llm, by="test")
    out = decide(p, store, llm, NIGHT_RUN)
    assert out.action["status"] == "awaiting_approval"
    msg = out.decision["message"]
    assert "Sorry for the delay." in msg or "माफी" in msg or "माफ़ी" in msg
    assert sign_and_greet("Hi Pooja, साहुजी जवाब दिहें।", "Pooja", "bho", apology=True).startswith(
        "प्रणाम पूजा जी, देरी खातिर माफी चाहत बानी।")
    assert sign_and_greet("नमस्ते अमित, साहुजी जवाब देंगे।", "Amit", "hi", apology=True).startswith(
        "नमस्ते अमित जी, देरी के लिए माफ़ी चाहते हैं।")


# ---- 6. style: money, counts, the greeting's script ------------------------------------------------------------------
def test_money_is_ru_or_rs_never_npr_and_the_greeting_is_in_the_replys_script():
    assert sign_and_greet("Namaste Sita, दाम NPR 1800 बा।", "Sita", "bho") == "प्रणाम सीता जी, दाम रु 1800 बा। – बिरगंज साड़ी घर"
    assert sign_and_greet("Hi Ranju, it is NPR 8500.", "Ranju", "en") == "Hi Ranju ji, it is Rs 8500. – Birgunj Saree Ghar"


def test_counts_are_for_wholesale_buyers_only():
    from pheri.shop import facts_for

    retail, _ = facts_for("यो बनारसी साडी अझै छ?", "Birgunj", "NP", "tihar")
    lot, _ = facts_for("यो बनारसी साडी अझै छ?", "Birgunj", "NP", "tihar", wholesale=True)
    assert "स्टकमा छ" in retail["shop_stock"] and "स्टकमा 4" in lot["shop_stock"]


# ---- 7. histories match the messages --------------------------------------------------------------------------------
def test_every_message_about_an_order_matches_that_order(birgunj):
    from pheri.history_check import mismatch

    bad = [(c.name, s.id) for c in birgunj.customers.values() for s in c.sources
           if s.text and mismatch(s.text, c.orders)]
    assert bad == []
    sanjay = next(c for c in birgunj.customers.values() if c.name == "Sanjay Karna")
    assert "Cotton saree" in sorted(sanjay.orders, key=lambda o: o["date"])[-1]["items"]


def test_someone_who_asks_for_photos_gets_the_send_photos_step_and_the_judge_sees_the_whole_message(birgunj, llm,
                                                                                                    monkeypatch):
    """Seen live: Bimala Pandey asked for photos and the reply handed them to the owner; and the judge, shown only
    the sentences, could not say whether a message answered ("no message provided")."""
    from pheri import llm as llm_module

    p, v = check(birgunj, llm, DINESH, "answer_question", "नमस्ते दिनेश जी, तिहार कलेक्सन स्टकमा छ।",
                 facts=("journey_stage", "shop_collection"))
    assert p.facts["asks_photos"] and "answers" in failed(v) and "send_photos" in " ".join(v.reasons)
    seen = []
    real = llm_module._mock_responders["judge"]
    monkeypatch.setitem(llm_module._mock_responders, "judge",
                        lambda m, s: seen.append(json.loads(m[-1]["content"])) or real(m, s))
    msg = "नमस्ते दिनेश जी, तिहारका नयाँ डिजाइनको फोटो पठाएका छौं।"
    check(birgunj, llm, DINESH, "send_photos", msg, facts=("journey_stage", "shop_collection"))
    assert seen[-1]["message"].startswith("नमस्ते दिनेश जी")


def test_the_judge_is_told_which_photos_code_attaches(birgunj, llm, monkeypatch):
    """Seen live: "फोटो पठाएका छौं" was judged unsupported, because nothing told the judge code sends the photos."""
    from pheri import llm as llm_module

    seen = []
    real = llm_module._mock_responders["judge"]
    monkeypatch.setitem(llm_module._mock_responders, "judge",
                        lambda m, s: seen.append(json.loads(m[-1]["content"])) or real(m, s))
    check(birgunj, llm, DINESH, "send_photos", "नमस्ते दिनेश जी, तिहारका नयाँ डिजाइनको फोटो पठाएका छौं।",
          facts=("journey_stage", "shop_collection"))
    assert seen[-1]["photos_attached_by_code"] and all("PH-" not in x for x in seen[-1]["photos_attached_by_code"])


# ---- the customer's language, not a neighbour's (1 Nov: Sita Shrestha, Bhojpuri, got "स्टकमा छ") ------------------
def test_nepali_words_in_a_bhojpuri_or_hindi_reply_fail_the_language_check_and_the_reverse():
    from pheri.words import foreign_words

    assert foreign_words("छठ खातिर पियर कॉटन साड़ी स्टकमा छ। फोटो पठाएका छौं।", "bho") == ["स्टकमा", "छ", "पठाएका", "छौं"]
    assert foreign_words("छठ की पीली कॉटन साड़ी स्टकमा छ।", "hi") == ["स्टकमा", "छ"]
    assert foreign_words("रातो बनारसी साडी स्टॉक में है।", "ne") == ["स्टॉक", "में", "है"]
    assert foreign_words("छठ खातिर पियर कॉटन साड़ी स्टॉक में बा। फोटो भेज देले बानी।", "bho") == []
    assert foreign_words("रातो बनारसी सिल्क साडी स्टकमा छ। फोटो पठाएका छौं।", "ne") == []


def test_a_bhojpuri_reply_with_nepali_words_fails_and_the_sign_off_never_counts(birgunj, llm):
    sita = next(k for k, c in birgunj.customers.items() if c.name == "Sita Shrestha")
    _, v = check(birgunj, llm, sita, "send_photos",
                 "नमस्ते सीता जी, छठ खातिर पियर कॉटन साड़ी स्टकमा छ। फोटो पठाएका छौं। – बिरगंज साड़ी घर",
                 facts=("journey_stage", "shop_stock"))
    assert "language" in failed(v) and "Nepali words (स्टकमा, छ" in " ".join(v.reasons)
    _, v = check(birgunj, llm, sita, "send_photos",
                 "नमस्ते सीता जी, छठ खातिर पियर कॉटन साड़ी स्टॉक में बा। फोटो भेज देले बानी। – बिरगंज साड़ी घर",
                 facts=("journey_stage", "shop_stock"))
    assert "language" not in failed(v)


def test_every_style_rule_is_one_line_so_the_brief_reads_all_of_it():
    """The brief takes the guide's "- " lines; a rule wrapped onto a second line would lose that line."""
    lines = (REPO_ROOT / "api" / "pheri" / "style_ne_hi.md").read_text(encoding="utf-8").splitlines()
    first_rule = next(i for i, x in enumerate(lines) if x.startswith("- "))
    assert all(x.startswith("- ") or not x.strip() for x in lines[first_rule:])
