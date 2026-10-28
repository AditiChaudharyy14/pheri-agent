"""Record what the real model says for the demo's hero cards, so the public site can replay it.

    python scripts/record_demo.py                          # mock dry run: counts the calls, spends nothing
    python scripts/record_demo.py --live --budget 0.05     # real calls, appended to data/recorded/llm.jsonl

It drives the API itself (in-process), so every recorded conversation is exactly the one a replay
server rebuilds: the starting rules compiled, then each hero's replies read by the guard, the profile
read, and the decision's whole tool loop. Only synthetic data is sent. As a backstop the Meta cap for
this one process is lowered to "spent so far + budget", so the ledger refuses any call past the budget.
Afterwards it replays the same requests offline and checks every one is found in the recording.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "api"))
sys.stdout.reconfigure(encoding="utf-8")

HEROES = {"brightdesk": ["maya.okafor@pinecrest.example"]}
RECORDING = REPO / "data" / "recorded" / "llm.jsonl"


def run(mode: str, record: Path | None, replay: Path | None = None) -> dict:
    """One API process in `mode`; returns each hero's decision card."""
    from fastapi.testclient import TestClient

    from pheri.app import create_app
    from pheri.config import Settings
    from pheri.llm import LLM

    llm = LLM(Settings())
    with TestClient(create_app(llm)) as client:
        cards = {}
        for b, keys in HEROES.items():
            for key in keys:
                r = client.get(f"/businesses/{b}/customers/{key}/decision")
                r.raise_for_status()
                cards[key] = r.json()
    return cards


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--budget", type=float, default=0.05)
    args = ap.parse_args()

    os.environ["DATABASE_URL"] = ""
    os.environ.pop("PHERI_LLM_RECORD", None)
    if not args.live:
        dry = REPO / ".pheri" / "record-dry-run.jsonl"
        dry.unlink(missing_ok=True)
        os.environ.update(PHERI_LLM_MODE="mock", PHERI_LEDGER_PATH=str(REPO / ".pheri" / "mock-ledger.sqlite"))
        from pheri import llm as llm_mod

        counted = []
        real = llm_mod.LLM.complete
        llm_mod.LLM.complete = lambda self, m, **kw: counted.append(kw["purpose"]) or real(self, m, **kw)
        run("mock", None)
        print(f"Dry run: {len(counted)} calls would be made: " +
              ", ".join(f"{p} x{counted.count(p)}" for p in dict.fromkeys(counted)))
        print("Nothing was sent. Add --live --budget <usd> to record for real.")
        return

    from pheri.config import Settings
    from pheri.ledger import Ledger

    spent = Ledger(Settings()).totals("meta").committed_usd
    os.environ.update(PHERI_LLM_MODE="live", PHERI_API_ALLOW_LIVE="1", PHERI_LLM_RECORD=str(RECORDING),
                      PHERI_META_CAP_USD=f"{spent + args.budget:.6f}")
    before = len(RECORDING.read_text(encoding="utf-8").splitlines()) if RECORDING.exists() else 0
    cards = run("live", RECORDING)
    rows = [json.loads(x) for x in RECORDING.read_text(encoding="utf-8").splitlines()[before:]]
    cost = sum(r["cost_usd"] for r in rows)
    print(f"Recorded {len(rows)} replies, ${cost:.4f}: " +
          ", ".join(f"{p} x{sum(r['purpose'] == p for r in rows)}" for p in dict.fromkeys(r["purpose"] for r in rows)))
    for key, card in cards.items():
        d = card["decision"]
        print(f"\n{key}: {d['action']} ({card.get('turns')} turns)\n  message: {d['message']}\n"
              f"  why this: {d['why_this']}\n  why now: {d['why_now']}")

    # Replay the same requests offline: every one must be found in the recording.
    os.environ.update(PHERI_LLM_MODE="replay", PHERI_LEDGER_PATH=str(REPO / ".pheri" / "mock-ledger.sqlite"),
                      PHERI_LLM_REPLAY=str(RECORDING))
    os.environ.pop("PHERI_LLM_RECORD")
    os.environ.pop("PHERI_META_CAP_USD")
    from pheri import llm as llm_mod

    misses = []
    real = llm_mod.LLM.complete

    def watch(self, m, **kw):
        r = real(self, m, **kw)
        if not r.recorded:
            misses.append(kw["purpose"])
        return r
    llm_mod.LLM.complete = watch
    replayed = run("replay", None)
    same = all(replayed[k]["decision"] == cards[k]["decision"] for k in cards)
    print(f"\nReplay check: {'every request found' if not misses else 'NOT recorded: ' + ', '.join(misses)}; "
          f"decisions {'identical' if same else 'DIFFER'}.")


if __name__ == "__main__":
    main()
