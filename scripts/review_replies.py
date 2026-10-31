"""Every reply Birgunj's customers would get in Nepali, Roman Nepali, Hindi or Bhojpuri, for a native speaker's review.

    python scripts/review_replies.py <out.txt>

Reads the recorded night (replay: no model is called, nothing is spent): Pheri's message for each customer, with
what the customer wrote and where the reply stands, then the fixed holding replies written by code (every
template, and who got one tonight). English replies are left out. Plain text, UTF-8.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "api"))
os.environ.update(PHERI_LLM_MODE="replay", PHERI_LLM_REPLAY=str(REPO / "data" / "recorded" / "llm.jsonl"),
                  DATABASE_URL="", PHERI_LLM_RECORD="", PHERI_LEDGER_PATH=str(REPO / ".pheri" / "mock-ledger.sqlite"))

REVIEWED = ("ne", "ne-Latn", "hi", "bho")
STATUS = {"scheduled": "ready at 08:00", "awaiting_approval": "waits for the owner", "blocked": "blocked",
          "executed": "sent"}


def main(out: Path) -> int:
    from fastapi.testclient import TestClient

    from pheri.app import create_app
    from pheri.config import Settings
    from pheri.holding import TEMPLATES
    from pheri.llm import LLM
    from pheri.words import ACTION_WORDS, LANGUAGE_NAMES, read_language

    with TestClient(create_app(LLM(Settings()))) as api:
        brief = api.get("/businesses/birgunj/brief").json()
        cards = {c["customer"]["key"]: c for c in api.get("/businesses/birgunj/next-steps").json()}
    lines = [f"Birgunj Saree Ghar: every reply in Nepali, Roman Nepali, Hindi and Bhojpuri, for native review",
             f"The recorded night of 29-30 Oct 2026, replayed; exported {date.today().isoformat()}.",
             "Under each reply, write OK, or the better version.", ""]
    n = 0
    lines += ["== Pheri's replies (Muse Spark 1.3 wrote them; code and the judge checked them) ==", ""]
    for e in brief["timeline"]:
        c = cards.get(e["customer"]["key"])
        msg = (c or {}).get("decision", {}).get("message") or ""
        if not msg or c["decision"]["action"] in ("task_for_owner", "no_action"):
            continue
        lang = read_language(msg)
        if lang not in REVIEWED:
            continue
        n += 1
        status = STATUS.get((c.get("action") or {}).get("status"), (c.get("action") or {}).get("status") or "")
        lines += [f"{n}. {e['customer']['name']} ({e['customer'].get('town') or ''}) · reply in "
                  f"{LANGUAGE_NAMES[lang]} · {ACTION_WORDS.get(c['decision']['action'], c['decision']['action'])}"
                  f" · {status}",
                  f"   They wrote ({LANGUAGE_NAMES.get(e['lang'] or '', e['lang'] or '?')}): {e['text'] or e['voice']}",
                  f"   Pheri:       {msg}",
                  "   Your review: ", ""]
    lines += ["== Fixed holding replies, written by code (an attacker gets one; no model writes to them) ==", ""]
    got = {s["holding_reply"]["language"]: s["customer"]["name"] for s in brief["stopped"] if s.get("holding_reply")}
    for lang in REVIEWED:
        n += 1
        who = f" · sent tonight to {got[lang]}" if lang in got else ""
        lines += [f"{n}. Template, {LANGUAGE_NAMES[lang]}{who}",
                  f"   Text:        {TEMPLATES[lang].format(first='<first name>', shop='Birgunj Saree Ghar')}",
                  "   Your review: ", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"{out}: {n} replies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
