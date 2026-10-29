"""Feature 1, any data -> one profile. Mock mode only: no network, no spend."""

import csv
import json
from datetime import date

import pytest

from pheri import llm as llm_module
from pheri.config import Settings
from pheri.llm import LLM
from pheri.profile import (PURPOSE, SYSTEM, build_profile, build_profiles, load, load_brightdesk, norm_email,
                           parse_date, quote_in_source)
from pheri.synth import OUT

MAYA = "maya.okafor@pinecrest.example"
EMPTY = {"goals": [], "needs": [], "blockers": [], "role": None, "sentiment": None, "language": None}
NOTE = "sales_notes.txt#L41"  # Maya's kickoff call: her goal and role are only written here


@pytest.fixture
def llm(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return LLM(Settings())


@pytest.fixture(scope="module")
def brightdesk():
    return load("brightdesk")


@pytest.fixture(scope="module")
def birgunj():
    return load("birgunj")


def _write_crm(folder, rows):
    """A minimal Brightdesk CRM export: rows of (name, email, company)."""
    with (folder / "crm_export.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Customer Name", "E-mail", "Company", "Plan", "Seats", "Signed Up", "Country", "MRR (USD)",
                    "Renewal"])
        for name, email, company in rows:
            w.writerow([name, email, company, "Team", 5, "2026-10-01", "UK", 195, "2026-11-01"])


def _model_replies(monkeypatch, reply):
    """Swap the mock model for one call shape; `reply` is a dict or a function of the messages."""
    fn = reply if callable(reply) else (lambda messages: reply)
    monkeypatch.setitem(llm_module._mock_responders, PURPOSE,
                        lambda messages, schema: json.dumps(fn(messages), ensure_ascii=False))


# ---- the hero ---------------------------------------------------------------------
def test_maya_is_stuck_on_csv_exports_and_12_days_quiet(brightdesk, llm):
    p = build_profile(brightdesk, MAYA, llm)

    assert p.facts["days_quiet"] == 12
    assert p.facts["failed_exports"] == 5
    assert p.facts["open_tickets"] == 2
    assert p.facts["days_since_signup"] == 22
    assert len(p.provenance["facts"]["failed_exports"]) == 5

    csv_blockers = [b for b in p.insights["blockers"] if "csv" in (b["label"] + b["quote"]).lower()]
    assert csv_blockers, p.insights["blockers"]
    assert {b["source_id"] for b in csv_blockers} == {"T0999"}
    assert p.insights["sentiment"]["label"] == "negative"
    assert p.insights["sentiment"]["source_id"] in {"T0999", "T1001"}  # her own tickets, not the sales note
    assert p.insights["language"]["code"] == "en"
    assert p.provenance["dropped"] == []
    assert all(g["source_id"] == NOTE for g in p.insights["goals"])  # never a ticket subject line
    # The sales note names her without an email, still lands on her profile, and gives her goal and role.
    assert NOTE in p.provenance["sources"]
    assert any("weekly client reports" in g["quote"] and g["source_id"] == NOTE for g in p.insights["goals"])
    assert p.insights["role"]["label"] == "decision maker" and p.insights["role"]["source_id"] == NOTE


def test_facts_come_from_code_not_the_model(brightdesk, llm, monkeypatch):
    _model_replies(monkeypatch, EMPTY)
    p = build_profile(brightdesk, MAYA, llm)
    assert p.insights == EMPTY
    assert (p.facts["days_quiet"], p.facts["failed_exports"], p.facts["open_tickets"]) == (12, 5, 2)


# ---- identity -----------------------------------------------------------------------
def test_emails_and_dates_are_normalised():
    assert norm_email("  Maya.Okafor@Pinecrest.Example ") == MAYA
    assert norm_email("MAYA.OKAFOR@PINECREST.EXAMPLE") == MAYA
    assert parse_date("08/10/2026") == date(2026, 10, 8)  # day-first, as the CRM exports it
    assert parse_date("2026-10-08") == date(2026, 10, 8)


def test_brightdesk_resolves_every_record(brightdesk):
    truth = json.loads((OUT / "brightdesk" / "_truth.json").read_text(encoding="utf-8"))["stages"]
    assert set(brightdesk.customers) == set(truth)
    assert len(brightdesk.duplicates) == 8  # the CRM's duplicate rows merged, not double-counted
    assert brightdesk.unresolved == []
    assert "  Maya.Okafor@Pinecrest.Example " in brightdesk.customers[MAYA].aliases


def test_birgunj_resolves_every_record(birgunj):
    truth = json.loads((OUT / "birgunj" / "_truth.json").read_text(encoding="utf-8"))["stages"]
    assert len(truth) == 300
    assert set(birgunj.customers) == set(truth)
    assert birgunj.ambiguous == set()
    assert birgunj.unresolved == []


def test_shared_phone_with_different_names_is_set_aside_not_merged(tmp_path):
    """One number written two ways, two different names: never merged, never guessed."""
    (tmp_path / "customers.csv").write_text(
        "id,name,phone,instagram,town,country,type,joined,pronouns\n"
        "bsg_0001,Sita Rai,+9779812345678,,Birgunj,NP,retail,2026-01-01,\n"
        "bsg_0002,Sita Lee, 981-234-5678 ,,Birgunj,NP,retail,2026-02-01,\n", encoding="utf-8")
    (tmp_path / "orders.csv").write_text(
        "order_no,phone,date,items,total_npr,payment,status,promised_by,delivered_on,town\n"
        "BSG-1,9812345678,2026-03-01,Cotton saree,1500,COD,delivered,2026-03-04,2026-03-04,Birgunj\n",
        encoding="utf-8")
    ds = load("birgunj", tmp_path)
    assert ds.customers == {} and ds.ambiguous == {"+9779812345678"}
    assert {u["ref"] for u in ds.unresolved} == {"customers.csv#L2", "customers.csv#L3", "orders.csv#L2"}


def test_phone_numbers_are_one_spelling_per_number():
    from pheri.profile import norm_phone

    nepali = ("+9779812345678", "9812345678", "+977-9812345678", "00977 981 2345678")
    assert {norm_phone(x) for x in nepali} == {"+9779812345678"}
    assert {norm_phone(x) for x in ("+919876543210", "+91-9876543210", "0091 987 6543210")} == {"+919876543210"}
    assert norm_phone("") == "" and norm_phone(None) == ""


def test_sales_notes_match_names_or_stay_unresolved(tmp_path):
    rows = [("Maya Okafor", "maya@pinecrest.example", "Pinecrest Design Co."),
            ("Ana Lima", "ana@harbor.example", "Harbor Labs"),
            ("Ana Lima", "ana.lima@harbor.example", "Harbor Media"),
            ("Ben Ode", "ben@kestrel.example", "Kestrel Labs")]
    _write_crm(tmp_path, rows)
    (tmp_path / "sales_notes.txt").write_text("\n".join([
        "2026-10-10 - Kickoff call with Maya Okafor (Pinecrest). Asked about CSV export.",
        "2026-10-11 - Call with Maya Okafor (Harbor). Wants SSO.",
        "2026-10-12 - Call with Ana Lima (Harbor). Wants SSO.",
        "2026-10-13 - Call with Zed Nobody (Granite). Wants SSO.",
        "2026-10-14 - Call with MAYA  OKAFOR (pinecrest). Uses reports daily.",
        "2026-10-15 - Met Dr Maya Okafor (Pinecrest) again.",
    ]) + "\n", encoding="utf-8")

    ds = load_brightdesk(tmp_path)
    maya = ds.customers["maya@pinecrest.example"]
    assert [s.id for s in maya.sources] == ["sales_notes.txt#L1", "sales_notes.txt#L5", "sales_notes.txt#L6"]
    reasons = {u["ref"]: u["reason"] for u in ds.unresolved}
    assert set(reasons) == {"sales_notes.txt#L2", "sales_notes.txt#L3", "sales_notes.txt#L4"}
    assert "not at" in reasons["sales_notes.txt#L2"]
    assert "2 customers named" in reasons["sales_notes.txt#L3"]
    assert "no customer named" in reasons["sales_notes.txt#L4"]
    assert ds.customers["ben@kestrel.example"].sources == []


# ---- evidence ---------------------------------------------------------------------
def test_quote_check_is_exact_but_forgives_typography():
    text = "Can't connect our email inbox\nThe Gmail connector says 'permission denied' after login."
    assert quote_in_source("Can’t connect our  email inbox", text)
    assert quote_in_source("“permission denied' after login…”", text)
    assert not quote_in_source("can't connect our email inbox", text)  # case matters
    assert not quote_in_source("Can't connect our Outlook inbox", text)
    assert not quote_in_source("The", text)  # too short to prove anything
    assert quote_in_source("exportación a CSV", "La exportación a CSV falla")  # Unicode form


def test_quotes_not_really_in_the_source_are_dropped(brightdesk, llm, monkeypatch):
    _model_replies(monkeypatch, {
        "goals": [{"label": "Weekly client reports", "quote": "main goal is weekly client reports", "source_id": NOTE},
                  {"label": "Monthly board pack", "quote": "main goal is a monthly board pack", "source_id": NOTE}],
        "role": {"label": "IT admin", "quote": "Our IT team can't find where to paste", "source_id": "T1013"},
        "needs": [{"label": "Wants a discount", "quote": "Please give us 50% off", "source_id": "T0999"}],
        "blockers": [
            {"label": "CSV export", "quote": "it fails at 90%", "source_id": "T0999"},
            {"label": "Gmail", "quote": "it fails at 90%", "source_id": "T1001"},
            {"label": "SSO", "quote": "Our IT team can't find where to paste the SAML metadata.", "source_id": "T1013"},
            {"label": "Invented", "quote": "Nothing works at all", "source_id": "T4242"},
        ],
        "sentiment": {"label": "negative", "quote": "We need this for our Monday review.", "source_id": "T0999"},
        "language": {"code": "es", "quote": "Exports keep failing", "source_id": "T0999"},
    })
    p = build_profile(brightdesk, MAYA, llm)

    assert p.insights["blockers"] == [{"label": "CSV export", "quote": "it fails at 90%", "source_id": "T0999"}]
    assert p.insights["goals"] == [{"label": "Weekly client reports", "quote": "main goal is weekly client reports",
                                    "source_id": NOTE}]
    assert p.insights["role"] is None
    assert p.insights["needs"] == []
    assert p.insights["sentiment"]["label"] == "negative"
    assert p.insights["language"] is None
    reasons = {(d["kind"], d["source_id"]): d["reason"] for d in p.provenance["dropped"]}
    assert reasons == {
        ("goals", NOTE): f"quote not found in {NOTE}",
        ("role", "T1013"): "'T1013' is not one of this customer's sources",
        ("needs", "T0999"): "quote not found in T0999",
        ("blockers", "T1001"): "quote not found in T1001",  # real quote, wrong source
        ("blockers", "T1013"): "'T1013' is not one of this customer's sources",  # another customer's ticket
        ("blockers", "T4242"): "'T4242' is not one of this customer's sources",
        ("language", "T0999"): "T0999 is tagged 'en', not 'es'",
    }


def test_language_must_come_from_the_customer(brightdesk, llm, monkeypatch):
    _model_replies(monkeypatch, {**EMPTY, "language": {
        "code": "en", "quote": "Kickoff call with Maya Okafor", "source_id": "sales_notes.txt#L41"}})
    p = build_profile(brightdesk, MAYA, llm)
    assert p.insights["language"] is None
    assert p.provenance["dropped"][0]["reason"] == "sales_notes.txt#L41 was not written by the customer"


def test_customer_text_is_sent_as_data_never_as_instructions(brightdesk, llm, monkeypatch):
    seen = []
    _model_replies(monkeypatch, lambda messages: seen.append(messages) or EMPTY)
    build_profile(brightdesk, "chen.shrestha@pinecrest.example", llm)

    system, user = seen[0]
    assert system == {"role": "system", "content": SYSTEM}  # fixed: nothing from the customer
    sources = json.loads(user["content"])["sources"]
    attack = next(s for s in sources if s["id"] == "T1099")
    assert "SYSTEM OVERRIDE" in attack["text"]  # carried inside a JSON string, as data


def test_customer_with_nothing_to_read_costs_no_call(brightdesk, llm, monkeypatch):
    def must_not_run(messages):
        raise AssertionError("model called with no sources")

    _model_replies(monkeypatch, must_not_run)
    quiet = next(k for k, c in brightdesk.customers.items() if not c.sources)
    p = build_profile(brightdesk, quiet, llm)
    assert p.insights == EMPTY and p.model is None
    assert p.facts["failed_exports"] >= 0


def test_sentiment_must_come_from_the_customer_and_may_be_mixed(brightdesk, llm, monkeypatch):
    _model_replies(monkeypatch, {**EMPTY, "sentiment": {"label": "positive", "quote": "Decision maker.",
                                                         "source_id": NOTE}})
    p = build_profile(brightdesk, MAYA, llm)
    assert p.insights["sentiment"] is None
    assert p.provenance["dropped"][0]["reason"] == f"{NOTE} was not written by the customer"

    _model_replies(monkeypatch, {**EMPTY, "sentiment": {"label": "mixed", "quote": "it fails at 90%",
                                                         "source_id": "T0999"}})
    assert build_profile(brightdesk, MAYA, llm).insights["sentiment"]["label"] == "mixed"


def test_goal_from_a_ticket_subject_line_is_dropped(brightdesk, llm, monkeypatch):
    _model_replies(monkeypatch, {**EMPTY, "goals": [
        {"label": "Exports", "quote": "Exports keep failing", "source_id": "T0999"},  # the subject line
        {"label": "Monday review", "quote": "We need this for our Monday review.", "source_id": "T0999"},  # the body
    ]})
    p = build_profile(brightdesk, MAYA, llm)
    assert [g["quote"] for g in p.insights["goals"]] == ["We need this for our Monday review."]
    assert p.provenance["dropped"][0]["reason"] == "goal quoted from the subject line of T0999"


def test_mock_mood_ignores_staff_notes_and_can_be_mixed(tmp_path, llm):
    _write_crm(tmp_path, [("Ana Lima", "ana@harbor.example", "Harbor Labs"),
                          ("Ben Ode", "ben@kestrel.example", "Kestrel Labs")])
    (tmp_path / "tickets.json").write_text(json.dumps([
        {"id": "T1", "from": "ana@harbor.example", "subject": "Goal: exports", "lang": "en", "status": "open",
         "created_at": "2026-10-20T10:00:00Z", "body": "Exports fail every time. Otherwise everything works great!"},
    ]), encoding="utf-8")
    (tmp_path / "sales_notes.txt").write_text(
        "2026-10-10 - Call with Ana Lima (Harbor). Happy with inbox speed.\n"
        "2026-10-11 - Call with Ben Ode (Kestrel). Happy with inbox speed.\n", encoding="utf-8")
    ds = load_brightdesk(tmp_path)

    ana = build_profile(ds, "ana@harbor.example", llm)
    assert ana.insights["sentiment"] == {"label": "mixed", "quote": "Exports fail every time.", "source_id": "T1"}
    assert ana.insights["goals"] == []  # "Goal: exports" is only a subject line
    ben = build_profile(ds, "ben@kestrel.example", llm)
    assert ben.insights["sentiment"] is None  # only a staff note says he is happy


def test_staff_praise_does_not_hide_a_customer_complaint(brightdesk, llm):
    # Noah's ticket says Gmail is broken; only the sales note says "Happy with inbox speed."
    p = build_profile(brightdesk, "noah.karimi@amberlane.example", llm)
    assert p.insights["sentiment"]["label"] == "negative" and p.insights["sentiment"]["source_id"] == "T1024"


# ---- Birgunj Saree Ghar --------------------------------------------------------------------
def test_birgunj_profile_counts_orders_across_spellings(birgunj, llm):
    """The order book writes the same number several ways; Instagram messages come from a handle, not a number."""
    from pheri.profile import norm_phone

    with (OUT / "birgunj" / "orders.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    spellings: dict[str, set] = {}
    for r in rows:
        spellings.setdefault(norm_phone(r["phone"]), set()).add(r["phone"])
    key = next(k for k, v in sorted(spellings.items()) if len(v) >= 2)
    raw = [r for r in rows if norm_phone(r["phone"]) == key]
    p = build_profile(birgunj, key, llm)
    assert p.facts["orders"] == len(raw)
    paid = [r for r in raw if r["status"] not in ("cod_refused", "returned")]
    assert p.facts["total_spend_npr"] == round(sum(float(r["total_npr"]) for r in paid))
    assert spellings[key] <= set(p.provenance["identity"]["aliases"])
    json.dumps(p.as_dict())  # profiles are plain JSON, ready for the profiles table


def test_instagram_messages_reach_the_customer_behind_the_handle(birgunj):
    messages = json.loads((OUT / "birgunj" / "messages.json").read_text(encoding="utf-8"))
    from_ig = [m for m in messages if m["from"].startswith("@")]
    assert from_ig
    for m in from_ig:
        owner = next(c for c in birgunj.customers.values() if any(s.id == m["id"] for s in c.sources))
        assert owner.attrs["instagram"] == m["from"].lower()


def test_every_birgunj_customer_gets_a_profile(birgunj, llm):
    profiles = build_profiles(birgunj, llm, limit=len(birgunj.customers))
    assert len(profiles) == 300
    assert {p.customer_key for p in profiles} == set(birgunj.customers)
    assert all(p.provenance["dropped"] == [] for p in profiles)  # the mock only quotes real text


def test_small_sample_by_default(birgunj, llm):
    profiles = build_profiles(birgunj, llm)
    assert len(profiles) == 20
    assert llm.ledger.totals("meta").settled_usd == 0  # mock mode spends nothing


def test_pronouns_only_when_the_customer_gave_them(brightdesk, birgunj):
    """The CRM column is blank unless the customer told us: then Pheri uses the name, never a guess."""
    given = {k: c.pronouns for ds in (brightdesk, birgunj) for k, c in ds.customers.items() if c.pronouns}
    assert given == {"maya.okafor@pinecrest.example": "she/her"}
