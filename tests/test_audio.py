"""Recorder.listen endpointing on synthesized audio (no microphone): tap, hold, and click rejection."""

import queue
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest
import webrtcvad

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from torti.audio import FRAME, SAMPLE_RATE, Recorder  # noqa: E402


@pytest.fixture(scope="module")
def speech(tmp_path_factory) -> np.ndarray:
    """~1.5 s of Korean speech from SAPI, int16 at 16 kHz."""
    import win32com.client

    path = tmp_path_factory.mktemp("tts") / "q.wav"
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
    fmt.Type = 18
    stream.Format = fmt
    stream.Open(str(path), 3)
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    voice.AudioOutputStream = stream
    voice.Speak("이 저항 몇 옴이야?")
    stream.Close()
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def silence(seconds: float, level: float = 0.0005) -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.normal(0, level, int(SAMPLE_RATE * seconds)) * 32768).astype(np.int16)


def make_recorder() -> Recorder:
    rec = Recorder.__new__(Recorder)  # skip the real input stream
    rec._vad = webrtcvad.Vad(2)
    rec.min_rms = 0.003
    rec._q = queue.Queue()
    rec._listening = False
    rec.level = 0.0
    return rec


def run(rec: Recorder, audio: np.ndarray, hold: threading.Event | None = None,
        stop: threading.Event | None = None, release: bool = False):
    def feed() -> None:
        while not rec._listening:
            time.sleep(0.001)
        q = rec._q
        for i in range(0, len(audio) - FRAME + 1, FRAME):
            q.put(audio[i:i + FRAME].copy())
        if release:  # pedal let go after the last frame was consumed
            while not q.empty():
                time.sleep(0.001)
            hold.clear()
            stop.set()

    threading.Thread(target=feed, daemon=True).start()
    return rec.listen(end_silence_ms=700, wait_speech_s=3, hold=hold, stop=stop)


def test_tap_mode_endpoints_after_speech(speech):
    utt = run(make_recorder(), np.concatenate([silence(0.5), speech, silence(1.5)]))
    assert utt is not None and not utt.manual_stop
    dur = len(utt.audio) / SAMPLE_RATE
    assert len(speech) / SAMPLE_RATE <= dur <= len(speech) / SAMPLE_RATE + 1.2


def test_click_is_not_speech():
    click = (np.random.default_rng(1).normal(0, 0.2, int(SAMPLE_RATE * 0.06)) * 32768).astype(np.int16)
    assert run(make_recorder(), np.concatenate([silence(0.5), click, silence(1.5)])) is None


def test_hold_mode_keeps_pauses_and_quiet_speech(speech):
    quiet = (speech * 0.3).astype(np.int16)
    # A long pause mid-sentence would end tap mode; while held it must not.
    audio = np.concatenate([silence(0.3), quiet, silence(1.2), quiet, silence(0.3)])
    hold, stop = threading.Event(), threading.Event()
    hold.set()
    utt = run(make_recorder(), audio, hold=hold, stop=stop, release=True)
    assert utt is not None and utt.manual_stop
    assert len(utt.audio) == len(audio) // FRAME * FRAME
