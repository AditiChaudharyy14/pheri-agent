"""Probe: can Muse Spark Open (open weights, Baseten) read a Nepali voice note? Muse Voice cannot: Nepali is
not among its 25 languages. One call, through llm.py, with the Baseten cap lowered to "spent + budget".

    python scripts/probe_audio.py clip.m4a                   # mock: no network
    python scripts/probe_audio.py clip.m4a --live --budget 0.10

Any audio format: ffmpeg converts it to WAV, mono, 16 kHz first. The transcript is compared with the script
the clip was read from (character error rate, spaces and punctuation ignored).
"""

import argparse
import base64
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

SCRIPT_NE = "नमस्ते, मैले गएको हप्ता दुईवटा साडी अर्डर गरेको थिएँ। अझै आइपुगेको छैन। तिहार अगाडि पठाइदिनुहोस् न।"
PROMPT = ("This is a voice note a customer sent to a clothing shop in Nepal. Write down exactly what is said, word for "
          "word, in the script of the language spoken (Devanagari for Nepali). Do not translate or summarise. Reply "
          "with the transcript only. Then, on a last line, write: LANGUAGE: <language name>.")


def to_wav(src: Path) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "clip.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000",
                        "-sample_fmt", "s16", str(out)], check=True)
        return out.read_bytes()


def cer(got: str, want: str) -> float:
    norm = lambda s: re.sub(r"[\s।,.!?\"'-]", "", s)  # noqa: E731
    a, b = norm(got), norm(want)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(1, len(b))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", type=Path)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--budget", type=float, default=None)
    ap.add_argument("--script", default=SCRIPT_NE, help="what the clip says, to score the transcript")
    args = ap.parse_args()
    if args.live and (args.budget is None or args.budget > 0.10):
        print("--live needs --budget, at most 0.10 (USD on Baseten).")
        return 2
    if args.live:
        os.environ["PHERI_LLM_MODE"] = "live"

    from pheri.config import Settings
    from pheri.ledger import Ledger
    from pheri.llm import LLM, register_mock, wav_duration_ms

    register_mock("audio_probe", lambda m, s: "(mock transcript)\nLANGUAGE: Nepali")
    wav = to_wav(args.clip)
    seconds = wav_duration_ms(wav) / 1000
    settings = Settings()
    if args.live:
        settings = Settings(baseten_cap_usd=Ledger(settings).totals("baseten").committed_usd + args.budget)
    llm = LLM(settings)
    url = "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii")
    messages = [{"role": "user", "content": [{"type": "text", "text": PROMPT},
                                             {"type": "audio_url", "audio_url": {"url": url}}]}]
    r = llm.complete(messages, purpose="audio_probe", provider="baseten", effort="low", max_tokens=2000)
    lines = [ln for ln in r.text.strip().splitlines() if ln.strip()]
    language = lines[-1] if lines and lines[-1].upper().startswith("LANGUAGE") else "(not given)"
    transcript = "\n".join(ln for ln in lines if ln is not language)
    print(f"Mode: {llm.settings.llm_mode}  clip: {seconds:.1f} s  model: {r.model}")
    print(f"tokens in={r.input_tokens} out={r.output_tokens} (reasoning {r.reasoning_tokens})  "
          f"cost ${r.cost_usd:.6f}  {r.latency_s:.1f} s")
    print(f"Script:     {args.script}")
    print(f"Transcript: {transcript}")
    print(f"{language}")
    print(f"Character error rate: {cer(transcript, args.script):.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
