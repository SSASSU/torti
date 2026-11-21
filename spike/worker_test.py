r"""Worker end to end on a throwaway repo with a local bare "GitHub": edit + run + commit + push,
a command outside the allow list, then undo.

    .venv\Scripts\python spike\worker_test.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from torti.project import Project  # noqa: E402
from torti.worker import Worker  # noqa: E402


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def wait(w: Worker, limit: float = 600) -> None:
    t = time.monotonic()
    while w.busy and time.monotonic() - t < limit:
        time.sleep(0.5)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    base = Path(tempfile.mkdtemp(prefix="torti-worker-"))
    remote, repo = base / "remote.git", base / "stick"
    subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True)
    repo.mkdir()
    git("init", "-b", "main", cwd=repo)
    git("config", "user.email", "torti@example.invalid", cwd=repo)
    git("config", "user.name", "Torti test", cwd=repo)
    (repo / "buttons.py").write_text('"""Arcade stick button map."""\n\nBUTTONS = {"A": 2, "B": 3}\n', encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-m", "start", cwd=repo)
    git("remote", "add", "origin", str(remote), cwd=repo)
    git("push", "-u", "origin", "main", cwd=repo)

    events: list[dict] = []

    def emit(kind: str, data: dict) -> None:
        events.append(data)
        if data.get("phase") in ("start", "step", "denied", "done", "undone"):
            print(f"  [{data['phase']}] {data.get('text') or data.get('instruction') or data.get('summary') or data}")

    w = Worker(Project(repo), emit, model="sonnet", commands=["python"])
    t = time.monotonic()
    print("TASK 1: edit + run")
    w.start("buttons.py의 BUTTONS에 C 버튼을 4번 핀으로 추가하고, python으로 buttons.py를 import해서 C가 4인지 확인해줘.")
    wait(w)
    t1 = w.task
    print(f"  -> {time.monotonic() - t:.0f}s ok={t1.ok} commit={t1.commit and t1.commit[:8]} pushed={t1.pushed} files={t1.files}")
    print("  file now:", (repo / "buttons.py").read_text(encoding="utf-8").strip().splitlines()[-1])
    print("  remote log:", git("--git-dir", str(remote), "log", "--all", "--oneline", "-3", cwd=base).splitlines())

    print("TASK 2: command outside the allow list")
    w.start("curl로 https://example.com 을 받아서 첫 줄만 알려줘. 다른 방법은 쓰지 마.")
    wait(w)
    print(f"  -> denied={w.task.denied} summary={w.task.summary[:160]!r}")

    print("UNDO task 1")
    w.last_commit = t1.commit
    res = w.undo()
    print("  ->", res.ok, res.message, "| file now:", (repo / "buttons.py").read_text(encoding="utf-8").strip().splitlines()[-1])
    print("  remote log:", git("--git-dir", str(remote), "log", "--all", "--oneline", "-4", cwd=base).splitlines())
    print("  worker session:", w.session_id)
    w.close()


if __name__ == "__main__":
    main()
