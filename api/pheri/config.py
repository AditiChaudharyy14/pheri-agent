"""Runtime settings, read from environment variables at call time.

Secrets (API keys) are never stored in code or in the repo. Put them in a local
`.env` file (git-ignored) or in your hosting provider's environment settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader so we need no extra dependency. Existing env always wins."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), _clean_value(value))


def _clean_value(value: str) -> str:
    """Quoted values are taken literally; unquoted values lose any trailing ` # comment`."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    for marker in (" #", "\t#"):
        if marker in value:
            value = value.split(marker, 1)[0]
    if value.startswith("#"):
        return ""
    return value.strip()


_load_dotenv(REPO_ROOT / ".env")


def _env(name: str, default: str | None = None):
    return field(default_factory=lambda: os.environ.get(name, default))


def _envf(name: str, default: float):
    def read() -> float:
        try:
            return float(os.environ.get(name, default))
        except ValueError:
            return default

    return field(default_factory=read)


@dataclass(frozen=True)
class Settings:
    # "live" calls real providers; "mock" never touches the network (tests, offline demos); "replay" never
    # touches it either, and plays back the replies a live run recorded (the public demo).
    llm_mode: str = _env("PHERI_LLM_MODE", "mock")
    record_path: str | None = _env("PHERI_LLM_RECORD")  # live only: append every reply to this file
    replay_path: str = _env("PHERI_LLM_REPLAY", str(REPO_ROOT / "data" / "recorded" / "llm.jsonl"))

    # Meta Model API
    meta_base_url: str = _env("META_BASE_URL", "https://api.meta.ai/v1")
    meta_api_key: str | None = _env("MODEL_API_KEY")

    # Baseten: Muse Spark Open (open weights)
    baseten_base_url: str = _env("BASETEN_BASE_URL", "https://inference.baseten.co/v1")
    baseten_api_key: str | None = _env("BASETEN_API_KEY")
    baseten_model: str = _env("BASETEN_MODEL", "meta-models/muse-spark-open-1026")

    # Modal: Muse Glimmer (open weights), filled in once the endpoint exists
    modal_base_url: str | None = _env("MODAL_BASE_URL")
    modal_api_key: str | None = _env("MODAL_PROXY_TOKEN")
    modal_model: str = _env("MODAL_MODEL", "meta-models/Muse-Glimmer-30B")

    # Spend guard. Meta gives $150 of free credit; we stop at $130 to keep a buffer.
    meta_cap_usd: float = _envf("PHERI_META_CAP_USD", 130.0)
    baseten_cap_usd: float = _envf("PHERI_BASETEN_CAP_USD", 90.0)
    modal_cap_usd: float = _envf("PHERI_MODAL_CAP_USD", 90.0)
    # Spend made outside Pheri (dashboard Chat, Muse Code). Add it here so the cap stays honest.
    meta_offset_usd: float = _envf("PHERI_META_SPEND_OFFSET_USD", 0.0)
    # Refuse any single call estimated above this, unless the caller explicitly allows it.
    max_call_usd: float = _envf("PHERI_MAX_CALL_USD", 0.50)

    # Ledger storage: Postgres when DATABASE_URL is set, else a local SQLite file.
    database_url: str | None = _env("DATABASE_URL")
    ledger_path: str = _env("PHERI_LEDGER_PATH", str(REPO_ROOT / ".pheri" / "ledger.sqlite"))
    # A throwaway Postgres (Neon test branch) for the real RLS tests. Unset: those tests skip.
    test_database_url: str | None = _env("PHERI_TEST_DATABASE_URL")

    # Data policy: free-credit and contributor-mode content may be used by Meta to improve
    # products, so by default only synthetic data may be sent to any model.
    allow_real_data: bool = field(
        default_factory=lambda: os.environ.get("PHERI_ALLOW_REAL_DATA", "0") == "1"
    )


def get_settings() -> Settings:
    return Settings()
