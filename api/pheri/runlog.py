"""Every live run is saved in full to .pheri/runs/ (git-ignored), so nothing a paid run showed is lost.

    path = save_run("decide", {"args": ..., "outcomes": [...], "calls": [...], "ledger": {...}})
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import REPO_ROOT

RUNS = REPO_ROOT / ".pheri" / "runs"


def save_run(kind: str, payload: dict, folder: Path = RUNS) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = folder / f"{stamp}-{kind}-{uuid.uuid4().hex[:6]}.json"
    path.write_text(json.dumps({"kind": kind, "saved_at": stamp, **payload}, ensure_ascii=False, indent=1,
                               default=str), encoding="utf-8")
    return path


MAX_ANSWER_CHARS = 40_000  # enough for a runaway answer cut off at 8000 tokens


def call_record(purpose: str | None, r) -> dict:
    """What a call cost, where its output tokens went, and what the model answered (so a failed run can be
    read afterwards). Never the prompt, never a key; models only ever see synthetic data (llm.py)."""
    return {"purpose": purpose, "provider": r.provider, "model": r.model, "input_tokens": r.input_tokens,
            "cached_tokens": r.cached_tokens, "output_tokens": r.output_tokens,
            "reasoning_tokens": r.reasoning_tokens, "reasoning_chars": r.reasoning_chars,
            "answer_chars": len(r.text or ""), "answer_text": (r.text or "")[:MAX_ANSWER_CHARS],
            "incomplete": r.incomplete, "cost_usd": r.cost_usd, "latency_s": round(r.latency_s, 2)}
