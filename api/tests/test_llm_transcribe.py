"""Muse Voice Transcribe goes through the same door as every model call: data policy, private fence,
ledger, retries, recording and replay. No network: the live endpoint is faked at `_transcribe`."""

import io
import json
import wave

import pytest

from pheri.config import Settings
from pheri.llm import LLM, DataPolicyError, SpendCapExceeded, _HTTPError, register_mock, wav_duration_ms
from pheri.pricing import TRANSCRIBE_USD_PER_HOUR


def wav(seconds: float = 2.0, rate: int = 16_000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return buf.getvalue()


def _llm(monkeypatch, tmp_path, mode: str, **env) -> LLM:
    monkeypatch.setenv("PHERI_LLM_MODE", mode)
    monkeypatch.setenv("PHERI_LEDGER_PATH", str(tmp_path / f"{mode}-ledger.sqlite"))
    monkeypatch.setenv("PHERI_LLM_REPLAY", str(tmp_path / "recorded.jsonl"))
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    monkeypatch.delenv("PHERI_LLM_RECORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return LLM(Settings())


def _fake_endpoint(llm: LLM, monkeypatch, transcript="दस परसेंट से ज़्यादा डिस्काउंट मत देना", ms=2000):
    sent = []

    def endpoint(settings, audio):
        sent.append((settings, audio))
        return {"sessionId": "s1", "transcript": transcript, "audioDurationMs": ms, "turns": []}
    monkeypatch.setattr(llm, "_transcribe", endpoint)
    return sent


def test_wav_checks_refuse_what_the_endpoint_would():
    assert wav_duration_ms(wav(2.0)) == 2000
    assert wav_duration_ms(wav(1.5, rate=24_000)) == 1500
    for bad in (wav(1, rate=44_100), wav(1, channels=2), wav(1, width=1), b"not audio"):
        with pytest.raises(ValueError):
            wav_duration_ms(bad)
    with pytest.raises(ValueError):
        wav_duration_ms(wav(601))  # over 10 minutes


def test_mock_transcribes_offline_for_free(monkeypatch, tmp_path):
    llm = _llm(monkeypatch, tmp_path, "mock")
    register_mock("voice_test", lambda m, s: "mock transcript")
    r = llm.transcribe(wav(), purpose="voice_test")
    assert r.text == "mock transcript" and r.cost_usd == 0 and r.parsed["audio_ms"] == 2000
    t = llm.ledger.totals("meta")
    assert t.settled_usd == 0 and t.reserved_usd == 0


def test_live_sends_settings_and_bills_per_second(monkeypatch, tmp_path):
    llm = _llm(monkeypatch, tmp_path, "live")
    sent = _fake_endpoint(llm, monkeypatch, ms=36_000)
    r = llm.transcribe(wav(36), purpose="voice_test", language_bias=["Hindi", "English"], keywords=["Raxaul"])
    settings, audio = sent[0]
    assert settings == {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "PUSH_TO_TALK",
                        "languageBias": ["Hindi", "English"], "keywords": ["Raxaul"]}
    assert audio == wav(36)
    assert r.cost_usd == pytest.approx(36 / 3600 * TRANSCRIBE_USD_PER_HOUR)
    assert llm.ledger.totals("meta").settled_usd == pytest.approx(r.cost_usd)


def test_bad_audio_reserves_nothing(monkeypatch, tmp_path):
    llm = _llm(monkeypatch, tmp_path, "live")
    sent = _fake_endpoint(llm, monkeypatch)
    with pytest.raises(ValueError):
        llm.transcribe(wav(1, rate=44_100), purpose="voice_test")
    assert not sent
    t = llm.ledger.totals("meta")
    assert t.settled_usd == 0 and t.reserved_usd == 0


def test_cap_and_policies_refuse_before_sending(monkeypatch, tmp_path):
    llm = _llm(monkeypatch, tmp_path, "live", PHERI_META_CAP_USD="0.00001")
    sent = _fake_endpoint(llm, monkeypatch)
    with pytest.raises(SpendCapExceeded):
        llm.transcribe(wav(60), purpose="voice_test")
    with pytest.raises(DataPolicyError):
        llm.transcribe(wav(), purpose="voice_test", data_class="real")
    with llm.only("baseten"), pytest.raises(DataPolicyError):
        llm.transcribe(wav(), purpose="voice_test")
    assert not sent
    assert llm.ledger.totals("meta").reserved_usd == 0


def test_a_refused_request_is_not_billed_and_not_retried(monkeypatch, tmp_path):
    llm = _llm(monkeypatch, tmp_path, "live")
    calls = []

    def endpoint(settings, audio):
        calls.append(1)
        raise _HTTPError(400, "not a supported WAV file")
    monkeypatch.setattr(llm, "_transcribe", endpoint)
    with pytest.raises(_HTTPError):
        llm.transcribe(wav(), purpose="voice_test")
    assert len(calls) == 1
    t = llm.ledger.totals("meta")
    assert t.settled_usd == 0 and t.reserved_usd == 0


def test_audio_parts_are_estimated_by_length_not_base64_size():
    import base64

    from pheri.llm import AUDIO_MAX_SECONDS, AUDIO_TOKENS_PER_SECOND, _estimate_input_tokens

    def msg(url):
        return [{"role": "user", "content": [{"type": "text", "text": "transcribe"},
                                             {"type": "audio_url", "audio_url": {"url": url}}]}]
    ten_s = "data:audio/wav;base64," + base64.b64encode(wav(10)).decode()
    est = _estimate_input_tokens(msg(ten_s))
    assert 10 * AUDIO_TOKENS_PER_SECOND <= est < 10 * AUDIO_TOKENS_PER_SECOND + 100  # not ~100k from 427 kB of base64
    assert _estimate_input_tokens(msg("https://example.com/a.mp3")) >= AUDIO_MAX_SECONDS * AUDIO_TOKENS_PER_SECOND


def test_recorded_live_then_replayed_by_the_audio(monkeypatch, tmp_path):
    rec = tmp_path / "recorded.jsonl"
    live = _llm(monkeypatch, tmp_path, "live", PHERI_LLM_RECORD=str(rec))
    _fake_endpoint(live, monkeypatch, transcript="रक्सौल से बात हो रही है")
    first = live.transcribe(wav(2), purpose="voice_test", language_bias=["Hindi"])
    row = json.loads(rec.read_text(encoding="utf-8").splitlines()[0])
    assert row["audio_ms"] == 2000 and row["text"] == "रक्सौल से बात हो रही है"

    replay = _llm(monkeypatch, tmp_path, "replay")
    register_mock("voice_test", lambda m, s: "stand-in")
    again = replay.transcribe(wav(2), purpose="voice_test", language_bias=["Hindi"])
    assert again.recorded and again.text == first.text and again.cost_usd == pytest.approx(first.cost_usd)
    other = replay.transcribe(wav(3), purpose="voice_test", language_bias=["Hindi"])  # different audio: a miss
    assert not other.recorded and other.text == "stand-in"
    assert replay.ledger.totals("meta").settled_usd == 0
