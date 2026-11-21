"""M0 device check: earcons, TTS (incl. stop), mic noise floor, and an acoustic loopback
(TTS speaks a question -> mic -> VAD endpoint -> STT). Makes sound on the default speaker.

    .venv\\Scripts\\python spike\\devices_check.py --mic "Wave:3"
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from torti.audio import Recorder, find_device  # noqa: E402
from torti.camera import Camera, encode_jpeg, list_cameras, resolve_camera  # noqa: E402
from torti.sounds import Earcons  # noqa: E402
from torti.stt import WhisperStt  # noqa: E402
from torti.tts import SapiTts  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mic", default=None)
    ap.add_argument("--speaker", default=None)
    args = ap.parse_args()

    print("cameras:", list_cameras())
    idx, name = resolve_camera()
    cam = Camera(index=idx)
    t = time.perf_counter()
    ok = cam.open()
    print(f"camera open: {name} idx={idx} ok={ok} ({time.perf_counter() - t:.2f}s)")
    if ok:
        t = time.perf_counter()
        frame = cam.snapshot()
        jpeg = encode_jpeg(frame)
        print(f"snapshot+encode: {(time.perf_counter() - t) * 1000:.0f}ms, {frame.shape[1]}x{frame.shape[0]} "
              f"-> {len(jpeg) // 1024}KB, frame age {cam.frame_age() * 1000:.0f}ms")
        cam.close()

    ear = Earcons(find_device(args.speaker, "output"))
    for n in ("listen", "accept", "idle"):
        ear.play(n)
        time.sleep(0.4)

    tts = SapiTts(output_hint=args.speaker)
    print("tts voice:", tts.voice_name)
    t = time.perf_counter()
    tts.say("토르티 장치 점검을 시작합니다.")
    while not tts.busy():
        time.sleep(0.005)
    tts.wait_done()
    print(f"tts sentence done in {time.perf_counter() - t:.2f}s")
    tts.say("이 문장은 중간에 끊겨야 합니다. 끊기지 않으면 중단 기능에 문제가 있는 것입니다.")
    time.sleep(0.8)
    t = time.perf_counter()
    tts.stop()
    tts.wait_done(timeout=3)
    print(f"tts stop -> idle in {(time.perf_counter() - t) * 1000:.0f}ms")

    rec = Recorder(find_device(args.mic, "input"))
    print("mic:", rec.device_name)
    levels = []
    for _ in range(40):
        levels.append(rec.level)
        time.sleep(0.05)
    print(f"noise floor rms: median={np.median(levels):.4f} max={max(levels):.4f}")

    print("loading STT...")
    stt = WhisperStt()
    stt.warmup()
    result = {}

    def listen() -> None:
        result["utt"] = rec.listen(wait_speech_s=8, end_silence_ms=700)

    th = threading.Thread(target=listen)
    th.start()
    time.sleep(0.3)
    tts.say("이 저항 몇 옴이야?")
    th.join(timeout=15)
    utt = result.get("utt")
    if utt is None:
        print("loopback: 마이크가 스피커 소리를 못 잡음 (헤드폰 출력이거나 볼륨이 낮으면 정상)")
    else:
        r = stt.transcribe(utt.audio)
        print(f"loopback: {len(utt.audio) / 16000:.2f}s audio, peak rms {utt.peak_rms:.3f}, "
              f"endpoint {round((utt.endpoint_at - utt.speech_end) * 1000)}ms after speech, "
              f"stt {r.seconds * 1000:.0f}ms -> {r.text!r}")
    rec.close()
    tts.close()
    ear.close()


if __name__ == "__main__":
    main()
