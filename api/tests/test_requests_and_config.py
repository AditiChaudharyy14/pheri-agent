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
