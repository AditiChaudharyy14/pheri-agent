"""Record what the real model says for the demo's showcase cards, so the public site can replay it.

    python scripts/record_demo.py                          # mock dry run: counts the calls, spends nothing
    python scripts/record_demo.py --live --budget 0.60 --baseten-budget 0.30   # real calls, appended to
                                                                               # data/recorded/llm.jsonl

It drives the API itself (in-process) and asks for each business's Next steps, exactly as the site does,
so every recorded conversation is the one a replay server rebuilds: the starting rules compiled, then for
each showcase customer the guard's read of their replies, their profile, the decision's whole tool loop,
and the judge's check of every draft (Muse Spark Open on Baseten), retries included. Only synthetic data is
sent. As a backstop the Meta and Baseten caps for this one process are lowered to "spent so far + budget",
so the ledger refuses any call past either budget. A run stopped part-way resumes: replies
already recorded for the same conversation are reused, not bought again.

Afterwards it replays the same requests offline, checks every one is found, and drops recorded replies
that no request asks for any more (a prompt changed since), except Muse Wonder's, which it never asks for.
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

BUSINESSES = ("brightdesk", "birgunj")
RECORDING = REPO / "data" / "recorded" / "llm.jsonl"
KEPT_PURPOSES_NOT_ASKED_HERE = {"learn_report"}  # recorded by scripts/live_learn.py


def run() -> dict:
    """One API process (mode from the environment); returns each showcase card by customer key."""
    from fastapi.testclient import TestClient

    from pheri.app import create_app
    from pheri.config import Settings
    from pheri.llm import LLM

    with TestClient(create_app(LLM(Settings()))) as client:
        cards = {}
        for b in BUSINESSES:
            r = client.get(f"/businesses/{b}/next-steps")
            r.raise_for_status()
            cards.update({card["customer"]["key"]: card for card in r.json()})
        # Slop vs Pheri: the plain drafts are model replies too, recorded with the cards (Birgunj, the hero).
        client.get("/businesses/birgunj/slop").raise_for_status()
        client.get("/businesses/birgunj/brief").raise_for_status()  # no model: it must not need one either
    return cards


def watch_calls(on_result) -> None:
    from pheri import llm as llm_mod

    real = llm_mod.LLM.complete

    def complete(self, messages, **kw):
        r = real(self, messages, **kw)
        on_result(kw["purpose"], r, messages, kw)
        return r
    llm_mod.LLM.complete = complete


def replay_check() -> None:
    """In a fresh process: replay every request and print (as JSON) which recorded replies it used and missed."""
    from pheri.llm import recording_key

    used, misses = set(), []

    def check(purpose, r, messages, kw):
        key = recording_key(purpose, r.provider, r.model, messages, kw.get("schema"), kw.get("tools"))
        (used.add(key) if r.recorded else misses.append(purpose))
    watch_calls(check)
    cards = run()
    print(json.dumps({"used": sorted(used), "misses": misses,
                      "decisions": {k: c["decision"] for k, c in cards.items()}}, ensure_ascii=False))


def main() -> None:
    if "--replay-check" in sys.argv:
        replay_check()
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--budget", type=float, default=0.60, help="USD on the Meta Model API")
    ap.add_argument("--baseten-budget", type=float, default=0.30, help="USD on Baseten (the judge)")
    args = ap.parse_args()

    os.environ["DATABASE_URL"] = ""
    os.environ.pop("PHERI_LLM_RECORD", None)
    if not args.live:
        os.environ.update(PHERI_LLM_MODE="mock", PHERI_LEDGER_PATH=str(REPO / ".pheri" / "mock-ledger.sqlite"))
        counted = []
        watch_calls(lambda purpose, r, m, kw: counted.append(purpose))
        cards = run()
        print(f"Dry run: {len(cards)} showcase cards, {len(counted)} calls would be made: " +
              ", ".join(f"{p} x{counted.count(p)}" for p in dict.fromkeys(counted)))
        print("Nothing was sent. Add --live --budget <usd> to record for real.")
        return

    from pheri.config import Settings
    from pheri.ledger import Ledger

    led = Ledger(Settings())
    spent, spent_b = led.totals("meta").committed_usd, led.totals("baseten").committed_usd
    os.environ.update(PHERI_LLM_MODE="live", PHERI_API_ALLOW_LIVE="1", PHERI_LLM_RECORD=str(RECORDING),
                      PHERI_META_CAP_USD=f"{spent + args.budget:.6f}",
                      PHERI_BASETEN_CAP_USD=f"{spent_b + args.baseten_budget:.6f}")
    before = len(RECORDING.read_text(encoding="utf-8").splitlines()) if RECORDING.exists() else 0
    cards = run()
    rows = [json.loads(x) for x in RECORDING.read_text(encoding="utf-8").splitlines()[before:]]
    print(f"Recorded {len(rows)} new replies, ${sum(r['cost_usd'] for r in rows):.4f}: " +
          ", ".join(f"{p} x{sum(r['purpose'] == p for r in rows)}" for p in dict.fromkeys(r["purpose"] for r in rows)))
    for key, card in cards.items():
        d = card["decision"]
        v = card.get("verification") or {}
        print(f"\n{card['customer']['name']} ({card['customer']['stage']}): {d['action']}, {card['turns']} turns,"
              f" ${card['cost_usd']:.4f}, {v.get('attempts', 0)} draft(s), "
              + ("verified" if v.get("passed") else f"NOT verified ({v.get('caught_by')})")
              + f"\n  message: {d['message']}\n  why this: {d['why_this']}\n  why now: {d['why_now']}")
        for r in v.get("reasons") or []:
            print(f"  ! {r}")

    # Replay the same requests offline, in a fresh process (as the server starts): every one must be found. A check in
    # this process could pass on state the live run left behind and miss what a clean start asks for.
    import subprocess

    done = subprocess.run([sys.executable, __file__, "--replay-check"], capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PHERI_LLM_MODE": "replay", "PHERI_LLM_REPLAY": str(RECORDING),
                               "PHERI_LLM_RECORD": "", "PHERI_LEDGER_PATH": str(REPO / ".pheri" / "mock-ledger.sqlite")})
    if done.returncode != 0:
        raise SystemExit(f"Replay check crashed:\n{done.stderr[-2000:]}")
    check = json.loads(done.stdout.strip().splitlines()[-1])
    used, misses = set(check["used"]), check["misses"]
    same = all(check["decisions"].get(k) == cards[k]["decision"] for k in cards) and set(check["decisions"]) == set(cards)
    print(f"\nReplay check (fresh process): {'every request found' if not misses else 'NOT recorded: ' + ', '.join(misses)}; "
          f"decisions {'identical' if same else 'DIFFER'}.")
    if misses or not same:
        raise SystemExit("Not pruning: the recording does not cover a clean start. Run --live again: only what is "
                         "missing is paid for.")

    lines = RECORDING.read_text(encoding="utf-8").splitlines()
    keep = [x for x in lines if (row := json.loads(x))["key"] in used or row["purpose"] in KEPT_PURPOSES_NOT_ASKED_HERE]
    RECORDING.write_text("\n".join(keep) + "\n", encoding="utf-8")
    print(f"Recording: {len(keep)} replies kept, {len(lines) - len(keep)} no longer asked for dropped.")


if __name__ == "__main__":
    main()
