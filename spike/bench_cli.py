"""M0: measure Claude CLI latency for the voice loop.

Cases: cold start, warm turn, inline image, interrupt + recovery, image via Read tool, model comparison.
Run:  .venv\\Scripts\\python spike\\bench_cli.py [--camera 0] [--models haiku,sonnet]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from torti.camera import Camera, encode_jpeg  # noqa: E402
from torti.claude_cli import ClaudeCli, check_cli  # noqa: E402
from torti.prompts import SYSTEM_PROMPT  # noqa: E402

WORKSPACE = ROOT / "data" / "workspace"
OUT = ROOT / "data" / "bench"


def run_turn(cli: ClaudeCli, label: str, text: str, image: bytes | None = None, t0: float | None = None,
             stop_after_first: bool = False) -> dict:
    t0 = t0 or time.perf_counter()
    first = None
    res = None
    gen = cli.ask(text, image)
    for kind, val in gen:
        if kind == "text" and first is None:
            first = time.perf_counter()
            if stop_after_first:
                gen.close()
                break
        elif kind == "result":
            res = val
    end = time.perf_counter()
    row = {
        "case": label, "model": cli.model_resolved,
        "ttft_ms": round((first - t0) * 1000) if first else None,
        "total_ms": round((end - t0) * 1000),
    }
    if res is not None:
        u = res.usage
        row.update({
            "ok": res.ok, "api_ms": res.duration_api_ms,
            "in": u.get("input_tokens"), "cache_w": u.get("cache_creation_input_tokens"),
            "cache_r": u.get("cache_read_input_tokens"), "out": u.get("output_tokens"),
            "answer": res.text if res.ok else res.error,
        })
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--models", default="haiku,sonnet")
    ap.add_argument("--long-edge", type=int, default=1280)
    args = ap.parse_args()

    info = check_cli()
    print("cli:", {k: v for k, v in info.items() if k in ("ok", "version", "logged_in", "auth_method", "plan", "error")})
    if not info["ok"]:
        sys.exit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    cam = Camera(index=args.camera)
    image = None
    if cam.open():
        time.sleep(1.0)  # let auto exposure settle
        frame = cam.snapshot()
        image = encode_jpeg(frame, args.long_edge)
        (OUT / "snapshot.jpg").write_bytes(image)
        (WORKSPACE / "captures").mkdir(parents=True, exist_ok=True)
        (WORKSPACE / "captures" / "bench.jpg").write_bytes(image)
        print(f"camera: {frame.shape[1]}x{frame.shape[0]} -> jpeg {len(image) // 1024} KB")
        cam.close()
    else:
        print("camera: not available, image cases skipped")

    rows = []
    q_text = "인두 온도는 무연납 기준으로 몇 도가 적당해?"
    q_img = "지금 책상 위에 뭐가 보여? 작업물 상태를 짧게 말해줘."
    for model in args.models.split(","):
        cli = ClaudeCli(SYSTEM_PROMPT, model=model, effort="low", cwd=WORKSPACE)
        t0 = time.perf_counter()
        cli.start()
        rows.append(run_turn(cli, "cold_text", q_text, t0=t0))
        init = cli.init_info
        print("init:", {"tools": init.get("tools"), "mcp": init.get("mcp_servers"),
                        "skills": len(init.get("skills") or []), "memory_paths": init.get("memory_paths"),
                        "cwd": init.get("cwd")})
        rows.append(run_turn(cli, "warm_text", "그럼 유연납은?"))
        if image:
            rows.append(run_turn(cli, "warm_image_inline", q_img, image))
        rows.append(run_turn(cli, "interrupt", "납땜의 원리를 아주 자세히 설명해줘.", stop_after_first=True))
        t = time.perf_counter()
        idle = cli._idle.wait(timeout=20)
        print(f"interrupt settle: {round((time.perf_counter() - t) * 1000)} ms, idle={idle}, alive={cli.alive()}")
        rows.append(run_turn(cli, "after_interrupt", "방금 질문은 취소. 플럭스는 왜 써? 한 문장."))
        cli.stop()

    if image:
        cli = ClaudeCli(SYSTEM_PROMPT, model=args.models.split(",")[0], effort="low", cwd=WORKSPACE, tools="Read")
        t0 = time.perf_counter()
        cli.start()
        rows.append(run_turn(cli, "cold_image_read_tool",
                             f"{WORKSPACE / 'captures' / 'bench.jpg'} 사진을 읽고 답해줘. {q_img}", t0=t0))
        cli.stop()

    (OUT / "bench_cli.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    print("\nsummary (ms):")
    for r in rows:
        print(f"  {r['case']:<22} {str(r['model']):<20} ttft={r['ttft_ms']}  total={r['total_ms']}  "
              f"in={r.get('in')} cw={r.get('cache_w')} cr={r.get('cache_r')} out={r.get('out')}")


if __name__ == "__main__":
    main()
