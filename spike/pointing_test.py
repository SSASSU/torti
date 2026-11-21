"""How precisely can Claude point at things in a photo? Synthetic board with known part positions.

    .venv\\Scripts\\python spike\\pointing_test.py [--models haiku,sonnet]

Draws a PCB-like image (silkscreen labels, resistors, LEDs, an IC), asks "where is X?" with the
pointing rules, and scores each returned box: does its center fall inside the true part, and IoU.
Saves annotated results to data/bench/pointing_<model>.png.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from torti.camera import encode_jpeg  # noqa: E402
from torti.visual import Pointer  # noqa: E402

W, H = 1600, 900


def board() -> tuple[np.ndarray, dict[str, tuple[int, int, int, int]]]:
    img = np.full((H, W, 3), (40, 90, 30), np.uint8)  # green solder mask
    rng = np.random.default_rng(3)
    for _ in range(60):  # traces
        x, y = int(rng.integers(0, W)), int(rng.integers(0, H))
        cv2.line(img, (x, y), (x + int(rng.integers(-300, 300)), y), (60, 130, 50), 6)
    parts: dict[str, tuple[int, int, int, int]] = {}

    def label(text: str, x: int, y: int) -> None:
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (235, 235, 235), 2, cv2.LINE_AA)

    for i, (x, y) in enumerate([(180, 200), (180, 330), (180, 460), (180, 590)], 1):  # resistors
        cv2.rectangle(img, (x, y), (x + 150, y + 44), (90, 160, 200), -1)
        for k, c in enumerate([(19, 69, 139), (0, 0, 0), (0, 0, 255)]):
            cv2.rectangle(img, (x + 30 + k * 30, y), (x + 42 + k * 30, y + 44), c, -1)
        parts[f"R{i}"] = (x, y, x + 150, y + 44)
        label(f"R{i}", x + 160, y + 32)
    for i, (x, y) in enumerate([(620, 220), (760, 220), (900, 220), (1040, 220)], 1):  # LED pads (empty)
        cv2.circle(img, (x, y), 34, (200, 200, 200), 3)
        cv2.circle(img, (x - 14, y), 7, (180, 180, 180), -1)
        cv2.circle(img, (x + 14, y), 7, (180, 180, 180), -1)
        parts[f"D{i}"] = (x - 36, y - 36, x + 36, y + 36)
        label(f"D{i}", x - 20, y + 75)
    cv2.rectangle(img, (700, 480), (1000, 640), (25, 25, 25), -1)  # IC
    for k in range(8):
        cv2.rectangle(img, (715 + k * 36, 460), (735 + k * 36, 480), (190, 190, 190), -1)
        cv2.rectangle(img, (715 + k * 36, 640), (735 + k * 36, 660), (190, 190, 190), -1)
    cv2.circle(img, (720, 500), 8, (120, 120, 120), -1)
    parts["U1"] = (700, 460, 1000, 660)
    label("U1", 830, 700)
    cv2.circle(img, (1350, 650), 70, (40, 40, 40), -1)  # electrolytic cap footprint
    cv2.circle(img, (1350, 650), 70, (220, 220, 220), 3)
    parts["C1"] = (1280, 580, 1420, 720)
    label("C1", 1330, 760)
    return img, parts


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


QUESTIONS = [("D3", "LED 세 번째 자리 D3는 어디야?"), ("R2", "R2 저항 어디 있어?"),
             ("U1", "IC는 어디 꽂아?"), ("C1", "전해 콘덴서 C1 자리 짚어줘.")]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="haiku,sonnet")
    args = ap.parse_args()
    img, parts = board()
    jpeg = encode_jpeg(img, 1280)
    sent = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    size = (sent.shape[1], sent.shape[0])
    out = ROOT / "data" / "bench"
    out.mkdir(parents=True, exist_ok=True)
    for model in args.models.split(","):
        pointer = Pointer(model, cwd=out)
        shown = img.copy()
        hits, ious = 0, []
        for name, q in QUESTIONS:
            marks, secs = pointer.locate(jpeg, size, q)
            truth = parts[name]
            cv2.rectangle(shown, truth[:2], truth[2:], (0, 255, 0), 2)
            if not marks:
                print(f"[{model}] {name}: 표시 없음 ({secs:.1f}s)")
                continue
            box = marks[0].pixels(W, H)
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            inside = truth[0] <= cx <= truth[2] and truth[1] <= cy <= truth[3]
            score = iou(box, truth)
            hits += inside
            ious.append(score)
            cv2.rectangle(shown, box[:2], box[2:], (0, 0, 255), 3)
            cv2.putText(shown, name, (box[0], box[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            print(f"[{model}] {name}: 중심 적중 {'O' if inside else 'X'}, IoU {score:.2f}, {secs:.1f}s, "
                  f"라벨 {marks[0].label!r}")
        pointer.stop()
        cv2.imwrite(str(out / f"pointing_{model}.png"), shown)
        print(f"[{model}] 적중 {hits}/{len(QUESTIONS)}, 평균 IoU {np.mean(ious) if ious else 0:.2f}\n")


if __name__ == "__main__":
    main()
