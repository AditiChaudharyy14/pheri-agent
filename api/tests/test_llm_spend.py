"""The spend guard is the most important safety net in the repo: test it hard."""

import pytest
from pydantic import BaseModel

from pheri.config import Settings
from pheri.ledger import Ledger, SpendCapExceeded
from pheri.llm import LLM, DataPolicyError, ModelOutputError, register_mock


class Hello(BaseModel):
    greeting: str


@pytest.fixture
def llm(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "mock")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    register_mock("hello", lambda messages, schema: '{"greeting": "Namaste"}')
    return LLM(Settings())


def test_mock_call_parses_schema_and_records_ledger(llm):
    r = llm.complete([{"role": "user", "content": "hi"}], purpose="hello", schema=Hello)
    assert r.parsed.greeting == "Namaste"
    t = llm.ledger.totals("meta")
    assert t.reserved_usd == 0  # settled, not left reserved
    assert t.settled_usd == 0  # mock calls cost nothing


def test_cap_refuses_before_sending(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.setenv("PHERI_META_CAP_USD", "0.0001")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    llm = LLM(Settings())
    register_mock("hello", lambda m, s: '{"greeting": "x"}')
    with pytest.raises(SpendCapExceeded):
        llm.complete([{"role": "user", "content": "hi" * 200}], purpose="hello", max_tokens=500)
    # The refused call left nothing reserved.
    assert llm.ledger.totals("meta").reserved_usd == 0


def test_offset_counts_toward_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.setenv("PHERI_META_CAP_USD", "130")
    monkeypatch.setenv("PHERI_META_SPEND_OFFSET_USD", "129.9999")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    llm = LLM(Settings())
    with pytest.raises(SpendCapExceeded):
        llm.complete([{"role": "user", "content": "hello"}], purpose="hello", max_tokens=200)


def test_per_call_limit(llm):
    huge = "x" * 2_000_000  # ~666k tokens: far above the per-call limit
    with pytest.raises(SpendCapExceeded):
        llm.complete([{"role": "user", "content": huge}], purpose="hello")


def test_real_data_blocked_by_default(llm):
    with pytest.raises(DataPolicyError):
        llm.complete([{"role": "user", "content": "hi"}], purpose="hello", data_class="real")


def test_bad_output_raises(llm):
    register_mock("bad", lambda m, s: "not json")
    with pytest.raises(ModelOutputError):
        llm.complete([{"role": "user", "content": "hi"}], purpose="bad", schema=Hello)


def test_unknown_meta_model_is_refused(llm):
    with pytest.raises(KeyError):
        llm.complete([{"role": "user", "content": "hi"}], purpose="hello", model="muse-mystery-9")


def test_ledger_settles_real_costs(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    led = Ledger(Settings())
    rid = led.reserve("meta", "muse-spark-1.3", "t", 0.01)
    assert led.totals("meta").reserved_usd == pytest.approx(0.01)
    led.settle(rid, 0.002, 100, 0, 50)
    t = led.totals("meta")
    assert t.reserved_usd == 0 and t.settled_usd == pytest.approx(0.002)


def test_parallel_reservations_never_pass_the_cap(tmp_path, monkeypatch):
    import concurrent.futures as cf

    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.setenv("PHERI_META_CAP_USD", "0.05")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    led = Ledger(Settings())

    def try_reserve(_):
        try:
            led.reserve("meta", "muse-spark-1.3", "race", 0.01)
            return True
        except SpendCapExceeded:
            return False

    with cf.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(try_reserve, range(40)))
    assert sum(results) == 5
    assert led.totals("meta").committed_usd <= 0.05 + 1e-9


def test_missing_key_reserves_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("PHERI_LLM_MODE", "live")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    llm = LLM(Settings())
    with pytest.raises(RuntimeError):
        llm.complete([{"role": "user", "content": "hi"}], purpose="hello", max_tokens=100)
    t = llm.ledger.totals("meta")
    assert t.settled_usd == 0 and t.reserved_usd == 0
