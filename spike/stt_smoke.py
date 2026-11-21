"""Smoke test: load Whisper on GPU, warm up, transcribe synthesized Korean speech (SAPI Heami)."""

import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from torti.stt import WhisperStt  # noqa: E402


def synth_korean_wav(text: str, path: str) -> None:
    import win32com.client

    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
    fmt.Type = 18  # SAFT16kHz16BitMono
    stream.Format = fmt
    stream.Open(path, 3)  # SSFMCreateForWrite
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    for tok in voice.GetVoices():
        if "Heami" in tok.GetDescription():
            voice.Voice = tok
    voice.AudioOutputStream = stream
    voice.Speak(text)
    stream.Close()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    t = time.perf_counter()
    stt = WhisperStt()
    print(f"load: {time.perf_counter() - t:.1f}s device={stt.device} compute={stt.compute_type} model={stt.model_name}")
    print(f"warmup: {stt.warmup():.2f}s")
    phrase = "이 저항 몇 옴이야? 방금 납땜한 거 괜찮아?"
    path = str(Path(tempfile.gettempdir()) / "torti_stt_smoke.wav")
    synth_korean_wav(phrase, path)
    with wave.open(path) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    print(f"audio: {len(audio) / 16000:.2f}s")
    for _ in range(3):
        r = stt.transcribe(audio)
        print(f"stt {r.seconds * 1000:.0f}ms -> {r.text!r}")


if __name__ == "__main__":
    main()
