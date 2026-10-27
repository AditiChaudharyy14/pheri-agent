"""The one door to every model. Nothing in Pheri calls a model any other way.

Each call:
  1. checks the data policy (only synthetic data goes to models unless explicitly allowed),
  2. estimates the worst-case cost and reserves it in the ledger (refused past the cap),
  3. calls the provider, retrying only 429/500/502/503 (max 3 tries, honouring Retry-After),
  4. settles the reservation with the real cost from the usage report.

Protocols (checked against https://dev.meta.ai/docs on 27 Oct 2026):
  meta    -> Meta Model API, **Responses API** (Meta's recommended default for agents):
             structured output in `text.format`, effort in `reasoning.effort`,
             usage in `input_tokens` / `input_tokens_details.cached_tokens` / `output_tokens`.
  baseten -> Muse Spark Open (open weights), Chat Completions, top-level `reasoning_effort`.
  modal   -> Muse Glimmer (open weights), Chat Completions.
Reasoning tokens are billed as output, so `max_tokens` bounds reasoning + answer together.
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from .config import Settings, get_settings
from .ledger import Ledger, SpendCapExceeded  # noqa: F401  (re-exported)
from .pricing import cost_usd, price_for

MAX_OUTPUT_TOKENS = 8192
DEFAULT_OUTPUT_TOKENS = 1200
MAX_ATTEMPTS = 3
RETRYABLE_STATUS = {429, 500, 502, 503}
EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}


class DataPolicyError(RuntimeError):
    """Raised when non-synthetic data would be sent somewhere it must not go."""


class ModelOutputError(RuntimeError):
    """Raised when a model's output does not match the schema we asked for."""


@dataclass
class LLMResult:
    text: str
    parsed: Any
    provider: str
    model: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
    response_id: str | None = None
    raw: Any = field(default=None, repr=False)


# Mock responders let tests and offline demos run with zero network and zero spend.
MockFn = Callable[[list[dict], dict | None], str]
_mock_responders: dict[str, MockFn] = {}


def register_mock(purpose: str, fn: MockFn) -> None:
    _mock_responders[purpose] = fn


def _estimate_input_tokens(messages: list[dict]) -> int:
    chars = 0
    for m in messages:
        content = m.get("content")
        chars += len(content) if isinstance(content, str) else len(json.dumps(content, ensure_ascii=False))
    # ~3 characters per token is pessimistic for English and fair for Devanagari; overestimating is the safe side.
    return math.ceil(chars / 3) + 16 * len(messages)


# ---- request builders (pure functions, unit-tested) ------------------------------
def build_responses_request(model, messages, max_tokens, schema, effort, cache_key) -> dict:
    req: dict[str, Any] = {"model": model, "input": messages, "max_output_tokens": max_tokens}
    if effort:
        req["reasoning"] = {"effort": effort}
    if schema is not None:
        req["text"] = {"format": {"type": "json_schema", "name": schema.__name__,
                                  "schema": strict_schema(schema), "strict": True}}
    if cache_key:
        req["prompt_cache_key"] = cache_key
    return req


def build_chat_request(model, messages, max_tokens, schema, effort, temperature) -> dict:
    req: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if effort:
        req["reasoning_effort"] = effort
    if temperature is not None:
        req["temperature"] = temperature
    if schema is not None:
        req["response_format"] = {"type": "json_schema",
                                  "json_schema": {"name": schema.__name__, "schema": strict_schema(schema), "strict": True}}
    return req


class LLM:
    def __init__(self, settings: Settings | None = None, ledger: Ledger | None = None):
        self.settings = settings or get_settings()
        self.ledger = ledger or Ledger(self.settings)
        self._clients: dict[str, Any] = {}

    # ---- providers -------------------------------------------------------
    def _client(self, provider: str):
        if provider in self._clients:
            return self._clients[provider]
        from openai import OpenAI  # imported lazily so mock mode needs no network libs

        s = self.settings
        base, key = {
            "meta": (s.meta_base_url, s.meta_api_key),
            "baseten": (s.baseten_base_url, s.baseten_api_key),
            "modal": (s.modal_base_url, s.modal_api_key),
        }[provider]
        if not base or not key:
            raise RuntimeError(f"{provider}: base URL or API key missing. Set it in .env (see .env.example).")
        # The OpenAI SDK does not read MODEL_API_KEY by itself, so we pass it explicitly.
        client = OpenAI(base_url=base, api_key=key, max_retries=0, timeout=120)
        self._clients[provider] = client
        return client

    def default_model(self, provider: str) -> str:
        return {"meta": "muse-spark-1.3", "baseten": self.settings.baseten_model,
                "modal": self.settings.modal_model}[provider]

    # ---- the call -------------------------------------------------------
    def complete(
        self,
        messages: list[dict],
        *,
        purpose: str,
        provider: str = "meta",
        model: str | None = None,
        max_tokens: int = DEFAULT_OUTPUT_TOKENS,
        schema: type[BaseModel] | None = None,
        effort: str | None = "low",
        data_class: str = "synthetic",
        allow_expensive: bool = False,
        temperature: float | None = None,
    ) -> LLMResult:
        model = model or self.default_model(provider)
        max_tokens = max(1, min(int(max_tokens), MAX_OUTPUT_TOKENS))
        if effort is not None and effort not in EFFORTS:
            raise ValueError(f"effort must be one of {sorted(EFFORTS)} (Meta rejects 'none').")
        if effort == "max" and model.endswith("-contributor"):
            raise ValueError("Contributor models do not support effort 'max'.")

        # 1. Data policy.
        if data_class != "synthetic" and not self.settings.allow_real_data:
            raise DataPolicyError(
                "Only synthetic data may be sent to models (free-credit content may be used by Meta "
                "for product improvement). Set PHERI_ALLOW_REAL_DATA=1 only with a paid, standard-mode setup."
            )
        if model.endswith("-contributor") and data_class != "synthetic":
            raise DataPolicyError("Contributor-mode models may train on content: synthetic data only.")

        # 2. Estimate and reserve the worst case (reasoning tokens bill as output, bounded by max_tokens).
        price = price_for(provider, model)
        est = cost_usd(price, _estimate_input_tokens(messages), max_tokens)
        if est > self.settings.max_call_usd and not allow_expensive:
            raise SpendCapExceeded(
                f"Single call estimated at ${est:.4f} > per-call limit ${self.settings.max_call_usd:.2f}. "
                "Shrink the prompt or pass allow_expensive=True on purpose."
            )
        rid = self.ledger.reserve(provider, model, purpose, est)

        # 3. Call.
        start = time.monotonic()
        try:
            if self.settings.llm_mode == "mock":
                text, usage, raw, resp_id = *self._mock_call(messages, purpose, schema), None, None
            elif provider == "meta":
                req = build_responses_request(model, messages, max_tokens, schema, effort, f"pheri-{purpose}")
                text, usage, raw, resp_id = self._with_retries(lambda: self._responses(req))
            else:
                req = build_chat_request(model, messages, max_tokens, schema, effort, temperature)
                text, usage, raw, resp_id = self._with_retries(lambda: self._chat(provider, req))
        except BaseException as exc:
            status = getattr(exc, "status_code", None)
            maybe_billed = (status is not None and status >= 500) or exc.__class__.__name__ in (
                "APIConnectionError", "APITimeoutError")
            if self.settings.llm_mode != "mock" and maybe_billed:
                # Timeout or server error: the provider may have billed us. Count the worst case.
                self.ledger.settle(rid, est, _estimate_input_tokens(messages), 0, max_tokens)
            else:
                # Never sent (missing key, bad config) or refused outright (4xx): nothing was billed.
                self.ledger.release(rid)
            raise
        latency = time.monotonic() - start

        # 4. Settle with the real cost.
        in_tok, cached_tok, out_tok = usage
        actual = 0.0 if self.settings.llm_mode == "mock" else cost_usd(price, in_tok, out_tok, cached_tok)
        self.ledger.settle(rid, actual, in_tok, cached_tok, out_tok)

        parsed = _parse(text, schema) if schema is not None else None
        return LLMResult(text, parsed, provider, model, in_tok, cached_tok, out_tok, actual, latency, resp_id, raw)

    # ---- transports -------------------------------------------------------
    def _responses(self, req: dict):
        resp = self._client("meta").responses.create(**req)
        u = resp.usage
        details = getattr(u, "input_tokens_details", None)
        cached = (getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
        return resp.output_text or "", (u.input_tokens or 0, cached, u.output_tokens or 0), resp, resp.id

    def _chat(self, provider: str, req: dict):
        resp = self._client(provider).chat.completions.create(**req)
        u = resp.usage
        details = getattr(u, "prompt_tokens_details", None)
        cached = (getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
        text = resp.choices[0].message.content or ""
        return text, (u.prompt_tokens or 0, cached, u.completion_tokens or 0), resp, resp.id

    @staticmethod
    def _with_retries(fn):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001
                status = getattr(exc, "status_code", None)
                network_error = status is None and exc.__class__.__name__ in ("APIConnectionError", "APITimeoutError")
                if attempt == MAX_ATTEMPTS or not (status in RETRYABLE_STATUS or network_error):
                    raise
                time.sleep(_retry_delay(exc, attempt))
        raise AssertionError("unreachable")

    def _mock_call(self, messages, purpose, schema):
        fn = _mock_responders.get(purpose)
        if fn is None:
            raise RuntimeError(f"No mock responder registered for purpose {purpose!r}.")
        text = fn(messages, schema.model_json_schema() if schema else None)
        return text, (_estimate_input_tokens(messages), 0, math.ceil(len(text) / 3))


def _retry_delay(exc: Exception, attempt: int) -> float:
    response = getattr(exc, "response", None)
    header = None
    if response is not None:
        header = response.headers.get("retry-after")
    if header:
        try:
            return min(float(header), 60.0)
        except ValueError:
            pass
    return (2 ** (attempt - 1)) + random.random()


def _parse(text: str, schema: type[BaseModel]):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned[cleaned.find("{"):]
    try:
        return schema.model_validate_json(cleaned)
    except ValidationError as exc:
        raise ModelOutputError(f"Model output did not match {schema.__name__}: {exc}") from exc


def strict_schema(schema: type[BaseModel]) -> dict:
    """JSON schema in Meta's strict subset: every object closed, every property required, no titles needed."""
    js = schema.model_json_schema()

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(js)
    return js
