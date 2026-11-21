"""Hands-free self test of one full turn without a microphone.

SAPI synthesizes a spoken question; that audio replaces the mic input. Everything after it is
real: STT on GPU, Claude CLI (one short question), sentence-streamed TTS on the speaker,
history, and a work project pushed to a local bare repo standing in for GitHub.
Runs in a throwaway TORTI_DATA folder so the real project list is untouched.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="torti_e2e_"))
os.environ["TORTI_DATA"] = str(TMP / "data")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from m0_console import console_emit  # noqa: E402
from torti.audio import Utterance  # noqa: E402
from torti.config import Settings  # noqa: E402
from torti.engine import Engine  # noqa: E402

QUESTION = "인두 온도는 몇 도로 하면 돼?"


def synth(text: str, path: Path) -> np.ndarray:
    import win32com.client

    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
    fmt.Type = 18  # 16 kHz 16-bit mono
    stream.Format = fmt
    stream.Open(str(path), 3)
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    voice.AudioOutputStream = stream
    voice.Speak(text)
    stream.Close()
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    remote = TMP / "github.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    audio = synth(QUESTION, TMP / "q.wav")

    engine = Engine(Settings(image="never"), console_emit)
    engine.load()
    engine.open_project(new="셀프테스트 작업", remote=str(remote))

    def fake_listen(**_kw) -> Utterance:
        now = time.perf_counter()
        return Utterance(audio, now - len(audio) / 16000, now, now + 0.7, 0.2, False)

    engine.rec.listen = fake_listen
    engine.run_turn(time.perf_counter())
    engine.sync(announce=False)

    log = (engine.project.root / "log").glob("*.md")
    print("\nproject log:", *(p.read_text(encoding="utf-8") for p in log))
    print("remote commits:", subprocess.run(["git", "log", "--oneline"], cwd=remote, capture_output=True,
                                            text=True, encoding="utf-8").stdout.strip())
    engine.cli.stop()
    engine.rec.close()
    engine.earcons.close()


if __name__ == "__main__":
    main()
