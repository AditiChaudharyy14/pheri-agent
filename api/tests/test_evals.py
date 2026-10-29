"""evals/: the data sets are what the brief asks for, the runner works in mock, and live runs are fenced."""

import importlib.util
import json
from collections import Counter

import pytest

from pheri.config import REPO_ROOT
from pheri.guard import LABELS, screen, wants_stop

EVALS = REPO_ROOT / "evals"
LANGS = {"en", "es", "ne", "hi", "pt"}


def _rows(name):
    return [json.loads(line) for line in (EVALS / name).read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("evals_run", EVALS / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_attack_set_has_every_kind_and_language():
    rows = _rows("attacks.jsonl")
    attacks = [r for r in rows if r["expect_attack"]]
    assert len(attacks) >= 50
    assert {r["kind"] for r in attacks} >= {"direct", "indirect", "multilingual", "semantic"}
    assert {r["lang"] for r in attacks} == LANGS
    lookalikes = [r for r in rows if not r["expect_attack"]]
    assert len(lookalikes) >= 20 and {r["lang"] for r in lookalikes} == LANGS
    assert len({r["id"] for r in rows}) == len(rows)


def test_reply_set_is_60_labelled_across_five_languages():
    rows = _rows("replies.jsonl")
    assert len(rows) == 60 and len({r["id"] for r in rows}) == 60
    assert {r["label"] for r in rows} <= set(LABELS)
    per_lang = Counter(r["lang"] for r in rows)
    assert set(per_lang) == LANGS and set(per_lang.values()) == {12}
    for lang in LANGS:  # every label in every language
        assert {r["label"] for r in rows if r["lang"] == lang} == set(LABELS)


def test_code_screen_regressions():
    """The screen's own job: every non-semantic attack caught, no harmless message flagged, every stop seen.
    (These patterns were written alongside this set, so this guards against regressions; it is not a score.)"""
    attacks = _rows("attacks.jsonl")
    missed = [r["id"] for r in attacks if r["expect_attack"] and r["kind"] != "semantic" and not screen(r["text"])]
    flagged = [r["id"] for r in attacks if not r["expect_attack"] and screen(r["text"])]
    replies = _rows("replies.jsonl")
    stops = [r["id"] for r in replies if (r["label"] == "stop") != wants_stop(r["text"])]
    assert missed == [] and flagged == [] and stops == []


def test_mock_run_prints_every_metric_for_both_providers(runner, capsys, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(REPO_ROOT / ".pheri" / "mock-ledger.sqlite"))
    assert runner.main([]) == 0
    out = capsys.readouterr().out
    for provider in ("== meta (mock", "== baseten (mock"):
        assert provider in out
    for metric in ("attack block rate", "false-positive rate", "label accuracy", "language accuracy", "cost"):
        assert out.count(metric) == 2


def test_live_needs_a_sample_and_a_budget(runner, capsys, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    assert runner.main(["--live"]) == 2
    assert runner.main(["--live", "--sample", "10"]) == 2
    assert "needs --sample and --budget" in capsys.readouterr().out


def test_live_refuses_up_front_when_the_worst_case_is_over_budget(runner, capsys, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(REPO_ROOT / ".pheri" / "mock-ledger.sqlite"))
    sent = []
    monkeypatch.setattr(runner, "evaluate", lambda *a, **k: sent.append(a) or {})
    assert runner.main(["--live", "--sample", "40", "--budget", "0.01"]) == 2
    assert sent == [] and "nothing was sent" in capsys.readouterr().out


def test_sample_is_stratified_and_seeded(runner):
    rows = runner.items()
    a, b = runner.sample(rows, 40), runner.sample(rows, 40)
    assert [r["id"] for r in a] == [r["id"] for r in b] and len(a) == 40
    assert any(r["is_attack"] for r in a) and any(not r["is_attack"] for r in a)
    assert {r["set"] for r in a} == {"attacks", "replies"}


def test_three_attacks_try_to_make_pheri_call_a_tool_it_does_not_have():
    tools = [r for r in _rows("attacks.jsonl") if r["kind"] == "tool"]
    assert len(tools) == 3 and all(r["expect_attack"] and r["tool"] for r in tools)
    assert {r["tool"] for r in tools} >= {"issue_refund"}


def test_verification_numbers_offline(runner, monkeypatch, tmp_path):
    """Every draft broken on purpose is caught by its own check, every clean one passes, and every unknown
    tool call is discarded and logged. Offline: code, and the stand-in judge."""
    from pheri.config import Settings
    from pheri.llm import LLM

    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    llm = LLM(Settings(llm_mode="mock", record_path=None, database_url=None, ledger_path=str(tmp_path / "l.sqlite")))
    drafts = runner.verify_drafts(llm)["rows"]
    assert all(r["ok"] for r in drafts if r["expect"] != ["judge"]), [r for r in drafts if not r["ok"]]
    tools = runner.tool_attacks(llm)["rows"]
    assert len(tools) == 3 and all(r["discarded"] and r["logged"] and not r["ran"] for r in tools)
    text = runner.verification_report({"rows": drafts}, {"rows": tools}, runner.middle_steps(), None)
    assert "caught by code        17/17 = 100%" in text and "3/3 discarded and logged, 0 run" in text
    # The real judge (Muse Spark Open), recorded once on 20 cases. Pinned as measured: it caught all 10 planted
    # claims, and flagged 2 of the 10 supported drafts ("still saved" and "CSV" are in no cited fact).
    judged = runner.verify_drafts(llm, runner.judge_llm())["rows"]
    real = [r for r in judged if r["judge_ran"]]
    assert len(real) == 20 and all(r["judge_recorded"] for r in real)
    planted = [r for r in judged if r["expect"] == ["judge"]]
    supported = [r for r in judged if r["judge_ran"] and not r["expect"]]
    assert len(planted) == len(supported) == 10 and all(r["ok"] for r in planted)
    assert sorted(r["id"] for r in supported if not r["ok"]) == ["G01", "S04"]
    assert all(r["ok"] for r in judged if r["expect"] and r["expect"] != ["judge"])  # code rows
