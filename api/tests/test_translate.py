"""In English, for readers: Muse Spark 1.3's translations of the customer's words and the shop's replies, checked in
code before any is shown, recorded and replayed, and never sent."""

import json

import pytest
from fastapi.testclient import TestClient

from pheri import translate
from pheri.config import REPO_ROOT, Settings
from pheri.llm import LLM, register_mock

BG = "/businesses/birgunj"


# ---- code's check: a translation may not add a number or a claim ------------------------------------------
def test_a_faithful_translation_passes():
    assert translate.check("ब्लाउजको साइज कसरी छान्ने?", "How do I choose the blouse size?") == []
    assert translate.check("दस परसेंट से ज्यादा डिस्काउंट मत देना", "Do not give more than 10% discount.") == []  # दस = 10
    assert translate.check("tihar ko lagi tinwata banarasi saree linchhu", "I'll take three Banarasi sarees for Tihar.") == []
    assert translate.check("जॉर्जेट साड़ी स्टॉक में है, रु 2400 (₹1500)", "Georgette saree is in stock, Rs 2,400 (₹1,500).") == []
    assert translate.check("बिहान ८ बजे", "at 8:00 in the morning") == []  # Devanagari digits; "8:00" says 8


def test_a_translation_that_adds_a_number_or_a_promise_is_withheld():
    assert translate.check("ब्लाउजको साइज कसरी छान्ने?", "How do I choose the size? It will arrive tomorrow, Rs 500.") == [
        "adds numbers the original doesn't have: 500",
        "adds a claim the original doesn't make: promises a delivery time, states a price"]
    assert translate.check("नमस्ते सीता जी", "Hello Sita ji, we have 20% off for you.")[0].startswith("adds numbers")
    assert translate.check("नमस्ते", "")[0] == "no translation"
    assert translate.check("नमस्ते", " ".join(["word"] * 30))[0].startswith("runs long")


def test_the_original_is_read_loosely_so_an_honest_translation_is_not_withheld():
    """The promises check knows only some ways of saying things; the original side reads topics loosely. These two
    were withheld on the first recording (1 Nov) though both were faithful."""
    assert translate.check("नमस्कार दिनेश जी, तिहारका लागि नयाँ डिजाइन स्टकमा छ। फोटो पठाएका छौं।",
                           "Hello Dinesh ji, the new design for Tihar is in stock. We have sent photos.") == []
    assert translate.check("Nalagayeko ra tag bhayeko saman 7 din bhitra satna milchha.",
                           "Unworn items with the tag can be exchanged within 7 days.") == []


def test_the_shop_name_stays_a_name():
    assert translate.keep_names("Thanks. – Birgunj Saree House") == "Thanks. – Birgunj Saree Ghar"


def test_a_rejected_item_goes_back_once_with_the_reasons_then_is_withheld(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    seen = []

    def adds_a_price(messages, schema):
        seen.append(messages)
        items = json.loads(messages[1]["content"])["items"]
        return json.dumps({"items": [{"id": x["id"], "english": "Hello, it costs Rs 900."} for x in items]})

    register_mock(translate.PURPOSE, adds_a_price)
    try:
        out = translate.translate(["नमस्ते सीता जी"], LLM(Settings()))
    finally:
        register_mock(translate.PURPOSE, translate._mock)
    assert len(seen) == translate.MAX_TRIES == 2
    assert "adds numbers the original doesn't have: 900" in seen[1][-1]["content"]  # the reason went back
    assert out["नमस्ते सीता जी"]["english"] is None  # still wrong: withheld, never shown unchecked
    assert translate.translate(["Hello there"], LLM(Settings())) == {}  # English needs no English


# ---- the demo: recorded, replayed, checked, never sent ---------------------------------------------------
@pytest.fixture(scope="module")
def replay(tmp_path_factory):
    from pheri.app import create_app

    mp = pytest.MonkeyPatch()
    mp.setenv("PHERI_LLM_MODE", "replay")
    mp.setenv("PHERI_LLM_REPLAY", str(REPO_ROOT / "data" / "recorded" / "llm.jsonl"))
    mp.setenv("PHERI_LEDGER_PATH", str(tmp_path_factory.mktemp("l") / "ledger.sqlite"))
    mp.delenv("PHERI_LLM_RECORD", raising=False)
    mp.delenv("DATABASE_URL", raising=False)
    yield TestClient(create_app(LLM(Settings())))
    mp.undo()


def test_the_recorded_translations_cover_the_night_and_every_one_passes_codes_check(replay):
    e = replay.get(f"{BG}/english").json()
    assert e["recorded"] and len(e["translations"]) >= 90 and e["withheld"] == {}
    for original, english in e["translations"].items():
        assert translate.check(original, english) == [], (original, english)
        assert "Birgunj Saree House" not in english
    night = replay.get(f"{BG}/brief").json()["timeline"]
    foreign = [x["text"] for x in night if x["text"] and translate.needs_english(x["text"])]
    assert foreign and all(t in e["translations"] for t in foreign)  # every message that came in tonight
    cards = replay.get(f"{BG}/next-steps").json()
    replies = [c["decision"]["message"] for c in cards if translate.needs_english(c["decision"].get("message"))]
    assert replies and all(m in e["translations"] for m in replies)  # every reply Pheri wrote
    # the attack, too: a reader can see what it asked for
    assert any("phone numbers of all customers" in x for x in e["translations"].values())


def test_a_translation_is_never_sent(replay):
    english = set(replay.get(f"{BG}/english").json()["translations"].values())
    store = replay.app.state.pheri.stores["birgunj"]
    sent = {(a["payload"] or {}).get("message") for a in store.actions()}
    assert not english & sent


def test_offline_there_are_no_english_lines(tmp_path, monkeypatch):
    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api = TestClient(create_app(LLM(Settings())))
    e = api.get(f"{BG}/english").json()
    assert e["translations"] == {} and not e["recorded"]  # the stand-in translates nothing: no line is shown
    assert api.get("/businesses/brightdesk/english").json()["translations"] == {}  # English already
