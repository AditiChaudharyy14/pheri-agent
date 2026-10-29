"""Transcribe one WAV clip with Muse Voice, through llm.py (ledger, cap, data policy). About $0.0005 per 10 s.

    python scripts/transcribe.py clip.wav                          # mock: no network
    python scripts/transcribe.py clip.wav --live --language Hindi  # one real call
    python scripts/transcribe.py clip.wav --live --record          # also save it for replay (data/recorded)

The clip must be mono 16-bit PCM at 16 or 24 kHz (ffmpeg -i in.m4a -ac 1 -ar 16000 -sample_fmt s16 out.wav).
Muse Voice reads Hindi and English (with code-switching), not Nepali or Bhojpuri.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", type=Path)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--record", action="store_true", help="append the reply to data/recorded/llm.jsonl")
    ap.add_argument("--language", action="append", default=[], help="language name to bias toward; repeatable")
    ap.add_argument("--keyword", action="append", default=[], help="word to bias toward; repeatable")
    ap.add_argument("--purpose", default="transcribe_smoke")
    args = ap.parse_args()
    if args.live:
        os.environ["PHERI_LLM_MODE"] = "live"
        if args.record:
            os.environ["PHERI_LLM_RECORD"] = str(Path(__file__).resolve().parents[1] / "data" / "recorded" / "llm.jsonl")

    from pheri.llm import LLM, register_mock

    register_mock(args.purpose, lambda m, s: "(mock transcript)")
    llm = LLM()
    r = llm.transcribe(args.wav.read_bytes(), purpose=args.purpose, language_bias=args.language or None,
                       keywords=args.keyword or None)
    print(f"Mode: {llm.settings.llm_mode}  audio: {r.parsed['audio_ms'] / 1000:.1f} s  "
          f"cost: ${r.cost_usd:.6f}  {r.latency_s:.1f} s")
    print(f"Transcript: {r.text}")
    t = llm.ledger.totals("meta")
    print(f"Ledger meta: spent ${t.settled_usd:.6f}, cap ${t.cap_usd:.2f}, remaining ${t.remaining_usd:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
