"""Write what this week's live runs cost to data/spend/live.json, for the web app's Spend screen.

Reads the local spend ledger (no network, no model call) and keeps only totals per provider and
per model + purpose: no prompts, no replies, no keys. The API serves the file, so a deployed
server shows the real spend without a copy of the ledger.

    python scripts/spend_snapshot.py                      # the default live ledger, .pheri/ledger.sqlite
    python scripts/spend_snapshot.py --ledger path.sqlite
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from pheri.config import REPO_ROOT, get_settings  # noqa: E402
from pheri.ledger import Ledger  # noqa: E402

PROVIDERS = ("meta", "baseten")


def snapshot(ledger: Ledger) -> dict:
    providers = {}
    for p in PROVIDERS:
        t = ledger.totals(p)
        providers[p] = {"settled_usd": round(t.settled_usd, 6), "offset_usd": t.offset_usd, "cap_usd": t.cap_usd,
                        "remaining_usd": round(t.remaining_usd, 6)}
    rows = [r for r in ledger.breakdown() if r["provider"] in PROVIDERS]
    return {"as_of": datetime.now().isoformat(timespec="seconds"), "providers": providers, "calls": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=str(REPO_ROOT / ".pheri" / "ledger.sqlite"))
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "spend" / "live.json"))
    args = ap.parse_args()
    if not Path(args.ledger).exists():
        raise SystemExit(f"No ledger at {args.ledger}")
    ledger = Ledger(dataclasses.replace(get_settings(), ledger_path=args.ledger, database_url=""))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    snap = snapshot(ledger)
    out.write_text(json.dumps(snap, indent=1) + "\n", encoding="utf-8")
    for p, t in snap["providers"].items():
        print(f"{p}: ${t['settled_usd']:.4f} of ${t['cap_usd']:.0f}")
    print(f"{sum(r['calls'] for r in snap['calls'])} calls -> {out}")


if __name__ == "__main__":
    main()
