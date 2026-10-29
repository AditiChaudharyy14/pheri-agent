"""Customer voice notes: transcribed by Muse Voice where it can read the language, said plainly where it cannot.

    notes = fill(ds, llm)      # before profiles, guard and decisions read the customer's messages

Muse Voice Transcribe reads 25 languages, Hindi and English among them, but not Nepali or Bhojpuri
(dev.meta.ai/docs/speech-to-text, 29 Oct 2026). So a Hindi voice note becomes text the rest of Pheri reads like
any message, and a Nepali one stays empty and goes to the owner: "a voice note Pheri cannot read yet".

The audio is recorded by a person (data/synth/<business>/audio/<id>.wav). Until it is, the line the clip will
be read from stands in for the transcript, and every status says so: nothing pretends a model heard it.
"""

from __future__ import annotations

import json
from pathlib import Path

from .llm import LLM, register_mock
from .synth import OUT

PURPOSE = "transcribe_voice_note"
VOICE_LANGUAGES = {"hi": "Hindi", "en": "English"}  # what Muse Voice reads, of the languages the shop hears
LANGUAGE_BIAS = ["Hindi", "English"]  # the shop's customers who can be read; Muse Voice detects which
KEYWORDS = ["Raxaul", "Birgunj", "Chhath", "saree"]  # names it would otherwise mishear

TRANSCRIBED, STAND_IN, UNREADABLE = "transcribed", "stand_in", "unreadable"
STATUS_TEXT = {
    TRANSCRIBED: "Transcribed by Muse Voice",
    STAND_IN: "Transcript stand-in: the audio is not recorded yet",
    UNREADABLE: "Muse Voice cannot read this language yet: the owner listens",
}


def fill(ds, llm: LLM, folder: Path | None = None) -> dict[str, dict]:
    """Puts each readable voice note's transcript into its Source.text. Returns {message id: status}."""
    folder = folder or OUT / ds.business
    truth = folder / "_truth.json"
    scripts = json.loads(truth.read_text(encoding="utf-8")).get("voice_notes", {}) if truth.exists() else {}
    out = {}
    for c in ds.customers.values():
        for src in c.sources:
            if src.kind != "voice_note":
                continue
            audio = folder / "audio" / f"{src.id}.wav"
            status = {"customer": c.key, "lang": src.lang}
            if src.lang not in VOICE_LANGUAGES:
                src.text, status["status"] = "", UNREADABLE
            elif audio.exists():
                r = llm.transcribe(audio.read_bytes(), purpose=PURPOSE, language_bias=LANGUAGE_BIAS, keywords=KEYWORDS,
                                   data_class=ds.data_class)
                src.text, status["status"], status["recorded"] = r.text, TRANSCRIBED, r.recorded
                status["cost_usd"] = r.cost_usd
            else:
                src.text, status["status"] = scripts.get(src.id, {}).get("script", ""), STAND_IN
            status["says"] = STATUS_TEXT[status["status"]]
            out[src.id] = status
    return out


register_mock(PURPOSE, lambda messages, schema: "(mock transcript)")
