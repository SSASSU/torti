r"""Self-zoom check on a saved desk photo: does the voice model ask for a closer look, does the
pointer find the spot, and what does the model say about the crop?

    .venv\Scripts\python spike\zoom_test.py desk.jpg "보드에 적힌 글씨 읽어줘" [--out folder]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from torti.camera import encode_jpeg, jpeg_size, read_image  # noqa: E402
from torti.closeup import Zoom, for_model  # noqa: E402
from torti.claude_cli import ClaudeCli  # noqa: E402
from torti.paths import workspace_dir  # noqa: E402
from torti.prompts import build_system_prompt  # noqa: E402
from torti.visual import Pointer, TagFilter  # noqa: E402


def ask(cli: ClaudeCli, text: str, jpeg: bytes | None) -> tuple[str, TagFilter, float]:
    t = time.perf_counter()
    tags, out = TagFilter(), []
    for kind, val in cli.ask(text, jpeg):
        if kind == "text":
            out.append(tags.feed(val))
    out.append(tags.flush())
    return "".join(out).strip(), tags, time.perf_counter() - t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("questions", nargs="+")
    ap.add_argument("--out")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    full = read_image(args.image)
    h, w = full.shape[:2]
    cli = ClaudeCli(build_system_prompt(None, f"Elgato Facecam MK.2, {w}x{h}"), model="haiku", effort="low",
                    cwd=workspace_dir())
    cli.start()
    pointer = Pointer("sonnet", cwd=workspace_dir())
    for i, q in enumerate(args.questions):
        zoom = Zoom()
        jpeg = encode_jpeg(full, 1280)
        answer, tags, secs = ask(cli, q, jpeg)
        print(f"\nQ: {q}\n  1st ({secs:.1f}s): {answer!r}  zoom request: {tags.zoom_target!r}")
        if tags.zoom_target is None:
            continue
        marks, psecs = pointer.locate(jpeg, jpeg_size(jpeg), f"{tags.zoom_target or q} 위치")
        print(f"  pointer ({psecs:.1f}s): {[(m.label, m.box) for m in marks]}")
        if not marks:
            continue
        b = [m.box for m in marks]
        zoom.to_box((min(x[0] for x in b) / 1000, min(x[1] for x in b) / 1000,
                     max(x[2] for x in b) / 1000, max(x[3] for x in b) / 1000))
        crop = zoom.crop(full)
        if args.out:
            Path(args.out).mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(Path(args.out) / f"crop_{i}.jpg"), crop)
        note = f"[{tags.zoom_target}을(를) {zoom.factor:.1f}배 확대한 사진이다. 이 사진으로 답하고 확대 태그는 다시 쓰지 않는다]\n{q}"
        answer, tags2, secs = ask(cli, note, for_model(crop))
        print(f"  zoom {zoom.factor:.1f}x crop {crop.shape[1]}x{crop.shape[0]} -> 2nd ({secs:.1f}s): {answer!r}")
    cli.stop()
    pointer.stop()


if __name__ == "__main__":
    main()
