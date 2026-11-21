"""Probe camera brightness over time per backend, to find why snapshots come out black."""

import sys
import time
from pathlib import Path

import cv2

OUT = Path(__file__).resolve().parents[1] / "data" / "bench"


def probe(backend_name: str, backend: int, index: int, mjpg: bool, seconds: float = 4.0) -> None:
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        print(f"{backend_name} mjpg={mjpg}: open failed")
        return
    if mjpg:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    t0 = time.monotonic()
    n = 0
    samples = []
    frame = None
    while time.monotonic() - t0 < seconds:
        ok, f = cap.read()
        if not ok:
            continue
        n += 1
        frame = f
        if n in (1, 5, 15, 30, 60, 90, 120):
            samples.append(f"#{n}@{time.monotonic() - t0:.1f}s mean={f.mean():.1f}")
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fcc = "".join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4))
    print(f"{backend_name} mjpg={mjpg}: {n} frames in {seconds}s, fourcc={fcc!r}, "
          f"size={None if frame is None else frame.shape[1::-1]} | " + "; ".join(samples))
    if frame is not None:
        cv2.imwrite(str(OUT / f"probe_{backend_name}_{'mjpg' if mjpg else 'raw'}.jpg"), frame)
    cap.release()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    probe("dshow", cv2.CAP_DSHOW, idx, True)
    probe("dshow", cv2.CAP_DSHOW, idx, False)
    probe("msmf", cv2.CAP_MSMF, idx, False)
