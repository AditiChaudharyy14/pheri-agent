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
             Checked on https://docs.baseten.co/inference/model-apis/reasoning (27 Oct 2026): it always
             reasons; `reasoning_effort` low/medium/high/xhigh is used as sent (none/minimal run at low);
             the default is xhigh, so we always send one; there is no reasoning budget
             (`reasoning.max_tokens` is not enforced for it), so `max_tokens` is the only length control
             and it caps reasoning + answer together. Reasoning text comes back in `reasoning_content`.
  modal   -> Muse Glimmer (open weights), Chat Completions.
Reasoning tokens are billed as output, so `max_tokens` bounds reasoning + answer together.

JSON on every provider: `complete_json` asks for `json_schema` first. If a Chat Completions partner
refuses that (a 400 naming the schema or response_format), it switches that provider to JSON
instructions in the prompt + Pydantic validation, with one corrective retry, and remembers the
switch for the rest of the process. PHERI_<PROVIDER>_JSON=schema|instructions forces a mode.

Tool loops (meta only): pass `tools` (flat function shape). Two ways to carry the conversation:
  stateless=True   (what decide.py uses) resend the whole conversation every turn: the request has
                   `store: false` and asks for `reasoning.encrypted_content`, and `output_items` hands
                   back each response's items ready to append to the next input. Nothing is kept on
                   Meta's side, so no turn can fail with "referenced response not found or expired".
  previous_response_id  send only the new items; the server appends them to the stored history.
Either way the server reads the whole conversation on every turn and bills it as input again, so a
chained call is estimated against everything said so far, not only the new items. `tool_choice` is auto only: a turn may come back
as plain text instead of a tool call or JSON, so with tools a bad parse is reported, not raised.

Recorded replies: a live run with PHERI_LLM_RECORD=<file> saves every reply. PHERI_LLM_MODE=replay plays
them back offline (zero network, zero spend), so a public demo shows what the real model said while code
still does everything else: rule checks, evidence checks, the autonomy dial. A reply is found by the
conversation it answered (reasoning items left out, random ids masked); anything not recorded falls back
to the offline stand-in, and the result says which it was (`recorded`).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from .config import Settings, get_settings
from .ledger import Ledger, SpendCapExceeded  # noqa: F401  (re-exported)
from .pricing import cost_usd, price_for

MAX_OUTPUT_TOKENS = 8192
DEFAULT_OUTPUT_TOKENS = 1200
MAX_ATTEMPTS = 3
# A chained call whose earlier turns we did not see (another process): assume a long conversation.
UNKNOWN_CONTEXT_TOKENS = 16_000
RETRYABLE_STATUS = {429, 500, 502, 503}
EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}
MUSE_SPARK_OPEN_SAMPLING = {"temperature": 1.0, "top_p": 1.0}  # Meta's recommended defaults, 27 Oct 2026


class DataPolicyError(RuntimeError):
    """Raised when non-synthetic data would be sent somewhere it must not go."""


class ModelOutputError(RuntimeError):
    """Raised when a model's output does not match the schema we asked for. `.result` holds the call's
    LLMResult (tokens, cost, why it stopped) when there was one: a failed answer was still billed."""

    result = None


@dataclass
class FunctionCall:
    name: str
    arguments: str  # JSON text, exactly as the model wrote it
    call_id: str


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
    function_calls: list[FunctionCall] = field(default_factory=list)
    parse_error: str | None = None  # with tools: the reply was not the JSON we asked for
    incomplete: str | None = None  # why the provider stopped early, e.g. "max_output_tokens"
    output_items: list[dict] = field(default_factory=list)  # stateless: append these to the next input
    reasoning_tokens: int | None = None  # as the provider reported them, when it does
    reasoning_chars: int | None = None  # length of the reasoning text returned (Chat: reasoning_content)
    recorded: bool = False  # replay mode: the reply a live run recorded (cost_usd is what that run paid)


# Mock responders let tests and offline demos run with zero network and zero spend.
# A responder returns text, or {"function_calls": [{"name": ..., "arguments": {...}}]} to call tools.
# In a tool loop it receives the whole conversation so far, as the real server sees it.
MockFn = Callable[[list[dict], dict | None], "str | dict"]
_mock_responders: dict[str, MockFn] = {}


def register_mock(purpose: str, fn: MockFn) -> None:
    _mock_responders[purpose] = fn


def _estimate_input_tokens(messages: list[dict]) -> int:
    chars = 0
    for m in messages:
        content = m.get("content", m)  # tool items (function_call_output, ...) have no "content"
        chars += len(content) if isinstance(content, str) else len(json.dumps(content, ensure_ascii=False))
    # ~3 characters per token is pessimistic for English and fair for Devanagari; overestimating is the safe side.
    return math.ceil(chars / 3) + 16 * len(messages)


# ---- request builders (pure functions, unit-tested) ------------------------------
def build_responses_request(model, messages, max_tokens, schema, effort, cache_key, tools=None,
                            previous_response_id=None, stateless=False) -> dict:
    req: dict[str, Any] = {"model": model, "input": messages, "max_output_tokens": max_tokens}
    if tools:
        req["tools"] = tools
        req["tool_choice"] = "auto"  # the only value Meta supports
    if previous_response_id:
        req["previous_response_id"] = previous_response_id
    if stateless:
        # Meta keeps no copy, and returns the reasoning encrypted so the next turn can replay it.
        req["store"] = False
        req["include"] = ["reasoning.encrypted_content"]
    if effort:
        req["reasoning"] = {"effort": effort}
    if schema is not None:
        req["text"] = {"format": {"type": "json_schema", "name": schema.__name__,
                                  "schema": strict_schema(schema), "strict": True}}
    if cache_key:
        req["prompt_cache_key"] = cache_key
    return req


def build_chat_request(model, messages, max_tokens, schema, effort, temperature, top_p=None) -> dict:
    req: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if effort:
        req["reasoning_effort"] = effort
    if temperature is not None:
        req["temperature"] = temperature
    if top_p is not None:
        req["top_p"] = top_p
    if schema is not None:
        req["response_format"] = {"type": "json_schema",
                                  "json_schema": {"name": schema.__name__, "schema": strict_schema(schema), "strict": True}}
    return req


class LLM:
    def __init__(self, settings: Settings | None = None, ledger: Ledger | None = None):
        self.settings = settings or get_settings()
        self.ledger = ledger or Ledger(self.settings)
        self._clients: dict[str, Any] = {}
        self._context_tokens: dict[str, int] = {}  # response id -> tokens the next chained turn re-reads
        self._mock_threads: dict[str, list[dict]] = {}  # mock only: the conversation behind a response id
        self._json_mode: dict[str, str] = {}  # provider -> "instructions" once it refused json_schema
        self._only: frozenset[str] | None = None  # inside `only(...)`: the providers calls may go to
        self._recordings: dict[str, dict] | None = None  # replay mode: key -> recorded reply, read on first use

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

    @contextmanager
    def only(self, *providers: str):
        """Inside this block a call to any other provider is refused before anything is sent or reserved."""
        before, self._only = self._only, frozenset(providers)
        try:
            yield self
        finally:
            self._only = before

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
        top_p: float | None = None,
        tools: list[dict] | None = None,
        previous_response_id: str | None = None,
        stateless: bool = False,
    ) -> LLMResult:
        if self._only is not None and provider not in self._only:
            raise DataPolicyError(f"This business is in full private mode: a {purpose!r} call to {provider!r} was "
                                  f"refused before sending (allowed: {sorted(self._only)}).")
        model = model or self.default_model(provider)
        if provider == "baseten":
            if effort is None:
                effort = "low"  # Muse Spark Open's default on Baseten is xhigh: never leave it to the default
            # Meta's recommended sampling for Muse Spark Open (dev.meta.ai/docs/muse-spark-open/settings):
            # temperature 1.0, top_p 1.0. Sent explicitly so no partner default can change it.
            temperature = MUSE_SPARK_OPEN_SAMPLING["temperature"] if temperature is None else temperature
            top_p = MUSE_SPARK_OPEN_SAMPLING["top_p"] if top_p is None else top_p
        if (tools or previous_response_id or stateless) and provider != "meta":
            raise ValueError("Tool loops use the Responses API, which only the meta provider speaks here.")
        if stateless and previous_response_id:
            # Meta: include=["reasoning.encrypted_content"] cannot be combined with previous_response_id.
            raise ValueError("A stateless call resends the conversation; it cannot also use previous_response_id.")
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
        est_in = _estimate_input_tokens(messages) + math.ceil(len(json.dumps(tools or [])) / 3)
        if previous_response_id:
            est_in += self._context_tokens.get(previous_response_id, UNKNOWN_CONTEXT_TOKENS)
        est = cost_usd(price, est_in, max_tokens)
        if est > self.settings.max_call_usd and not allow_expensive:
            raise SpendCapExceeded(
                f"Single call estimated at ${est:.4f} > per-call limit ${self.settings.max_call_usd:.2f}. "
                "Shrink the prompt or pass allow_expensive=True on purpose."
            )
        rid = self.ledger.reserve(provider, model, purpose, est)

        # 3. Call.
        offline = self.settings.llm_mode != "live"
        # Replay mode plays recordings back; a recording run reuses what it already recorded for the same
        # conversation, so a run stopped part-way (spend cap, outage) resumes without paying twice.
        replay = (self.settings.llm_mode == "replay" or bool(self.settings.record_path)) and (stateless or not tools)
        key = recording_key(purpose, provider, model, messages, schema, tools)             if replay or self.settings.record_path else None
        rec = self._recorded(key) if replay else None
        start = time.monotonic()
        try:
            calls: list[FunctionCall] = []
            if rec is not None:
                text, usage, calls, resp_id, raw, items = _from_recording(rec)
            elif offline:
                text, usage, calls, resp_id, raw, items = self._mock_call(messages, purpose, schema, tools,
                                                                          previous_response_id, stateless)
            elif provider == "meta":
                req = build_responses_request(model, messages, max_tokens, schema, effort, f"pheri-{purpose}",
                                              tools, previous_response_id, stateless)
                text, usage, raw, resp_id, calls, items = self._with_retries(lambda: self._responses(req))
            else:
                req = build_chat_request(model, messages, max_tokens, schema, effort, temperature, top_p)
                text, usage, raw, resp_id = self._with_retries(lambda: self._chat(provider, req))
                items = []
        except BaseException as exc:
            status = getattr(exc, "status_code", None)
            maybe_billed = (status is not None and status >= 500) or exc.__class__.__name__ in (
                "APIConnectionError", "APITimeoutError")
            if not offline and maybe_billed:
                # Timeout or server error: the provider may have billed us. Count the worst case.
                self.ledger.settle(rid, est, est_in, 0, max_tokens)
            else:
                # Never sent (missing key, bad config) or refused outright (4xx): nothing was billed.
                self.ledger.release(rid)
            raise
        latency = time.monotonic() - start

        # 4. Settle with the real cost.
        in_tok, cached_tok, out_tok = usage
        actual = 0.0 if offline or rec is not None else cost_usd(price, in_tok, out_tok, cached_tok)
        self.ledger.settle(rid, actual, in_tok, cached_tok, out_tok)
        if tools and resp_id and not stateless:
            self._context_tokens.pop(previous_response_id or "", None)  # our chains are linear
            self._context_tokens[resp_id] = in_tok + out_tok

        incomplete = None
        if getattr(raw, "status", None) == "incomplete":  # Responses API
            incomplete = getattr(getattr(raw, "incomplete_details", None), "reason", None) or "unknown"
        elif getattr((getattr(raw, "choices", None) or [None])[0], "finish_reason", None) == "length":  # Chat
            incomplete = "max_output_tokens"
        reasoning_tokens, reasoning_chars = _reasoning_usage(raw)
        if rec is not None:
            reasoning_tokens, actual = rec.get("reasoning_tokens"), rec["cost_usd"]
        elif self.settings.record_path and not offline:
            self._record(key, purpose, provider, model, text, calls, items, usage, actual, incomplete,
                         reasoning_tokens)
        result = LLMResult(text, None, provider, model, in_tok, cached_tok, out_tok, actual, latency, resp_id, raw,
                           calls, None, incomplete, items, reasoning_tokens, reasoning_chars, rec is not None)
        if schema is not None and not calls:
            try:
                result.parsed = _parse(text, schema)
            except ModelOutputError as exc:
                if not tools:
                    err = (ModelOutputError(f"Answer cut off ({incomplete}) before the JSON was complete")
                           if incomplete else exc)  # say why: the limit, not the model's grasp of the schema
                    err.result = result
                    raise err from (exc if err is not exc else None)
                result.parse_error = f"cut off ({incomplete})" if incomplete else str(exc)
        return result

    # ---- JSON on any provider ----------------------------------------------
    def json_mode(self, provider: str) -> str:
        if provider == "meta":
            return "schema"
        forced = os.environ.get(f"PHERI_{provider.upper()}_JSON", "").strip().lower()
        return forced if forced in ("schema", "instructions") else self._json_mode.get(provider, "schema")

    def complete_json(self, messages: list[dict], *, schema: type[BaseModel], provider: str = "meta",
                      schema_only: bool = False, **kw) -> LLMResult:
        """A validated `schema` instance in .parsed, whatever the provider supports. Raises ModelOutputError.
        schema_only: strict json_schema or nothing; never fall back to JSON instructions."""
        if schema_only:
            return self.complete(messages, schema=schema, provider=provider, **kw)
        if self.json_mode(provider) == "schema":
            try:
                return self.complete(messages, schema=schema, provider=provider, **kw)
            except Exception as exc:  # noqa: BLE001
                if provider == "meta" or not _schema_refused(exc):
                    raise
                self._json_mode[provider] = "instructions"  # that request was refused, not billed
        asked = _with_json_instructions(messages, schema)
        r = self.complete(asked, provider=provider, **kw)
        try:
            r.parsed = _parse(_json_object(r.text), schema)
        except ModelOutputError as err:
            # One corrective retry, then give up: a reply we cannot validate is never used.
            fix = asked + [{"role": "assistant", "content": r.text[:4000]},
                           {"role": "user", "content": f"That was not valid JSON for the schema ({str(err)[:300]}). "
                                                       "Reply with only the JSON object."}]
            r = self.complete(fix, provider=provider, **kw)
            r.parsed = _parse(_json_object(r.text), schema)
        return r

    # ---- transports -------------------------------------------------------
    def _responses(self, req: dict):
        resp = self._client("meta").responses.create(**req)
        u = resp.usage
        details = getattr(u, "input_tokens_details", None)
        cached = (getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
        calls = [FunctionCall(item.name, item.arguments or "{}", item.call_id)
                 for item in (resp.output or []) if getattr(item, "type", None) == "function_call"]
        items = [_replayable(item) for item in (resp.output or [])]
        return resp.output_text or "", (u.input_tokens or 0, cached, u.output_tokens or 0), resp, resp.id, calls, items

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

    # ---- recorded replies ----------------------------------------------------
    def _recorded(self, key: str) -> dict | None:
        if self._recordings is None:
            path = Path(self.settings.record_path or self.settings.replay_path)
            lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            self._recordings = {r["key"]: r for r in map(json.loads, filter(None, lines))}  # the newest wins
        return self._recordings.get(key)

    def _record(self, key, purpose, provider, model, text, calls, items, usage, cost, incomplete, reasoning_tokens):
        """Append one live reply: what came back and what it cost. Not the request: code + data rebuild it."""
        kept = [d for d in map(_replayable, items) if d.get("type") != "reasoning"]  # reasoning is encrypted
        row = {"key": key, "purpose": purpose, "provider": provider, "model": model,
               "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "text": text,
               "function_calls": [{"name": c.name, "arguments": c.arguments, "call_id": c.call_id} for c in calls],
               "items": kept, "usage": list(usage), "cost_usd": cost, "incomplete": incomplete,
               "reasoning_tokens": reasoning_tokens}
        path = Path(self.settings.record_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _mock_call(self, messages, purpose, schema, tools=None, previous_response_id=None, stateless=False):
        fn = _mock_responders.get(purpose)
        if fn is None:
            raise RuntimeError(f"No mock responder registered for purpose {purpose!r}.")
        if previous_response_id and previous_response_id not in self._mock_threads:
            raise RuntimeError(f"Unknown previous_response_id {previous_response_id!r}.")  # as the server would
        thread = self._mock_threads.pop(previous_response_id, []) if previous_response_id else []
        thread = thread + list(messages)
        reply = fn(thread, schema.model_json_schema() if schema else None)
        calls: list[FunctionCall] = []
        raw = None
        if isinstance(reply, dict):
            if reply.get("incomplete"):  # lets tests play a reply cut off at the output limit
                raw = SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason=reply["incomplete"]))
            calls = [FunctionCall(c["name"], c["arguments"] if isinstance(c["arguments"], str)
                                  else json.dumps(c["arguments"], ensure_ascii=False), f"call_{uuid.uuid4().hex[:12]}")
                     for c in reply.get("function_calls", [])]
            text = reply.get("text", "")
        else:
            text = reply
        out_items = ([{"type": "function_call", "name": c.name, "arguments": c.arguments, "call_id": c.call_id}
                      for c in calls] or [{"role": "assistant", "content": text}])
        usage = (_estimate_input_tokens(thread), 0, math.ceil(len(json.dumps(out_items, ensure_ascii=False)) / 3))
        resp_id = None
        if tools:
            resp_id = f"mock_{uuid.uuid4().hex[:12]}"
            if not stateless:  # only server-side chains need the mock to remember the thread
                self._mock_threads[resp_id] = thread + out_items
        # Like the real API: a reasoning item (encrypted, with a summary) comes first, then the answer.
        items = [{"type": "reasoning", "summary": [], "encrypted_content": "mock-reasoning"}, *out_items]
        return text, usage, calls, resp_id, raw, items


_RANDOM_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def recording_key(purpose: str, provider: str, model: str, messages: list, schema: type[BaseModel] | None,
                  tools: list[dict] | None) -> str:
    """What a reply answered: the conversation without reasoning items (encrypted, different every run),
    with random ids (rule ids) masked, plus the schema and tools it was asked with."""
    convo = [m for m in map(_replayable, messages) if m.get("type") != "reasoning"]
    blob = json.dumps({"purpose": purpose, "provider": provider, "model": model, "messages": convo,
                       "schema": schema.model_json_schema() if schema else None,
                       "tools": [t.get("name") for t in tools or []]},
                      sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(_RANDOM_ID.sub("<id>", blob).encode("utf-8")).hexdigest()[:32]


def _from_recording(rec: dict):
    calls = [FunctionCall(c["name"], c["arguments"], c["call_id"]) for c in rec["function_calls"]]
    raw = (SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason=rec["incomplete"]))
           if rec.get("incomplete") else None)
    reasoning = {"type": "reasoning", "summary": [], "encrypted_content": "recorded"}
    items = [reasoning, *rec["items"]] if rec["items"] else []
    return rec["text"], tuple(rec["usage"]), calls, None, raw, items


def _reasoning_usage(raw) -> tuple[int | None, int | None]:
    """(reasoning tokens the provider reported, characters of reasoning text it sent back)."""
    usage = getattr(raw, "usage", None)
    tokens = None
    for name in ("output_tokens_details", "completion_tokens_details"):  # Responses, Chat Completions
        n = getattr(getattr(usage, name, None), "reasoning_tokens", None)
        if isinstance(n, int):
            tokens = n
    chars = None
    choices = getattr(raw, "choices", None)
    if choices:
        msg = getattr(choices[0], "message", None)
        text = getattr(msg, "reasoning_content", None) or (getattr(msg, "model_extra", None) or {}).get(
            "reasoning_content")
        chars = len(text) if isinstance(text, str) else None
    return tokens, chars


def _schema_refused(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    text = str(getattr(exc, "message", "") or exc).lower()
    return status in (400, 422) and any(w in text for w in ("response_format", "json_schema", "schema"))


def _with_json_instructions(messages: list[dict], schema: type[BaseModel]) -> list[dict]:
    rule = ("Reply with one JSON object only, no prose and no code fences, matching this JSON schema exactly:\n"
            + json.dumps(strict_schema(schema), ensure_ascii=False))
    if messages and messages[0].get("role") == "system":
        return [{**messages[0], "content": messages[0]["content"] + "\n\n" + rule}, *messages[1:]]
    return [{"role": "system", "content": rule}, *messages]


def _json_object(text: str) -> str:
    """The outermost {...} in a reply that may carry prose or a fence around it."""
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else text


def _replayable(item) -> dict:
    """A response output item as an input item for the next stateless turn."""
    d = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else dict(item)
    if d.get("type") == "reasoning":
        d.setdefault("summary", [])  # Meta requires a summary on every reasoning input item, even []
    return d


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
            if "const" in node:  # a one-value Literal: written as an enum, the form every strict subset knows
                node["enum"] = [node.pop("const")]
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
