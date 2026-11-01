"""Final polish from a judge's walkthrough of the live site: opaque customer URLs, the Proof page's safety numbers
read from the saved evals, Birgunj's real Muse Wonder report, and one set of outcome words on every page."""

import json
import re

import pytest
from fastapi.testclient import TestClient

from pheri.config import REPO_ROOT, Settings
from pheri.llm import LLM
from pheri.words import internal_ids

BG = "/businesses/birgunj"
WEB = REPO_ROOT / "web"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return TestClient(create_app(LLM(Settings())))


@pytest.fixture
def replay(tmp_path, monkeypatch):
    from pheri.app import create_app

    monkeypatch.setenv("PHERI_LLM_MODE", "replay")
    monkeypatch.setenv("PHERI_LLM_REPLAY", str(REPO_ROOT / "data" / "recorded" / "llm.jsonl"))
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("PHERI_LLM_RECORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return TestClient(create_app(LLM(Settings())))


def _customers(x):
    """Every customer object anywhere in a response."""
    if isinstance(x, dict):
        if "key" in x and "name" in x and "ref" in x:
            yield x
        for v in x.values():
            yield from _customers(v)
    elif isinstance(x, list):
        for v in x:
            yield from _customers(v)


def test_customer_urls_are_opaque_ids_never_phone_numbers(client):
    brief = client.get(f"{BG}/brief").json()
    replies = client.get(f"{BG}/replies").json()
    seen = list(_customers(brief)) + list(_customers(replies)) + list(_customers(client.get(f"{BG}/slop").json()))
    assert len(seen) > 20
    for cu in seen:
        assert re.fullmatch(r"c\d{3}", cu["ref"]), cu  # no phone number, no email, nothing to read off
        assert cu["key"].startswith("+")  # Birgunj's customers are keyed by phone: exactly what the URL must not show
    one = seen[0]
    by_ref = client.get(f"{BG}/customers/{one['ref']}").json()
    assert by_ref["key"] == one["key"] and by_ref["ref"] == one["ref"] and by_ref["name"] == one["name"]
    assert client.get(f"{BG}/customers/{one['ref']}/trace").status_code == 200
    rows = client.get(f"{BG}/customers", params={"limit": 500}).json()["items"]
    assert len({r["ref"] for r in rows}) == len(rows) == 300  # one each, stable (file order)
    assert client.get(f"{BG}/customers/c999").status_code == 404


def test_the_web_links_customers_by_ref_only():
    sources = [p for d in ("app", "components") for p in (WEB / d).rglob("*.tsx")]
    for p in sources:
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"customers/\$\{encodeURIComponent\(\w+\.(customer\.)?key\)", text), p
        assert "customerKey={step.customer.key}" not in text and "customerKey={s.customer.key}" not in text, p


def test_proof_safety_numbers_are_the_saved_eval_results(client):
    e = client.get("/evals").json()
    saved = json.loads((REPO_ROOT / "evals" / "scale" / "results.json").read_text(encoding="utf-8"))
    for p in ("meta", "baseten"):
        for lang in ("all", "ne", "ne-Latn", "hi", "bho", "en"):
            assert e["guard"][p][lang]["attacks_stopped"] == saved["guard"][p][lang]["attacks_stopped"]
            assert e["guard"][p][lang]["label"] == saved["guard"][p][lang]["label"]
    assert (e["guard"]["meta"]["bho"]["attacks_stopped"]["k"], e["guard"]["baseten"]["bho"]["attacks_stopped"]["k"]) == (24, 37)
    assert (e["judge"]["planted_caught"]["k"], e["judge"]["planted_caught"]["n"]) == (25, 25)
    # Defence in depth (evals/pipeline.py): every attack through the whole pipeline, code screen off.
    assert e["pipeline"]["baseten"] == {"run": 140, "of": 140, "past_guard": 6, "sent": 0, "harmful": 0}
    assert e["pipeline"]["meta"] == {"run": 74, "of": 140, "past_guard": 7, "sent": 3, "harmful": 0}


def test_birgunj_proof_is_written_by_muse_wonder_recorded_and_in_plain_words(replay):
    """Recorded live on 1 Nov (one call, passed every check on attempt 1, $0.056). The page no longer says 'offline
    stand-in'; the model named actions and stages by their ids, which the API turns into words for the owner."""
    rep = replay.get(f"{BG}/learned").json()
    assert rep["source"] == "recorded" and rep["model"] == "muse-wonder-1.0"
    assert [(a["attempt"], a["passed"]) for a in rep["attempts"]] == [(1, True)] and rep["rejected"] == []
    assert len(rep["findings"]) == 7  # every stage, wholesale included
    assert "+14.0" in rep["headline"]
    owner_text = [rep["headline"], *(f["text"] for f in rep["findings"]), *(c["text"] for c in rep["caveats"])]
    assert [t for t in owner_text if internal_ids(t)] == []
    twin = replay.get(f"{BG}/twin").json()
    wholesale = next(s for s in twin["stages"] if s["stage"] == "wholesale")
    assert (wholesale["treated"]["n"], wholesale["holdout"]["n"]) == (442, 105)  # shown on the page, with its range
    # the headline is the stages combined: their lifts, weighted by customers, come back to it
    weighted = sum(s["lift_pp"] * s["treated"]["n"] for s in twin["stages"]) / twin["overall"]["treated"]["n"]
    assert abs(weighted - twin["overall"]["lift_pp"]) < 0.2


def test_one_set_of_outcome_words_on_every_page():
    labels = (WEB / "lib" / "labels.ts").read_text(encoding="utf-8")
    for w in ("Goes out at 08:00", "Waits for you", "Blocked by your rule", "Attack stopped"):
        assert f'"{w}"' in labels
    owner_pages = [p for d in ("app", "components") for p in (WEB / d).rglob("*.tsx")]
    retired = ("Ready at 8:00", "Waiting for you", "Your rules stopped", "Blocked by a rule", "Stopped: waiting",
               "Blocked by your new rule", "exfiltrat")
    for p in owner_pages:
        text = p.read_text(encoding="utf-8")
        assert [w for w in retired if w in text] == [], p
