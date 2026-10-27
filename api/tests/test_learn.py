"""What Pheri learned: Muse Wonder (mocked) writes from the results JSON; code checks every number and verdict."""

import json

import pytest

from pheri import learn
from pheri import llm as llm_module
from pheri.config import Settings
from pheri.llm import LLM
from pheri.twin import run


@pytest.fixture
def llm(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return LLM(Settings())


@pytest.fixture(scope="module")
def results():
    return run("brightdesk", n=200)  # stuck and at-risk work, overall and the rest unclear


def _model(monkeypatch, report: dict):
    monkeypatch.setitem(llm_module._mock_responders, learn.PURPOSE, lambda m, s: json.dumps(report))


def _finding(stage, verdict, text, ids):
    return {"stage": stage, "verdict": verdict, "text": text, "fact_ids": ids}


def test_the_catalogue_is_the_results_and_never_the_hidden_truth(results):
    facts = learn.catalogue(results)
    assert facts["stuck.lift_pp"] == "+20.7" and facts["stuck.verdict"] == "works"
    assert facts["overall.verdict"] == "unclear" and facts["customers"] == "200"
    assert not any("truth" in k or "baseline" in k for k in facts)


def test_wonder_gets_only_the_catalogue_with_strict_ids(results, llm, monkeypatch):
    calls = []
    real = llm.complete
    monkeypatch.setattr(llm, "complete", lambda m, **kw: calls.append((m, kw)) or real(m, **kw))
    learn.write_report(results, llm)
    messages, kw = calls[0]
    assert kw["model"] == "muse-wonder-1.0" and kw["purpose"] == "learn_report"
    sent = json.loads(messages[-1]["content"])
    assert set(sent) == {"business", "facts"} and "twin_truth" not in messages[-1]["content"]
    schema = kw["schema"].model_json_schema()
    ids = schema["$defs"]["Finding"]["properties"]["fact_ids"]["items"]["enum"]
    assert set(ids) == set(learn.catalogue(results))
    assert set(schema["$defs"]["Finding"]["properties"]["stage"]["enum"]) == {s["stage"] for s in results["stages"]}


def test_the_mock_report_passes_every_check(results, llm):
    rep = learn.write_report(results, llm)
    assert rep.rejected == []
    assert {f["stage"] for f in rep.findings} == {s["stage"] for s in results["stages"] if s["lift_pp"] is not None}
    assert "not clear yet" in rep.headline  # overall is unclear at 200 customers
    assert rep.markdown.startswith("## What Pheri learned") and "**stuck** (works)" in rep.markdown


def test_a_number_not_in_the_cited_facts_is_rejected(results, llm, monkeypatch):
    _model(monkeypatch, {
        "headline": "Pheri lifted responses by 12 points.", "headline_fact_ids": ["overall.lift_pp"],
        "findings": [_finding("stuck", "works", "Up +20.7 points, best send_help.", ["stuck.lift_pp"]),
                     _finding("at_risk_renewal", "works", "Up 45 points.", ["at_risk_renewal.lift_pp"])],
        "caveats": [{"text": "Only 150 customers.", "fact_ids": ["customers"]}]})
    rep = learn.write_report(results, llm)
    assert [f["stage"] for f in rep.findings] == ["stuck"]
    reasons = {x["part"]: x["problems"] for x in rep.rejected}
    assert "45 is not in the facts" in reasons["finding"][0] and "150 is not in the facts" in reasons["caveat"][0]
    assert "12 is not in the facts" in reasons["headline"][0]
    assert rep.headline.startswith("Across 200 customers")  # code's own headline instead


def test_rounding_is_allowed_inventing_is_not(results, llm, monkeypatch):
    facts = learn.catalogue(results)
    assert learn.check_item("About 21 points.", ["stuck.lift_pp"], facts) == []  # +20.7 rounded
    assert learn.check_item("About 21 points.", [], facts)  # same number, nothing cited: rejected
    assert learn.check_item("At the 95% level.", [], facts) == []  # the interval's level is not a result


def test_the_verdict_must_be_the_one_code_computed(results, llm, monkeypatch):
    _model(monkeypatch, {
        "headline": "Mixed results so far.", "headline_fact_ids": [],
        "findings": [_finding("quiet", "works", "Up +10.0 points.", ["quiet.lift_pp"]),  # interval crosses zero
                     _finding("healthy", "unclear", "Check-ins clearly hurt here: -6.9 points.", ["healthy.lift_pp"]),
                     _finding("stuck", "works", "Up +20.7 points.", ["stuck.lift_pp"]),
                     _finding("stuck", "works", "Again +20.7 points.", ["stuck.lift_pp"])],
        "caveats": []})
    rep = learn.write_report(results, llm)
    assert [f["stage"] for f in rep.findings] == ["stuck"]
    problems = [p for x in rep.rejected for p in x["problems"]]
    assert any("verdict 'works', but the interval says 'unclear'" in p for p in problems)
    assert any("claims a result for an unclear stage" in p for p in problems)
    assert any("a second finding" in p for p in problems)


def test_an_unclear_overall_result_may_not_be_claimed_in_the_headline(results, llm, monkeypatch):
    _model(monkeypatch, {"headline": "Pheri clearly works: +6.9 points.", "headline_fact_ids": ["overall.lift_pp"],
                         "findings": [], "caveats": []})
    rep = learn.write_report(results, llm)
    assert rep.rejected[0]["part"] == "headline" and "overall verdict is unclear" in rep.rejected[0]["problems"][0]


def test_an_unusable_answer_leaves_only_what_code_can_say(results, llm, monkeypatch):
    monkeypatch.setitem(llm_module._mock_responders, learn.PURPOSE, lambda m, s: "not json")
    rep = learn.write_report(results, llm)
    assert rep.findings == [] and rep.rejected[0]["part"] == "report"
    assert rep.headline.startswith("Across 200 customers")


def test_mock_only_from_the_command_line(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    from pheri.config import REPO_ROOT

    path = tmp_path / "r.json"
    path.write_text(json.dumps(run("kettle", n=200)), encoding="utf-8")
    env = {**os.environ, "PHERI_LLM_MODE": "live", "PHERI_LEDGER_PATH": str(tmp_path / "l.sqlite")}
    done = subprocess.run([sys.executable, "-m", "pheri.learn", str(path)], capture_output=True, text=True,
                          encoding="utf-8", cwd=REPO_ROOT / "api", env=env)
    assert done.returncode != 0 and "Mock only" in (done.stderr + done.stdout)  # Wonder is not called yet
