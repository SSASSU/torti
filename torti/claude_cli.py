"""Resident Claude Code CLI client: headless, stream-json in and out.

Uses the logged-in Claude subscription. API-key variables are stripped from the child
environment so the CLI never falls back to pay-per-token API billing (NFR-04b).
"""

from __future__ import annotations

import base64
import collections
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

BILLING_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def cli_env() -> tuple[dict[str, str], list[str]]:
    """Return a copy of the environment without billing variables, and the names removed."""
    env = dict(os.environ)
    removed = [k for k in BILLING_ENV_VARS if k in env]
    for k in removed:
        del env[k]
    return env, removed


def find_cli(exe: str = "claude") -> str | None:
    return shutil.which(exe)


def check_cli(exe: str = "claude") -> dict:
    """Version and login state (FR-30a). Never raises; problems are reported in ``error``."""
    path = find_cli(exe)
    if not path:
        return {"ok": False, "error": "Claude CLI를 찾을 수 없습니다"}
    env, _ = cli_env()
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        ver = subprocess.run([path, "--version"], capture_output=True, env=env, timeout=30, creationflags=flags)
        auth = subprocess.run([path, "auth", "status"], capture_output=True, env=env, timeout=30, creationflags=flags)
        status = json.loads(auth.stdout.decode("utf-8", "replace") or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return {"ok": False, "path": path, "error": f"CLI 확인 실패: {e}"}
    info = {
        "path": path,
        "version": ver.stdout.decode("utf-8", "replace").strip(),
        "logged_in": bool(status.get("loggedIn")),
        "auth_method": status.get("authMethod"),
        "plan": status.get("subscriptionType"),
        "login_expires_at": status.get("loginExpiresAt"),
    }
    if not info["logged_in"]:
        return {**info, "ok": False, "error": "Claude CLI에 로그인되어 있지 않습니다"}
    if info["auth_method"] != "claude.ai":
        return {**info, "ok": False, "error": f"구독 로그인이 아닙니다 (authMethod={info['auth_method']})"}
    return {**info, "ok": True}


@dataclass
class TurnResult:
    text: str = ""
    ok: bool = True
    error: str | None = None
    subtype: str | None = None
    session_id: str | None = None
    duration_ms: int | None = None
    duration_api_ms: int | None = None
    usage: dict = field(default_factory=dict)
    cost_usd: float | None = None  # notional for subscription use; useful to compare settings
    rate_limit: dict | None = None


class ClaudeCli:
    """One long-lived ``claude -p --input-format stream-json`` process; one turn at a time."""

    def __init__(
        self,
        system_prompt: str,
        model: str = "haiku",
        effort: str | None = "low",
        cwd: str | Path | None = None,
        tools: str = "",
        exe: str = "claude",
        extra_args: list[str] | None = None,
    ) -> None:
        self.exe = find_cli(exe) or exe
        self.system_prompt = system_prompt
        self.model = model
        self.effort = effort
        self.cwd = str(cwd) if cwd else None
        self.tools = tools
        self.extra_args = list(extra_args or [])
        self.session_id: str | None = None
        self.model_resolved: str | None = None
        self.init_info: dict = {}
        self.removed_env: list[str] = []
        self._proc: subprocess.Popen | None = None
        self._events: queue.Queue = queue.Queue()
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=40)
        self._idle = threading.Event()
        self._idle.set()
        self._req = 0
        self.last_rate_limit: dict | None = None

    # ---------------------------------------------------------------- process
    def command(self, resume: str | None = None) -> list[str]:
        cmd = [
            self.exe, "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose",
            "--include-partial-messages",
            "--model", self.model,
            "--tools", self.tools,
            "--strict-mcp-config",  # no MCP servers: faster start, nothing outside the app's scope
            "--disable-slash-commands",
            "--permission-prompts", "none",  # unattended: anything that would prompt is denied
            "--system-prompt", self.system_prompt,
        ]
        if self.tools:
            cmd += ["--allowedTools", self.tools]
        if self.effort:
            cmd += ["--effort", self.effort]
        if resume:
            cmd += ["--resume", resume]
        return cmd + self.extra_args

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, resume: str | None = None) -> None:
        if self.alive():
            return
        env, self.removed_env = cli_env()
        if self.cwd:
            Path(self.cwd).mkdir(parents=True, exist_ok=True)
        self._events = queue.Queue()
        self._idle.set()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._proc = subprocess.Popen(
            self.command(resume),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=self.cwd, env=env, creationflags=flags,
        )
        threading.Thread(target=self._read_stdout, args=(self._proc, self._events), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(self._proc,), daemon=True).start()

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()
        self._idle.set()

    def new_conversation(self) -> None:
        """Drop the session (VC-03) and pre-start a fresh process."""
        self.stop()
        self.session_id = None
        self.start()

    def _read_stdout(self, proc: subprocess.Popen, q: queue.Queue) -> None:
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                q.put(json.loads(line))
            except json.JSONDecodeError:
                q.put({"type": "_raw", "line": line})
        q.put({"type": "_eof", "returncode": proc.wait()})

    def _read_stderr(self, proc: subprocess.Popen) -> None:
        for raw in proc.stderr:
            self._stderr_tail.append(raw.decode("utf-8", "replace").rstrip())

    def _send(self, obj: dict) -> bool:
        if not self.alive():
            return False
        try:
            self._proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
            return True
        except OSError:
            return False

    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_tail)

    # ------------------------------------------------------------------ turns
    def ask(self, text: str, image_jpeg: bytes | None = None, timeout: float = 120.0,
            cancel: threading.Event | None = None) -> Iterator[tuple[str, object]]:
        """Send one user turn. Yields ``("text", delta)`` while streaming, then ``("result", TurnResult)``.

        Setting ``cancel`` or closing the generator early (barge-in) interrupts the turn; the
        next ``ask`` waits for the CLI to settle, or restarts it on the same session if it doesn't.
        """
        if not self._idle.wait(timeout=10):
            self.stop()
        if not self.alive():
            self.start(resume=self.session_id)

        content: list[dict] = []
        if image_jpeg:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(image_jpeg).decode("ascii")}})
        content.append({"type": "text", "text": text})
        if not self._send({"type": "user", "message": {"role": "user", "content": content}}):
            yield "result", TurnResult(ok=False, error="CLI 프로세스에 질문을 보내지 못했습니다")
            return

        self._idle.clear()
        finished = False
        parts: list[str] = []
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    ev = self._events.get(timeout=0.1)
                except queue.Empty:
                    if cancel is not None and cancel.is_set():
                        return
                    if time.monotonic() > deadline:
                        yield "result", TurnResult(ok=False, text="".join(parts), error="CLI 응답 시간 초과")
                        return
                    continue
                kind = ev.get("type")
                if kind == "system" and ev.get("subtype") == "init":
                    self.init_info = ev
                    self.session_id = ev.get("session_id") or self.session_id
                    self.model_resolved = ev.get("model")
                elif kind == "stream_event":
                    e = ev.get("event") or {}
                    delta = e.get("delta") or {}
                    if e.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                        parts.append(delta.get("text", ""))
                        yield "text", delta.get("text", "")
                elif kind == "rate_limit_event":
                    self.last_rate_limit = ev.get("rate_limit_info")
                elif kind == "result":
                    finished = True
                    self._idle.set()
                    self.session_id = ev.get("session_id") or self.session_id
                    is_error = bool(ev.get("is_error")) or ev.get("subtype") != "success"
                    yield "result", TurnResult(
                        text=ev.get("result") if isinstance(ev.get("result"), str) else "".join(parts),
                        ok=not is_error,
                        error=(ev.get("result") or ev.get("subtype")) if is_error else None,
                        subtype=ev.get("subtype"),
                        session_id=self.session_id,
                        duration_ms=ev.get("duration_ms"),
                        duration_api_ms=ev.get("duration_api_ms"),
                        usage=ev.get("usage") or {},
                        cost_usd=ev.get("total_cost_usd"),
                        rate_limit=self.last_rate_limit,
                    )
                    return
                elif kind == "_eof":
                    finished = True
                    self._idle.set()
                    yield "result", TurnResult(
                        ok=False, text="".join(parts),
                        error=f"CLI가 종료됨 (code {ev.get('returncode')}): {self.stderr_tail()[-300:]}")
                    return
        finally:
            if not finished:
                self._abort_turn()

    def interrupt(self) -> bool:
        self._req += 1
        return self._send({"type": "control_request", "request_id": f"torti-{self._req}",
                           "request": {"subtype": "interrupt"}})

    def _abort_turn(self) -> None:
        """Interrupt the running turn and swallow its remaining events in the background."""
        self.interrupt()
        q = self._events

        def drain() -> None:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    ev = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if ev.get("type") in ("result", "_eof"):
                    self._idle.set()
                    return
            self.stop()  # could not resync; the next ask restarts on the same session

        threading.Thread(target=drain, daemon=True).start()
