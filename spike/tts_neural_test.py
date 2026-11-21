"""NeuralTts check: first-audio latency, pipelined sentences, barge-in stop, recovery. Speaks aloud."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from torti.tts_neural import NeuralTts  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    t = time.perf_counter()
    tts = NeuralTts()
    print("ready:", tts.wait_ready(), f"{time.perf_counter() - t:.1f}s", tts.error or "")
    tts.set_mood("친근")

    t0 = time.perf_counter()  # an answer streamed as two sentences, digits included
    tts.say("우퍼 구멍 지름은 128밀리미터이고, 트위터 쪽은 기록이 없어요.")
    tts.say("규격서에서 트위터 지름부터 확인해 보세요.")
    tts.wait_done()
    starts = [s - t0 for s in tts._play_starts]
    print(f"first audio {starts[0]:.2f}s after text, chunk starts {[round(s, 2) for s in starts]}, "
          f"all done {time.perf_counter() - t0:.2f}s")

    tts.set_mood("활기")
    tts.say("좋아요! 이제 LED 16개를 달 차례예요. 긴 다리가 플러스 쪽인 것만 확인해 주세요.")
    time.sleep(4.0)
    t = time.perf_counter()
    tts.stop()  # barge-in
    while tts.busy():
        time.sleep(0.005)
    print(f"stop -> silent {1000 * (time.perf_counter() - t):.0f} ms")

    t = time.perf_counter()
    n = len(tts._play_starts)
    tts.say("네, 말씀하세요.")
    tts.wait_done()
    print(f"after stop: next sentence audio after {tts._play_starts[n] - t:.2f}s" if len(tts._play_starts) > n
          else "after stop: nothing played")
    tts.close()


if __name__ == "__main__":
    main()
