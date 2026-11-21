"""Worker session: does work in the project folder the way Claude Code does - edits files, runs
build/test/upload commands - in the background while the voice conversation goes on.

The voice model hands work off with ``<작업 지시="..."/>`` (see prompts.WORK_RULES). The worker

* saves the folder's current state first (a commit, only if something was uncommitted), so a task
  can be undone on its own,
* runs a resident headless Claude Code session in the project folder (Sonnet by default) that can
  read, search the web, edit files (acceptEdits, inside the folder only) and run *allow-listed*
  commands; any other command is denied automatically and the summary says what was not run,
* reports each step (file edited, command run, command denied) as events for the screen,
* commits the result as one commit ``Torti 작업: <지시>`` and pushes it when the project has a
  GitHub remote (the same sync the rest of Torti uses),
* can be stopped ("작업 멈춰"; whatever was changed is still committed so it can be undone) and
  undone ("되돌려줘": ``git revert`` of that commit, pushed too).

The session keeps its context between tasks ("아까 그거 B 버튼도"), and as an ordinary Claude Code
session of the project folder it also shows up in Claude Code's own session list.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .claude_cli import ClaudeCli
from .project import GitResult, Project, _run

WORKER_SYSTEM = """\
너는 '토르티'의 작업자다. 사용자는 손으로 작업하면서 음성으로 지시했고 화면을 거의 보지 않는다.
- 지시받은 일을 이 작업 폴더에서 끝까지 해낸다. 필요한 파일은 직접 읽고, 고치고, 허용된 명령으로 빌드나 테스트를 돌려 확인한다.
- git commit, push, reset, 브랜치 조작은 하지 않는다. 기록과 업로드는 토르티가 한다.
- 허용되지 않아 거부된 명령은 다시 시도하지 말고, 끝난 뒤 요약에 사용자가 직접 실행할 명령으로 적는다.
- 지시가 모호하면 가장 그럴듯한 쪽으로 하고 그 가정을 요약에 적는다. 위험하거나 되돌리기 어려운 일은 하지 않는다.
- 끝나면 한국어 두세 문장으로만 요약한다: 무엇을 바꿨는지(파일 이름), 빌드나 테스트 결과, 사용자가 해야 할 일. 이 요약은 소리 내어 읽힌다. 마크다운, 코드, 경로 나열은 쓰지 않는다."""

READ = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "Edit", "Write", "MultiEdit", "TodoWrite"]
DEFAULT_COMMANDS = [  # command prefixes the worker may run without asking (builds, tests, uploads, read-only git)
    "pio", "platformio", "arduino-cli", "idf.py", "make", "cmake", "ninja", "west",
    "npm run", "npm test", "npx", "pnpm", "yarn", "python", "py", "pytest", "uv run",
    "cargo build", "cargo test", "cargo run", "go build", "go test", "dotnet build", "dotnet test",
    "git status", "git diff", "git log", "git show", "ls", "dir", "cat", "head", "tail", "find", "grep",
]


@dataclass
class Task:
    instruction: str
    started: float = field(default_factory=time.time)
    steps: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    summary: str = ""
    ok: bool = False
    stopped: bool = False
    commit: str | None = None
    pushed: bool = False
    git_message: str = ""
    finished: float | None = None


def describe(call: dict) -> tuple[str, str]:
    """(kind, short text) for a tool call: what the screen shows as one step."""
    name, inp = call.get("name", ""), call.get("input") or {}
    if name in ("Edit", "Write", "MultiEdit"):
        return "edit", f"{'새 파일' if name == 'Write' else '수정'} {Path(str(inp.get('file_path', ''))).name}"
    if name == "Bash":
        return "run", f"$ {str(inp.get('command', '')).strip()[:120]}"
    if name in ("Read", "Glob", "Grep"):
        target = inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
        return "read", f"읽기 {Path(str(target)).name or target}"
    if name in ("WebSearch", "WebFetch"):
        return "web", f"검색 {str(inp.get('query') or inp.get('url') or '')[:80]}"
    return "other", name


class Worker:
    """One project's worker. ``emit(kind, data)`` reports ``work`` events; never blocks the caller."""

    def __init__(self, project: Project, emit: Callable[[str, dict], None], model: str = "sonnet",
                 commands: list[str] | None = None, push: bool = True, resume: str | None = None) -> None:
        self.project = project
        self.emit = emit
        self.model = model
        self.commands = list(commands or DEFAULT_COMMANDS)
        self.push = push
        self.task: Task | None = None  # running or last finished
        self.last_commit: str | None = None  # undo target
        self.unreported: Task | None = None  # finished, not yet told to the voice conversation
        self.queue: list[str] = []  # orders given while busy, run one after another
        self._cli: ClaudeCli | None = None
        self.session_id = resume  # continued from last time this project was open
        self._lock = threading.Lock()
        self._cancel = threading.Event()

    # ----------------------------------------------------------------- state
    @property
    def busy(self) -> bool:
        return self.task is not None and self.task.finished is None

    def status_note(self) -> str | None:
        """One line for the voice model about the worker (running, or a result it hasn't heard)."""
        t = self.task
        if t and t.finished is None:
            last = t.steps[-1] if t.steps else "시작함"
            waiting = f", 대기 {len(self.queue)}건" if self.queue else ""
            return f"[작업자: '{t.instruction[:60]}' 하는 중, {len(t.steps)}단계째, 마지막: {last}{waiting}]"
        if self.unreported:
            u, self.unreported = self.unreported, None
            return f"[작업자 결과: {u.summary or ('중단됨' if u.stopped else '끝남')}]"
        return None

    def _cli_args(self) -> ClaudeCli:
        allowed = READ + [f"Bash({c}:*)" for c in self.commands]
        # Full path: with a Windows short name (e.g. LONGNA~1) Claude Code sees the files as outside the
        # folder and refuses the edits. No .pyc files from the commands it runs, so they aren't committed.
        return ClaudeCli(WORKER_SYSTEM, model=self.model, effort="medium", cwd=self.project.root.resolve(),
                         tools=",".join(READ + ["Bash"]), allowed=allowed, append_system=True,
                         extra_args=["--permission-mode", "acceptEdits"], env={"PYTHONDONTWRITEBYTECODE": "1"})

    # ---------------------------------------------------------------- control
    def start(self, instruction: str) -> str:
        """Begin a task in the background: "started", or "queued" behind the running one."""
        with self._lock:
            if self.busy:
                self.queue.append(instruction.strip())
                self.emit("work", {"phase": "queued", "instruction": instruction.strip(), "waiting": len(self.queue)})
                return "queued"
            self.task = Task(instruction.strip())
            self._cancel.clear()
        threading.Thread(target=self._run, args=(self.task,), daemon=True, name="worker").start()
        return "started"

    def stop(self) -> bool:
        """Stop the running task and drop the waiting ones."""
        if not self.busy:
            return False
        self.queue.clear()
        self._cancel.set()
        return True

    def undo(self) -> GitResult:
        """Revert the last task's commit (and push the revert)."""
        if self.busy:
            return GitResult(False, "작업 중에는 되돌릴 수 없어요")
        if not self.last_commit:
            return GitResult(False, "되돌릴 작업이 없어요")
        res = _run(["git", "revert", "--no-edit", self.last_commit], cwd=self.project.root)
        if not res.ok:
            _run(["git", "revert", "--abort"], cwd=self.project.root)
            return res
        undone, self.last_commit = self.last_commit, None
        pushed = self._push()
        self.emit("work", {"phase": "undone", "commit": undone[:8], "pushed": pushed})
        return GitResult(True, "되돌렸어요" + (", GitHub에도 올렸어요" if pushed else ""))

    def close(self) -> None:
        self._cancel.set()
        if self._cli:
            self._cli.stop()
            self._cli = None

    # ------------------------------------------------------------------- run
    def _git(self, *args: str) -> GitResult:
        return _run(["git", *args], cwd=self.project.root)

    def _push(self) -> bool:
        if not (self.push and self.project.has_remote()):
            return False
        return self._git("push", "-u", "origin", "HEAD").ok

    def _checkpoint(self) -> str | None:
        """Commit uncommitted work first, so the task's own commit holds only the task. Returns HEAD."""
        if not self.project.is_repo():
            return None
        self._git("add", "-A")
        if not self._git("diff", "--cached", "--quiet").ok:
            self._git("commit", "-m", "Torti: 작업 전 상태 저장")
        head = self._git("rev-parse", "HEAD")
        return head.message.strip() if head.ok else None

    def _run(self, task: Task) -> None:
        self.emit("work", {"phase": "start", "instruction": task.instruction})
        base = self._checkpoint()
        result = None
        try:
            if self._cli is None:
                self._cli = self._cli_args()
                self._cli.session_id = self.session_id
                self._cli.start(resume=self.session_id)
            for kind, val in self._cli.ask(task.instruction, timeout=1800, cancel=self._cancel):
                if kind == "tool_call":
                    step_kind, text = describe(val)
                    task.steps.append(text)
                    self.emit("work", {"phase": "step", "kind": step_kind, "text": text, "n": len(task.steps)})
                elif kind == "tool_result" and val["is_error"] and ("denied" in val["text"].lower()
                                                                     or "permission" in val["text"].lower()):
                    cmd = task.steps[-1] if task.steps else ""
                    task.denied.append(cmd)
                    self.emit("work", {"phase": "denied", "text": cmd})
                elif kind == "result":
                    result = val
        except Exception as e:  # noqa: BLE001 - report, keep the app alive
            task.summary = f"작업자 오류: {e}"
        if self._cli:
            self.session_id = self._cli.session_id or self.session_id
        task.stopped = self._cancel.is_set()
        if result is not None:
            task.ok = bool(result.ok) and not task.stopped
            task.summary = (result.text or "").strip() if result.ok else f"작업자 오류: {result.error}"
        if task.stopped and not task.summary:
            task.summary = "작업을 중간에 멈췄어요."
        self._finish(task, base)

    def _finish(self, task: Task, base: str | None) -> None:
        if self.project.is_repo():
            self._git("add", "-A")
            if not self._git("diff", "--cached", "--quiet").ok:
                title = task.instruction.replace("\n", " ")[:60]
                msg = f"Torti 작업{' (중단)' if task.stopped else ''}: {title}\n\n{task.summary[:1500]}"
                if self._git("commit", "-m", msg).ok:
                    head = self._git("rev-parse", "HEAD")
                    task.commit = self.last_commit = head.message.strip() if head.ok else None
            if base and task.commit:
                diff = self._git("diff", "--name-only", base, task.commit)
                task.files = [f for f in diff.message.splitlines() if f.strip()] if diff.ok else []
            if task.commit:
                task.pushed = self._push()
        task.finished = time.time()
        self.unreported = task
        self.emit("work", {"phase": "done", "ok": task.ok, "stopped": task.stopped, "summary": task.summary,
                           "files": task.files, "denied": task.denied, "commit": (task.commit or "")[:8],
                           "pushed": task.pushed, "seconds": round(task.finished - task.started)})
        if self.queue and not task.stopped:
            self.start(self.queue.pop(0))
