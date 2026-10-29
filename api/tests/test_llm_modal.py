"""Glimmer on Modal is billed by GPU time, not tokens: the ledger reserves the longest a request may run plus
the idle tail, settles on wall-clock GPU-seconds, and stops at the $25 Modal cap. No network: `_chat` is faked."""

import pytest

from pheri.config import Settings
from pheri.ledger import SpendCapExceeded
from pheri.llm import LLM
from pheri.pricing import MODAL_GPU_USD_PER_SECOND, gpu_usd

MSG = [{"role": "user", "content": "label this reply"}]


def _llm(monkeypatch, tmp_path, **env) -> LLM:
    monkeypatch.setenv("PHERI_LLM_MODE", "live")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.setenv("MODAL_BASE_URL", "https://example.modal.run/v1")
    monkeypatch.setenv("MODAL_PROXY_TOKEN", "test-token")
    monkeypatch.delenv("PHERI_MODAL_CAP_USD", raising=False)
    monkeypatch.delenv("PHERI_LLM_RECORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    llm = LLM(Settings())
    monkeypatch.setattr(llm, "_chat", lambda provider, req: ("ok", (500, 0, 40), None, "chat_1"))
    return llm


def _clock(monkeypatch, *times):
    """time.monotonic() as llm.py sees it: each call takes the next value."""
    it = iter(times)
    monkeypatch.setattr("pheri.llm.time.monotonic", lambda: next(it))


def test_the_cap_is_25_dollars_by_default(monkeypatch, tmp_path):
    llm = _llm(monkeypatch, tmp_path)
    assert llm.ledger.totals("modal").cap_usd == 25.0


def test_settles_on_gpu_seconds_and_charges_the_idle_tail_once_per_burst(monkeypatch, tmp_path):
    llm = _llm(monkeypatch, tmp_path, PHERI_MODAL_GPU="L40S", PHERI_MODAL_SCALEDOWN_S="120")
    rate = MODAL_GPU_USD_PER_SECOND["L40S"]
    # call 1: 100 s -> 140 s (a cold start); call 2 right after: 150 s -> 152 s (same burst)
    _clock(monkeypatch, 100.0, 140.0, 140.0, 150.0, 152.0, 152.0)
    first = llm.complete(MSG, purpose="guard", provider="modal")
    second = llm.complete(MSG, purpose="guard", provider="modal")
    assert first.cost_usd == pytest.approx((40 + 120) * rate)  # wall clock + the tail after the burst
    assert second.cost_usd == pytest.approx(2 * rate)  # same burst: no second tail
    assert llm.ledger.gpu_seconds("modal") == pytest.approx(162)
    assert llm.ledger.totals("modal").settled_usd == pytest.approx(162 * rate)


def test_a_call_after_the_container_scaled_down_starts_a_new_burst(monkeypatch, tmp_path):
    llm = _llm(monkeypatch, tmp_path, PHERI_MODAL_GPU="L40S", PHERI_MODAL_SCALEDOWN_S="120")
    _clock(monkeypatch, 0.0, 10.0, 10.0, 500.0, 505.0, 505.0)
    llm.complete(MSG, purpose="guard", provider="modal")
    late = llm.complete(MSG, purpose="guard", provider="modal")
    assert late.cost_usd == pytest.approx((5 + 120) * MODAL_GPU_USD_PER_SECOND["L40S"])


def test_reserves_the_worst_case_and_refuses_past_the_cap(monkeypatch, tmp_path):
    worst = gpu_usd("A100-80GB", 300 + 120)
    llm = _llm(monkeypatch, tmp_path, PHERI_MODAL_GPU="A100-80GB", PHERI_MODAL_CAP_USD=str(worst * 0.99))
    with pytest.raises(SpendCapExceeded):
        llm.complete(MSG, purpose="guard", provider="modal")
    assert llm.ledger.totals("modal").reserved_usd == 0


def test_an_unpriced_gpu_is_refused(monkeypatch, tmp_path):
    llm = _llm(monkeypatch, tmp_path, PHERI_MODAL_GPU="B200")
    with pytest.raises(KeyError):
        llm.complete(MSG, purpose="guard", provider="modal")


def test_other_providers_still_bill_tokens(monkeypatch, tmp_path):
    llm = _llm(monkeypatch, tmp_path, BASETEN_API_KEY="k")
    r = llm.complete(MSG, purpose="guard", provider="baseten")
    assert r.cost_usd > 0 and llm.ledger.gpu_seconds("baseten") == 0
