"""A/B listening: SAPI Heami (current) vs neural TTS samples, played on the default speaker.

    .venv\\Scripts\\python spike\\tts_compare_play.py <lab_dir>

Makes the SAPI baseline for the same sentences (with the mood's rate/pitch), then plays each mood:
announcement -> current voice -> each neural sample found in <lab_dir>.
"""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
import win32com.client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from torti.brief import MOOD_VOICE  # noqa: E402

SAMPLES = {
    "lively": ("활기", "좋아요! 이제 LED 열여섯 개를 달 차례예요. 긴 다리가 플러스 쪽인 것만 확인해 주세요."),
    "serious": ("진지", "좋습니다. 먼저 전원 플러그가 뽑혀 있는지 확인해 주세요. 변압기 일차측 절연 확인은 끝나셨나요?"),
    "friendly": ("친근", "우퍼 구멍 지름은 백이십팔 밀리미터예요. 트위터 쪽은 기록이 없으니 규격서를 확인해 보세요."),
}
_ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"


def heami():
    cat = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
    cat.SetId(_ONECORE, False)
    return next(t for t in cat.EnumerateTokens() if "Heami" in t.GetDescription())


def sapi_wav(text: str, path: Path, rate: int, pitch: int) -> None:
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
    fmt.Type = 34  # 44 kHz 16-bit mono
    stream.Format = fmt
    stream.Open(str(path), 3)
    v = win32com.client.Dispatch("SAPI.SpVoice")
    v.Voice = heami()
    v.Rate = rate
    v.AudioOutputStream = stream
    v.Speak(f'<pitch absmiddle="{pitch}">{text}</pitch>', 8)
    stream.Close()


def play(path: Path) -> None:
    with wave.open(str(path)) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        sr = w.getframerate()
    sd.play(audio, sr)
    sd.wait()
    time.sleep(0.6)


def announce(text: str) -> None:
    v = win32com.client.Dispatch("SAPI.SpVoice")
    v.Voice = heami()
    v.Rate = 2
    v.Speak(text)
    time.sleep(0.3)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    lab = Path(sys.argv[1])
    for key, (mood, text) in SAMPLES.items():
        rate, pitch = MOOD_VOICE[mood]
        base = lab / f"sapi_{key}.wav"
        sapi_wav(text, base, rate, pitch)
        candidates = sorted(p for p in lab.glob(f"*_{key}*.wav") if not p.name.startswith("sapi_"))
        print(f"[{mood}] {text}")
        announce(f"{mood}. 지금 목소리.")
        play(base)
        for i, p in enumerate(candidates, 1):
            print(f"   {i}번: {p.name}")
            announce(f"새 목소리 {i}번.")
            play(p)


if __name__ == "__main__":
    main()
