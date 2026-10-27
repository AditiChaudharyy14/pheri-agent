"""Request shapes must match Meta's docs exactly; a wrong key silently disables a feature."""

from pydantic import BaseModel

from pheri.config import _clean_value
from pheri.llm import build_chat_request, build_responses_request, strict_schema


class Inner(BaseModel):
    quote: str


class Outer(BaseModel):
    name: str
    items: list[Inner]


def test_responses_request_uses_meta_field_names():
    req = build_responses_request("muse-spark-1.3", [{"role": "user", "content": "hi"}], 500, Outer, "low", "pheri-x")
    assert req["max_output_tokens"] == 500
    assert req["reasoning"] == {"effort": "low"}
    fmt = req["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["name"] == "Outer" and fmt["strict"] is True
    assert req["prompt_cache_key"] == "pheri-x"
    assert "response_format" not in req and "max_tokens" not in req


def test_chat_request_for_partners():
    req = build_chat_request("meta-models/muse-spark-open-1026", [], 300, None, "low", None)
    assert req["reasoning_effort"] == "low" and req["max_tokens"] == 300
    assert "reasoning" not in req


def test_strict_schema_closes_every_object():
    js = strict_schema(Outer)
    assert js["additionalProperties"] is False and set(js["required"]) == {"name", "items"}
    inner = js["$defs"]["Inner"]
    assert inner["additionalProperties"] is False and inner["required"] == ["quote"]


def test_env_values_drop_inline_comments():
    assert _clean_value("mock            # mock = no network") == "mock"
    assert _clean_value("                 # Meta Model API key") == ""
    assert _clean_value("LLM|123|abc#def") == "LLM|123|abc#def"  # '#' inside a key is kept
    assert _clean_value('"quoted # kept"') == "quoted # kept"
    assert _clean_value("130") == "130"


def test_baseten_effort_is_top_level_and_never_left_to_the_xhigh_default(tmp_path, monkeypatch):
    """docs.baseten.co reasoning page: Muse Spark Open takes top-level reasoning_effort; its default is xhigh."""
    from types import SimpleNamespace

    from pheri.config import Settings
    from pheri.llm import LLM

    monkeypatch.setenv("PHERI_LLM_MODE", "live")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    llm, sent = LLM(Settings()), []
    raw = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="ok"))])
    monkeypatch.setattr(llm, "_chat", lambda provider, req: sent.append(req) or ("ok", (10, 0, 5), raw, "c1"))
    llm.complete([{"role": "user", "content": "x"}], purpose="effort", provider="baseten", effort=None)
    llm.complete([{"role": "user", "content": "x"}], purpose="effort", provider="baseten", effort="medium")
    assert [r["reasoning_effort"] for r in sent] == ["low", "medium"]  # top level, and never the default
    assert all("reasoning" not in r and "extra_body" not in r for r in sent)


def test_reasoning_tokens_are_read_from_either_api():
    from types import SimpleNamespace

    from pheri.llm import _reasoning_usage

    responses = SimpleNamespace(usage=SimpleNamespace(output_tokens_details=SimpleNamespace(reasoning_tokens=900)))
    chat = SimpleNamespace(usage=SimpleNamespace(completion_tokens_details=None),
                           choices=[SimpleNamespace(message=SimpleNamespace(reasoning_content="think " * 100))])
    assert _reasoning_usage(responses) == (900, None)
    assert _reasoning_usage(chat) == (None, 600)
    assert _reasoning_usage(None) == (None, None)


def test_baseten_uses_metas_recommended_sampling(tmp_path, monkeypatch):
    """dev.meta.ai/docs/muse-spark-open/settings: temperature 1.0, top_p 1.0, sent explicitly."""
    from types import SimpleNamespace

    from pheri.config import Settings
    from pheri.llm import LLM

    monkeypatch.setenv("PHERI_LLM_MODE", "live")
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    llm, sent = LLM(Settings()), []
    raw = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="ok"))])
    monkeypatch.setattr(llm, "_chat", lambda provider, req: sent.append(req) or ("ok", (10, 0, 5), raw, "c1"))
    llm.complete([{"role": "user", "content": "x"}], purpose="sampling", provider="baseten")
    assert sent[0]["temperature"] == 1.0 and sent[0]["top_p"] == 1.0
    req = build_chat_request("m", [], 10, None, None, None)
    assert "temperature" not in req and "top_p" not in req  # other partners: only what is asked for
