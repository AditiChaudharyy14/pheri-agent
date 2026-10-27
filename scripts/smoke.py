"""One tiny live call per provider, to prove keys and wiring work. Costs well under $0.01.

    python scripts/smoke.py            # dry run: mock mode, no network
    python scripts/smoke.py --live     # real calls (Meta + Baseten)

Uses synthetic text only, low reasoning effort and small output limits. Every call goes
through the spend ledger, so the caps apply here too.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

if "--live" in sys.argv:
    os.environ["PHERI_LLM_MODE"] = "live"

from pydantic import BaseModel  # noqa: E402

from pheri.llm import LLM, register_mock  # noqa: E402


class Greeting(BaseModel):
    language: str
    greeting: str


register_mock("smoke", lambda m, s: '{"language": "Nepali", "greeting": "Namaste"}')
PROMPT = [{"role": "user", "content": "Return a one-word greeting in Nepali as JSON with fields language and greeting."}]


def main() -> int:
    llm = LLM()
    mode = llm.settings.llm_mode
    print(f"Mode: {mode}")
    checks = [("meta", "muse-spark-1.3", "minimal")]
    if mode == "mock" or llm.settings.baseten_api_key:
        checks.append(("baseten", llm.settings.baseten_model, "low"))
    ok = True
    for provider, model, effort in checks:
        try:
            r = llm.complete(PROMPT, purpose="smoke", provider=provider, model=model, schema=Greeting,
                             effort=effort, max_tokens=600)
            print(f"  OK  {provider:8} {model:36} -> {r.parsed.greeting!r}  "
                  f"in={r.input_tokens} out={r.output_tokens} cost=${r.cost_usd:.6f} {r.latency_s:.1f}s")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  FAIL {provider:8} {model:36} -> {type(exc).__name__}: {exc}")
    for provider in ("meta", "baseten"):
        t = llm.ledger.totals(provider)
        print(f"Ledger {provider}: spent ${t.settled_usd:.6f}, offset ${t.offset_usd:.2f}, cap ${t.cap_usd:.2f}, "
              f"remaining ${t.remaining_usd:.2f}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
