"""Torti engine: one conversation that voice, typed chat, camera, reference images and the work
project all feed into. UI-agnostic; everything that happens is reported with ``emit(kind, data)``
from worker threads (the console prints it, the GUI turns it into Qt signals).

Events: log, state, cli, project, brief, session, heard, delta, say, turn, command, visual,
reference, sync, ready, error, fatal.
"""

from __future__ import annotations

import os
import queue
import re
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .audio import Recorder, find_device
from .brief import Brief, analyze, load_cached
from .camera import Camera, encode_jpeg, jpeg_size, read_image
from .closeup import Inspector, Zoom, average_still, for_model, needs_close_look
from .claude_cli import BILLING_ENV_VARS, ClaudeCli, check_cli
from .config import Settings
from .history import History
from .intent import match_command, match_note, match_zoom, needs_image
from .paths import data_dir, history_dir, workspace_dir
from .project import Project, gh_available, load_state, save_state
from .prompts import build_system_prompt
from .sessions import SessionInfo, default_projects_dir, find_session, recent_exchanges, sessions_for
from .sounds import Earcons
from .speech_text import SentenceSplitter, speakable, times_ko
from .stt import DEFAULT_PROMPT, WhisperStt
from . import tts_neural
from .tts import SapiTts
from .visual import Pointer, TagFilter, wants_pointing
from .worker import Worker

LOADING, IDLE, LISTENING, TRANSCRIBING, THINKING, SPEAKING = (
    "LOADING", "IDLE", "LISTENING", "TRANSCRIBING", "THINKING", "SPEAKING")
HOLD_S = 0.4  # held longer than this = push-to-talk; shorter = tap (VAD finds the end)
RESUME_DAYS = 3  # a project's conversation older than this starts fresh (the briefing carries over)
NOTICE = "AI 답변은 참고용이에요. 수치는 꼭 계측기나 데이터시트로 확인해 주세요."
# Always on: read the work folder (code, notes, datasheets) and look things up on the web. Nothing is
# changed. The model only uses them when a question needs it, and Torti says so out loud first.
READ_TOOLS = "Read,Glob,Grep,WebSearch,WebFetch"
EDIT_TOOLS = "Edit,Write"
TOOL_FILLERS = {"WebSearch": "찾아볼게요.", "WebFetch": "찾아볼게요.", "Read": "파일 확인해 볼게요.",
                "Glob": "파일 확인해 볼게요.", "Grep": "파일 확인해 볼게요."}

Emit = Callable[[str, dict], None]


def ms(a: float | None, b: float | None) -> int | None:
    return None if a is None or b is None else round((b - a) * 1000)


class Engine:
    def __init__(self, settings: Settings, emit: Emit | None = None) -> None:
        self.s = settings
        self.emit: Emit = emit or (lambda kind, data: None)
        self.state = LOADING
        self.triggers: queue.Queue[tuple[str, float]] = queue.Queue()
        self.cancel = threading.Event()
        self.stop_listen = threading.Event()
        self.holding = threading.Event()  # trigger key/pedal/button is physically down
        self.key_down = False
        self.down_at = 0.0
        self.turn: threading.Thread | None = None
        self.last_answer = ""
        self.project: Project | None = None
        self.brief: Brief | None = None
        self.camera: Camera | None = None
        self.cli: ClaudeCli | None = None
        self.pointer: Pointer | None = None
        self.inspector: Inspector | None = None  # close-ups (closeup.py), fast model
        self.worker: Worker | None = None  # does file edits / builds in the project folder (worker.py)
        self._say_when_idle: list[str] = []  # worker results that arrive while a turn is running
        self.reference: dict | None = None  # {"path", "jpeg", "size"} shown instead of the camera
        self.zoom = Zoom()  # what part of the camera frame is shown, sent and pointed at
        self.last_marks: tuple[float, list[tuple[float, float, float, float]]] | None = None  # full-frame boxes
        self.last_photo_at = 0.0  # when the camera photo was last sent (short follow-ups get one too)
        self.session: SessionInfo | None = None  # a resumed Claude Code session, if any
        self.sync_lock = threading.Lock()
        self._running = False
        self._hooked = False

    def log(self, text: str) -> None:
        self.emit("log", {"text": text})

    def set_state(self, state: str) -> None:
        self.state = state
        self.emit("state", {"state": state})
        if state == IDLE and self._say_when_idle:
            for text in self._say_when_idle:
                self.tts.say(text)
            self._say_when_idle.clear()

    @property
    def cwd(self) -> Path:
        return self.project.root if self.project else workspace_dir()

    # ------------------------------------------------------------------ setup
    def load(self, open_camera: bool | None = None) -> None:
        """Heavy initialization (CLI check, audio, STT, camera). Blocking: run it off the UI thread.

        ``open_camera``: None opens it only when photos may be sent; the GUI passes True for its
        preview, and the ``image`` setting alone then decides whether photos are sent.
        """
        info = check_cli()
        self.emit("cli", info)
        if not info["ok"]:
            raise RuntimeError(f"Claude CLI 문제: {info['error']}")
        self.log(f"Claude CLI {info['version']} / {info['plan']} 구독 로그인")
        found = [k for k in BILLING_ENV_VARS if k in os.environ]
        if found:  # NFR-04b
            self.log(f"경고: {', '.join(found)} 환경변수가 있어 CLI 실행 환경에서 제거합니다 (API 과금 방지)")

        self.earcons = Earcons(find_device(self.s.speaker, "output"))
        neural = None
        if self.s.tts_engine == "chatterbox":
            if tts_neural.available():  # loads ~25 s in its own process, alongside the rest below
                neural = tts_neural.NeuralTts(find_device(self.s.speaker, "output"))
            else:
                self.log("신경망 TTS 환경(.venv-tts)이 없어 Windows 음성을 씁니다")

        t = time.perf_counter()
        self.stt = WhisperStt(self.s.stt_model, beam_size=self.s.beam)
        self.log(f"STT: {self.stt.model_name} {self.stt.device}/{self.stt.compute_type} "
                 f"(load {time.perf_counter() - t:.1f}s, warmup {self.stt.warmup():.2f}s)")

        self.rec = Recorder(find_device(self.s.mic, "input"), vad_level=self.s.vad, min_rms=self.s.min_rms)
        self.log(f"마이크: {self.rec.device_name}")

        if open_camera or (open_camera is None and self.s.image != "never"):
            # Keeps trying in the background: a camera plugged in (or replugged) later just works.
            cam = Camera(self.s.camera, on_change=self.log)
            self.camera = cam
            if not cam.open():
                self.log(f"카메라 아직 없음 ({self.s.camera or '실제 카메라'}) - 연결되면 바로 씁니다")
        self.pointer = Pointer(self.s.pointer_model, cwd=workspace_dir())
        self.inspector = Inspector(Pointer(self.s.inspect_model, cwd=workspace_dir()), self.s.long_edge)
        self.history = History(history_dir())
        self.log(f"기록: {self.history.dir}")

        if neural and neural.wait_ready():
            self.tts = neural
            self.log(f"TTS: {neural.voice_name} (모델 준비 {neural.load_s}s)")
        else:
            if neural:
                self.log(f"신경망 TTS 실패 ({neural.error}) - Windows 음성으로 대신합니다")
                neural.close()
            self.tts = SapiTts(rate=self.s.tts_rate if self.s.tts_rate is not None else 1,
                               output_hint=self.s.speaker)
            self.log(f"TTS: {self.tts.voice_name}")

    # --------------------------------------------------------------- projects
    def open_project(self, *, new: str | None = None, remote: str | None = None, github: bool = False,
                     clone: str | None = None, name: str | None = None, folder: str | Path | None = None,
                     reanalyze: bool = False) -> Project | None:
        """New work, continue from GitHub, a Torti project, or any existing folder; then talk from it."""
        if new:
            use_gh = github and gh_available()
            if github and not use_gh:
                self.log("gh CLI가 없거나 로그인되지 않아 저장소를 자동으로 만들 수 없습니다 (저장소 URL 사용)")
            proj, res = Project.create(new, remote_url=remote, github=use_gh, push_photos=self.s.push_photos)
        elif clone:
            proj, res = Project.clone(clone, push_photos=self.s.push_photos)
        elif folder:
            proj, res = Project.open_folder(Path(folder), push_photos=self.s.push_photos)
        elif name:
            proj, res = Project.open(name, push_photos=self.s.push_photos)
        else:
            self.use_project(None)
            return None
        self.log(f"작업: {proj.name} ({proj.root}) - git: {'정상' if res.ok else '문제'}")
        if not res.ok:
            self.log(f"  git 메시지: {res.message[-400:]}")
        self.emit("project", {"name": proj.name, "root": str(proj.root), "git_ok": res.ok,
                              "git_message": res.message, "has_remote": proj.has_remote(),
                              "is_repo": proj.is_repo()})
        self.use_project(proj, reanalyze=reanalyze)
        return proj

    def use_project(self, project: Project | None, reanalyze: bool = False) -> None:
        """Switch the conversation to ``project`` (or none): briefing, voice, CLI working dir."""
        self.project = project
        self.reference = None
        self.emit("reference", {"path": None})
        self.brief = self.load_brief(force=reanalyze) if project else None
        self.emit("brief", {"brief": asdict(self.brief) if self.brief else None})
        self.apply_voice()
        if self.worker:
            self.worker.close()
        state = load_state(project.root) if project else {}
        self.worker = Worker(project, self._work_event, model=self.s.worker_model, commands=self.s.worker_commands,
                             push=self.s.worker_push,
                             resume=state.get("worker_session") if state.get("worker_session") and
                             find_session(project.root, state["worker_session"]) else None) if project else None
        # Continue where this project's conversation left off (same Claude Code session), unless it's stale.
        resume = None
        if project and state.get("voice_session") and time.time() - state.get("updated", 0) < RESUME_DAYS * 86400:
            resume = find_session(project.root, state["voice_session"])
        self._start_cli(continue_session=resume)
        self.emit("state", {"state": self.state})  # leave the "analyzing" display

    def _start_cli(self, resume: SessionInfo | None = None, code_tools: bool = False, edits: bool = False,
                   continue_session: SessionInfo | None = None) -> None:
        """(Re)start the conversation process: Torti's own voice session (new, or ``continue_session``
        from last time in this project), or a Claude Code session the user picked (``resume``)."""
        tools, extra = READ_TOOLS, []
        if (resume or code_tools) and edits:
            tools += "," + EDIT_TOOLS
            extra = ["--permission-mode", "acceptEdits"]
        if self.cli:
            self.cli.stop()
        camera = None
        if self.camera:
            frame = self.camera.snapshot()
            camera = (self.camera.name or "웹캠") + (f", {frame.shape[1]}x{frame.shape[0]}" if frame is not None else "")
        self.cli = ClaudeCli(build_system_prompt(self.brief, camera, worker=self.project is not None),
                             model=self.s.model, effort=self.s.effort, cwd=self.cwd, tools=tools, extra_args=extra)
        self.session = resume
        target = resume or continue_session
        if target:
            self.cli.session_id = target.id
        self.cli.start(resume=target.id if target else None)  # boot now; the first question won't pay for it
        self.last_answer = ""
        self.emit("session", {"id": resume.id if resume else None, "title": resume.title if resume else None,
                              "tools": tools, "edits": edits, "continued": continue_session is not None,
                              "history": recent_exchanges(target.path) if target else []})
        if continue_session:
            self.log(f"지난 대화 이어서: {continue_session.title} ({continue_session.user_turns}턴, "
                     f"{continue_session.modified:%m-%d %H:%M})")

    def _remember_session(self) -> None:
        """Torti's own conversation in this project is continued next time it is opened."""
        if self.project and self.cli and self.session is None:
            save_state(self.project.root, voice_session=self.cli.session_id)

    def list_sessions(self) -> list[SessionInfo]:
        """Claude Code sessions recorded for the current work folder (voice and typed ones included)."""
        return sessions_for(self.cwd, default_projects_dir())

    def load_session(self, session: SessionInfo | None, edits: bool = False) -> None:
        """Continue a Claude Code session in this folder (None: back to a fresh Torti conversation)."""
        self._start_cli(resume=session, edits=edits)
        self.log(f"세션 불러옴: {session.title} ({session.id[:8]})" if session else "새 Torti 대화")

    def load_brief(self, force: bool = False) -> Brief | None:
        """Briefing to talk from: cached if the project is unchanged, else analyze the repo."""
        try:
            brief = None if force else load_cached(self.project.root)
            if brief is None:
                self.emit("state", {"state": "ANALYZING"})
                self.log(f"작업 분석 중 ({self.s.brief_model}, 읽기 전용)...")
                self.tts.say("작업 내용을 살펴볼게요.")
                t = time.perf_counter()
                brief = analyze(self.project.root, self.s.brief_model)
                self.log(f"작업 분석 완료 ({time.perf_counter() - t:.0f}s)")
            else:
                self.log("작업 브리핑: 캐시 사용 (바뀐 파일 없음)")
        except Exception as e:  # noqa: BLE001 - talk without a briefing rather than not at all
            self.log(f"작업 분석 실패: {e}")
            return None
        self.log(f"  {brief.title} | {brief.domain} | {brief.mood}, {brief.speech_level}")
        return brief

    def apply_voice(self) -> None:
        """Tone, voice and STT vocabulary all follow the project (FR-59)."""
        self.stt.initial_prompt = self.brief.stt_prompt() if self.brief and self.brief.vocabulary else DEFAULT_PROMPT
        rate, pitch = self.brief.voice() if self.brief else (1, 0)
        if self.s.tts_rate is not None:
            rate = self.s.tts_rate
        self.tts.set_style(rate, pitch)
        if hasattr(self.tts, "set_mood"):  # neural voice: mood -> emotion intensity
            self.tts.set_mood(self.brief.mood if self.brief else None)

    def set_reference(self, path: str | Path | None) -> bool:
        """Show a reference image (schematic, pinout, drawing) and ask about it instead of the camera."""
        if not path:
            self.reference = None
            self.emit("reference", {"path": None})
            return True
        img = read_image(path)
        if img is None:
            self.log(f"이미지를 열 수 없습니다: {path}")
            return False
        jpeg = encode_jpeg(img, 1568)  # drawings need more detail than desk photos
        self.reference = {"path": str(path), "jpeg": jpeg, "size": jpeg_size(jpeg)}
        self.emit("reference", {"path": str(path), "jpeg": jpeg})
        self.log(f"자료 보기: {Path(path).name}")
        return True

    def sync(self, announce: bool = True) -> None:
        if not self.project:
            if announce:
                self.tts.say("연결된 작업이 없어요.")
            return
        self.emit("sync", {"running": True})
        with self.sync_lock:
            res = self.project.sync()
        self.log(f"작업 동기화: {'성공' if res.ok else '실패'} - {res.message[-300:]}")
        self.emit("sync", {"running": False, "ok": res.ok, "message": res.message})
        if announce:
            if res.ok:
                self.tts.say("깃허브에 올렸어요." if res.message in ("올렸습니다", "이미 최신입니다") else "저장했어요.")
            else:
                self.earcons.play("error")
                self.tts.say("깃허브에 올리지 못했어요. 화면을 확인해 주세요.")

    def reanalyze(self) -> None:
        if not self.project:
            self.tts.say("연결된 작업이 없어요.")
            return
        self.use_project(self.project, reanalyze=True)
        self.tts.say(self.brief.greeting if self.brief else "작업을 분석하지 못했어요.")

    def new_conversation(self) -> None:
        self._start_cli()
        self.last_answer = ""
        if self.project:
            save_state(self.project.root, voice_session=None)

    # --------------------------------------------------------------- run loop
    def start(self, hotkeys: bool = True) -> None:
        """Begin listening for triggers (global hotkey/pedal, plus press()/release() from a UI)."""
        if hotkeys:
            import keyboard

            # suppress: the trigger key belongs to Torti; e.g. F1 must not also open help windows
            keyboard.on_press_key(self.s.hotkey, lambda _e: self._key_down(), suppress=True)
            keyboard.on_release_key(self.s.hotkey, lambda _e: self._key_up(), suppress=True)
            self._hooked = True
        self._running = True
        threading.Thread(target=self._dispatch, daemon=True, name="torti-dispatch").start()
        greeting = self.brief.greeting if self.brief and self.brief.greeting else "토르티 준비됐어요."
        flag = data_dir() / "notice_shown"
        if not flag.exists():  # NFR-07, once
            greeting += " " + NOTICE
            flag.write_text("1", encoding="utf-8")
        self.tts.say(greeting)
        self.set_state(IDLE)
        self.emit("ready", {"greeting": greeting, "hotkey": self.s.hotkey})

    def press(self) -> None:
        self._key_down()

    def release(self) -> None:
        self._key_up()

    def _key_down(self) -> None:
        if self.key_down:  # OS auto-repeat while the key or pedal is held
            return
        self.key_down = True
        self.triggers.put(("down", time.perf_counter()))

    def _key_up(self) -> None:
        self.key_down = False
        self.triggers.put(("up", time.perf_counter()))

    def _dispatch(self) -> None:
        while self._running:
            try:
                kind, t = self.triggers.get(timeout=0.2)
            except queue.Empty:
                continue
            if kind == "down":
                self.holding.set()
                self.down_at = t
                self._on_trigger(t)
            else:
                self.holding.clear()
                if self.state == LISTENING and t - self.down_at >= HOLD_S:
                    self.stop_listen.set()  # push-to-talk: release ends the question

    def _interrupt_turn(self) -> None:
        if self.turn is not None and self.turn.is_alive():
            self.log("끼어들기: 하던 답을 멈춤")
            self.cancel.set()
            self.tts.stop()
            self.turn.join(timeout=3)

    def switch_project(self, **kwargs) -> Project | None:
        """Open another project from the UI. An answer in progress is cut off first: switching used
        to be refused while Torti was talking, with only a small status-bar note, so it looked broken."""
        self._interrupt_turn()
        self.tts.stop()
        return self.open_project(**kwargs)

    def _on_trigger(self, t: float) -> None:
        if self.turn is None or not self.turn.is_alive():
            self._start_turn(self.run_turn, t)
        elif self.state == LISTENING:
            self.stop_listen.set()  # second press: done talking
        else:  # barge-in (FR-42): stop talking/thinking, listen to the new question
            self._interrupt_turn()
            self._start_turn(self.run_turn, t)

    def _start_turn(self, target, *args) -> None:
        self.cancel.clear()
        self.stop_listen.clear()
        self.turn = threading.Thread(target=target, args=args, daemon=True, name="torti-turn")
        self.turn.start()

    def ask_text(self, text: str, speak: bool | None = None) -> None:
        """Typed question (when talking isn't possible): same conversation, same project, same camera."""
        text = text.strip()
        if not text:
            return
        self._interrupt_turn()
        self._start_turn(self._text_turn, text, self.s.text_speaks if speak is None else speak)

    def shutdown(self) -> None:
        self._running = False
        if self._hooked:
            import keyboard

            keyboard.unhook_all()
        self.cancel.set()
        if hasattr(self, "tts"):
            self.tts.stop()
            self.tts.close()
        if self.cli:
            self.cli.stop()
        if self.pointer:
            self.pointer.stop()
        if self.inspector:
            self.inspector.pointer.stop()
        if self.worker:
            self.worker.close()
        if self.project:
            self.sync(announce=False)  # FR-55: push the day's log on exit
        if self.camera:
            self.camera.close()
        if hasattr(self, "rec"):
            self.rec.close()
        if hasattr(self, "earcons"):
            self.earcons.close()

    # ------------------------------------------------------------------- turns
    def run_turn(self, t_trigger: float) -> None:
        """Voice turn: listen -> STT -> respond."""
        tm: dict[str, float | None] = {"trigger": t_trigger}
        try:
            self.set_state(LISTENING)
            self.earcons.play("listen")
            tm["beep"] = time.perf_counter()
            utt = self.rec.listen(
                ignore_ms=self.earcons.duration_ms("listen") + 60,
                end_silence_ms=self.s.end_silence_ms,
                hold=self.holding, stop=self.stop_listen, cancel=self.cancel,
            )
            if utt is None:
                if not self.cancel.is_set():
                    self.log("(말소리 없음)")
                    self.earcons.play("idle")
                return
            self.earcons.play("accept")
            shot = self.camera.recent_frames() if self.camera else []  # made into a photo only if sent
            tm.update(speech_start=utt.speech_start, speech_end=utt.speech_end, endpoint=utt.endpoint_at)
            turn_id = self.history.next_id()
            wav = self.history.save_wav(turn_id, utt.audio)
            self.set_state(TRANSCRIBING)
            stt = self.stt.transcribe(utt.audio)
            tm["stt_done"] = time.perf_counter()
            self.log(f"STT {round(stt.seconds * 1000)}ms ({len(utt.audio) / 16000:.1f}s 음성, "
                     f"{'누름' if utt.manual_stop else '자동'} 종료, peak rms {utt.peak_rms:.3f}, {wav}): {stt.text!r}")
            if self.cancel.is_set():
                return
            if not stt.text:
                self.earcons.play("idle")
                return
            self.emit("heard", {"text": stt.text, "source": "voice", "stt_ms": round(stt.seconds * 1000)})
            self._respond(stt.text, shot, tm, turn_id, speak=True)
        except Exception as e:  # noqa: BLE001 - never crash the loop (NFR-06)
            self._fail(e)
        finally:
            self.set_state(IDLE)

    def _text_turn(self, text: str, speak: bool) -> None:
        now = time.perf_counter()
        tm: dict[str, float | None] = {"trigger": now, "speech_end": now}
        try:
            shot = self.camera.recent_frames() if self.camera else []  # made into a photo only if sent
            self.emit("heard", {"text": text, "source": "text", "stt_ms": None})
            self._respond(text, shot, tm, self.history.next_id(), speak=speak)
        except Exception as e:  # noqa: BLE001
            self._fail(e)
        finally:
            self.set_state(IDLE)

    def _fail(self, e: Exception) -> None:
        self.log(f"오류: {e!r}")
        self.emit("error", {"text": str(e)})
        self.earcons.play("error")
        self.tts.say("문제가 생겼어요. 다시 말해 주세요.")

    def _wants_photo(self, text: str) -> bool:
        """Auto mode: words about what's in front of the camera, anything while zoomed in (the user is
        looking at something), and short follow-ups ("봐봐", "어때", "이건?") right after a photo turn."""
        if self.s.image != "auto":
            return needs_image(text, self.s.image)
        follow_up = len(text.strip()) <= 12 and time.monotonic() - self.last_photo_at < 180
        return needs_image(text) or self.zoom.active or follow_up

    def _no_photo_reason(self, shot: list) -> str:
        if self.s.image == "never":
            return "사진 보내기 설정이 '보내지 않기'라서 사진을 받지 못했다. 화면 왼쪽 '사진' 설정을 '자동'으로 바꾸면 보인다."
        if self.camera is None:
            return "카메라가 켜져 있지 않다."
        if not shot:
            return "카메라가 다시 연결되는 중이라 지금 화면을 받지 못했다. 잠시 뒤 다시 물어보면 된다."
        return "이번 질문에는 사진이 붙지 않았다. '지금 이거 봐줘'처럼 물으면 사진을 같이 보낸다."

    def _respond(self, text: str, shot: list, tm: dict, turn_id: int, speak: bool) -> None:
        """Shared by voice and text: local commands, photo/reference, pointing, streamed answer."""
        note = match_note(text)
        if note:
            if self.project:
                self.project.add_note(note)
                self.log(f"메모 추가: {note}")
                self.emit("command", {"cmd": "note", "text": note})
                self.tts.say("기록했어요.")
            else:
                self.tts.say("연결된 작업이 없어서 기록하지 못했어요.")
            return
        zoom = match_zoom(text)  # before commands: "확대 취소" is a zoom reset, not "cancel"
        if zoom:
            self.zoom_command(*zoom, text=text)
            return
        cmd = match_command(text)
        if cmd:
            self.run_command(cmd, text)
            return

        # What the assistant looks at: a reference image the user put on screen, else the camera.
        jpeg, size, source = None, None, None
        view_rect = self.zoom.rect()
        if self.reference:
            jpeg, size, source = self.reference["jpeg"], self.reference["size"], Path(self.reference["path"]).name
        elif shot and self._wants_photo(text):
            jpeg = self._photo(shot)
            size, source = jpeg_size(jpeg), "사진"
        ask = text
        if jpeg and source == "사진" and self.zoom.active:
            ask = f"[{times_ko(self.zoom.factor)} 확대한 화면: 책상 일부만 보인다]\n{text}"
        if not jpeg and needs_image(text, "auto"):  # seems to be about what's in front of the camera
            ask = (f"[사진 없음: {self._no_photo_reason(shot)} 질문이 눈앞의 작업을 봐야 하는 것이면 "
                   f"볼 수 없다고만 하지 말고 이유와 방법을 한 문장으로 알려 준다. 사진 없이 답할 수 있으면 그냥 답한다.]\n{text}")
        image_name = None
        if jpeg and source == "사진":
            self.last_photo_at = time.monotonic()
        if jpeg and not self.reference:
            image_name = self.project.save_capture(jpeg) if self.project else self.history.save_image(turn_id, jpeg)
        if jpeg and wants_pointing(text) and self.pointer:  # precise model marks the spot in parallel
            threading.Thread(target=self._point, args=(jpeg, size, text, source, view_rect), daemon=True).start()

        self.set_state(THINKING)
        images = jpeg
        if source == "사진" and not self.zoom.active and needs_close_look(text):
            # Small print or fine detail: find the part and send a close-up along with the whole
            # photo, so the answer needs no second round trip (~1 s instead of ~7 s).
            look = self._close_look(shot, text, None, turn_id)
            if look:
                images = [jpeg, look.jpeg]
                ask = (f"[사진 두 장: 첫 번째는 책상 전체, 두 번째는 '{look.label}' 부분을 {times_ko(look.factor)} 확대한 것. "
                       f"글자와 작은 부분은 두 번째 사진으로 본다. 확대 태그는 쓰지 않는다]\n{text}")
        note = self.worker.status_note() if self.worker else None
        if note:  # what the worker is doing / just finished, so "작업 어떻게 됐어?" can be answered
            ask = f"{note}\n{ask}"
        tm["sent"] = time.perf_counter()
        answer, result, tags = self._stream(ask, images, tm, speak)
        if tags.work_order and not self.cancel.is_set():
            self._hand_off(tags.work_order)
        if not self.cancel.is_set() and tags.zoom_target is not None and result and result.ok:
            # The model still wants a closer look (<확대 대상="..."/>): close-up of that target, then
            # ask again. The user's own view and zoom stay as they were.
            target = tags.zoom_target or text
            jpeg, look = None, None
            if source == "사진" and self.camera:
                if speak:
                    self._speak("확대해서 볼게요.", tm)
                look = self._close_look(self.camera.recent_frames(), text, target, turn_id)
            if look:
                jpeg = look.jpeg
                ask = (f"[{look.label}을(를) {times_ko(look.factor)} 확대한 사진이다. 이 사진으로 답하고 "
                       f"확대 태그는 다시 쓰지 않는다]\n{text}")
            else:
                ask = (f"[확대 실패: '{target}'을(를) 확대하지 못했다. 앞 사진에서 보이는 만큼만 답하고, 필요하면 "
                       f"그 부분을 카메라 가운데로 가까이 옮겨 달라고 한마디 한다. 확대 태그는 다시 쓰지 않는다]\n{text}")
            more, result, _ = self._stream(ask, jpeg, tm, speak)
            answer = f"{answer} {more}".strip()
        if self.cancel.is_set():
            self._record(turn_id, text, image_name, answer, tm, result, interrupted=True)
            return

        if result is None or not result.ok:
            err = result.error if result else "응답 없음"
            self.log(f"Claude 오류: {err}")
            self.emit("error", {"text": str(err)})
            self.earcons.play("error")
            limit = "limit" in str(err).lower() or "한도" in str(err)
            self.tts.say("사용량 한도에 걸렸어요. 잠시 후 다시 물어봐 주세요." if limit
                         else "답을 받지 못했어요. 다시 물어봐 주세요.")
        else:
            self.last_answer = speakable(answer)
            if self.project:
                self.project.append_log(text, answer, image_name)
        finished = self.tts.wait_done(cancel=self.cancel) if speak else False
        first_audio = getattr(self.tts, "first_audio_after", None)
        if speak and first_audio and tm.get("sent"):
            tm["first_audio"] = first_audio(tm["sent"])  # when sound really started, not when text was queued
        self._record(turn_id, text, image_name, answer, tm, result)
        if finished:
            self.earcons.play("idle")

    def _stream(self, ask: str, jpeg: bytes | None, tm: dict, speak: bool) -> tuple[str, object, TagFilter]:
        """Ask the conversation model; show and speak the answer sentence by sentence as it streams."""
        tags, splitter, raw, result = TagFilter(), SentenceSplitter(), [], None
        said_filler = False
        gen = self.cli.ask(ask, jpeg, cancel=self.cancel)
        try:
            for kind, val in gen:
                if self.cancel.is_set():
                    break
                if kind == "tool":  # searching or reading takes seconds: say so instead of going quiet
                    self.log(f"도구: {val}")
                    self.emit("tool", {"name": val})
                    if speak and not said_filler and val in TOOL_FILLERS:
                        for sentence in splitter.flush():  # whatever was said before the tool call
                            self._speak(sentence, tm)
                        self._speak(TOOL_FILLERS[val], tm)
                        said_filler = True
                elif kind == "text":
                    clean = tags.feed(val)
                    if not clean:
                        continue
                    tm.setdefault("first_token", time.perf_counter())
                    raw.append(clean)
                    self.emit("delta", {"text": clean})
                    if speak:
                        for sentence in splitter.feed(clean):
                            self._speak(sentence, tm)
                elif kind == "result":
                    result = val
        finally:
            gen.close()
        if not self.cancel.is_set():
            rest = tags.flush()
            if rest:
                raw.append(rest)
                self.emit("delta", {"text": rest})
            if speak:
                for sentence in splitter.feed(rest) + splitter.flush():
                    self._speak(sentence, tm)
        return "".join(raw).strip(), result, tags

    # ------------------------------------------------------------------ zoom
    def _photo(self, frames: list) -> bytes:
        """JPEG of what the view shows, for the model: still frames averaged (less grain on small
        print) and, when zoomed, the crop at native pixels enlarged so small text is readable."""
        img, n = average_still([self.zoom.crop(f) for f in frames])
        if self.zoom.active:
            self.log(f"사진: {self.zoom.factor:.1f}배 확대, {img.shape[1]}x{img.shape[0]} 원본 화소, {n}장 평균")
            return for_model(img, self.s.long_edge)
        return encode_jpeg(img, self.s.long_edge)

    def zoom_changed(self, why: str) -> None:
        self.log(f"확대 {self.zoom.factor:.1f}배 ({why})" if self.zoom.active else f"전체 화면 ({why})")
        self.emit("zoom", {"factor": round(self.zoom.factor, 2), "rect": self.zoom.rect()})

    def _zoom_to_boxes(self, boxes: list[tuple[float, float, float, float]], why: str) -> None:
        self.zoom.to_box((min(b[0] for b in boxes), min(b[1] for b in boxes),
                          max(b[2] for b in boxes), max(b[3] for b in boxes)))
        self.zoom_changed(why)

    def _locate_zoom(self, target: str) -> bool:
        """Find ``target`` on the whole frame with the precise model and zoom the view onto it."""
        box = self._find(target)
        if box:
            self.zoom.to_box(box)
            self.zoom_changed(target)
        return box is not None

    def _find(self, target: str) -> tuple[float, float, float, float] | None:
        """Box around ``target`` on the whole camera frame (fractions)."""
        full = self.camera.snapshot() if self.camera else None
        if full is None or not self.inspector:
            return None
        try:
            box, secs, label = self.inspector.find(full, f"{target} 위치")
        except Exception as e:  # noqa: BLE001
            self.log(f"확대할 곳 찾기 실패: {e}")
            return None
        self.log(f"확대할 곳 '{target}' ({secs:.1f}s): {label or '찾지 못함'}")
        return box

    def _close_look(self, frames: list, question: str, target: str | None, turn_id: int):
        """Close-up for the model (closeup.Inspector); shown briefly so the user sees what was looked at."""
        if not frames or not self.inspector:
            return None
        try:
            look = self.inspector.look(frames, question, target)
        except Exception as e:  # noqa: BLE001 - a close-up is a bonus; answer from the whole photo
            self.log(f"확대 실패: {e}")
            return None
        if not look:
            self.log(f"확대할 곳 못 찾음: {target or question!r}")
            return None
        self.log(f"확대해서 봄: '{look.label}' {look.factor:.1f}배, 찾기 {look.seconds:.1f}s, {look.frames}장 평균")
        self.emit("peek", {"jpeg": look.jpeg, "label": look.label, "factor": round(look.factor, 1)})
        if self.project:
            self.project.save_capture(look.jpeg)
        else:
            self.history.save_image(turn_id, look.jpeg, "-close")
        return look

    def zoom_command(self, kind: str, target: str | None, times: float | None, text: str) -> None:
        """Spoken or typed zoom request: "확대해", "보드 확대해", "세 배 확대", "거기 확대", "축소", "원래대로"."""
        self.log(f"음성 명령: 확대 {kind} {target or ''} ({text!r})")
        self.emit("command", {"cmd": "zoom", "text": text})
        if not self.camera:
            self.tts.say("카메라가 없어서 확대할 수 없어요.")
        elif self.reference:
            self.tts.say("자료를 닫으면 카메라 화면을 확대할 수 있어요.")
        elif kind == "reset":
            self.zoom.reset()
            self.zoom_changed("원래대로")
            self.tts.say("전체 화면이에요.")
        elif kind == "out":
            self.zoom.zoom_at(self.zoom.factor / 2)
            self.zoom_changed("축소")
            self.tts.say(f"{times_ko(self.zoom.factor)}예요." if self.zoom.active else "전체 화면이에요.")
        elif target:
            self.tts.say("찾아서 확대할게요.")
            if self._locate_zoom(target):
                self.tts.say(f"{times_ko(self.zoom.factor)}로 확대했어요.")
            else:
                self.tts.say("화면에서 찾지 못했어요. 카메라 가운데로 옮겨 주세요.")
        elif (self.last_marks and time.monotonic() - self.last_marks[0] < 180 and not times
              and re.search(r"거기|여기|표시", text)):
            self._zoom_to_boxes(self.last_marks[1], "표시한 곳")
            self.tts.say("표시한 곳을 확대했어요.")
        else:
            self.zoom.zoom_at(times or (self.zoom.factor * 2 if self.zoom.active else 2.0))
            self.zoom_changed("확대")
            self.tts.say(f"{times_ko(self.zoom.factor)}예요.")

    def _point(self, jpeg: bytes, size: tuple[int, int], question: str, source: str,
               view_rect: tuple[float, float, float, float] | None = None) -> None:
        try:
            marks, secs = self.pointer.locate(jpeg, size, question)
        except Exception as e:  # noqa: BLE001 - pointing is a bonus; the spoken answer stands alone
            self.log(f"위치 표시 실패: {e}")
            return
        self.log(f"위치 표시 {len(marks)}개 ({secs:.1f}s): {', '.join(m.label for m in marks) or '찾지 못함'}")
        if marks and source == "사진" and view_rect:  # remembered on the full frame for "거기 확대해"
            self.last_marks = (time.monotonic(),
                               [self.zoom.view_to_full(tuple(v / 1000 for v in m.box), view_rect) for m in marks])
        if marks:
            self.earcons.play("visual")
            self.emit("visual", {"jpeg": jpeg, "marks": [asdict(m) for m in marks], "question": question,
                                 "source": source, "seconds": round(secs, 1)})

    def _speak(self, sentence: str, tm: dict) -> None:
        text = speakable(sentence)
        if not text:
            return
        if "first_say" not in tm:
            tm["first_say"] = time.perf_counter()
            self.set_state(SPEAKING)
        self.emit("say", {"text": text})
        self.tts.say(text)

    # ---------------------------------------------------------------- worker
    def _hand_off(self, order: str) -> None:
        """The voice model wrote <작업 지시="..."/>: give it to the worker."""
        if not self.worker:
            self.tts.say("작업 폴더가 열려 있지 않아서 맡길 수 없어요. 먼저 작업을 열어 주세요.")
        else:  # started, or queued behind the running task (the voice model already said so)
            self.log(f"작업자에게 맡김 ({self.worker.start(order)}): {order}")

    def _work_event(self, kind: str, data: dict) -> None:
        """Worker progress goes to the screen; the result is also said out loud (after the current turn)."""
        self.emit(kind, data)
        phase = data.get("phase")
        if phase == "step":
            self.log(f"작업 {data['n']}: {data['text']}")
        elif phase == "denied":
            self.log(f"작업자 명령 거부됨 (허용 목록 밖): {data['text']}")
        elif phase == "done":
            if self.project and self.worker and self.worker.session_id:
                save_state(self.project.root, worker_session=self.worker.session_id,
                           last_task={"summary": data["summary"], "commit": data["commit"], "files": data["files"]})
            self.log(f"작업 끝 ({data['seconds']}초, 커밋 {data['commit'] or '없음'}, "
                     f"{'GitHub에 올림' if data['pushed'] else '올리지 않음'}): {data['summary'][:200]}")
            sentences = re.split(r"(?<=[.!?])\s+", speakable(data["summary"]))
            text = ("작업을 멈췄어요. " if data["stopped"] else "작업 끝났어요. ") + " ".join(sentences[:3])
            if data["pushed"]:
                text += " GitHub에도 올렸어요."
            if self.state == IDLE:
                self.tts.say(text)
            else:
                self._say_when_idle.append(text)

    def run_command(self, cmd: str, text: str) -> None:
        self.log(f"음성 명령: {cmd} ({text!r})")
        self.emit("command", {"cmd": cmd, "text": text})
        if cmd == "stop":
            self.tts.stop()
            self.earcons.play("idle")
        elif cmd == "cancel":
            self.earcons.play("cancel")
        elif cmd == "repeat":
            self.tts.say(self.last_answer or "아직 드린 답이 없어요.")
        elif cmd == "new":
            self.new_conversation()
            self.tts.say("새 대화를 시작할게요.")
        elif cmd in ("slower", "faster"):
            self.tts.set_rate(self.tts.rate + (-2 if cmd == "slower" else 2))
            self.tts.say("천천히 말할게요." if cmd == "slower" else "빠르게 말할게요.")
        elif cmd == "sync":
            self.tts.say("깃허브에 올릴게요.")
            threading.Thread(target=self.sync, daemon=True).start()
        elif cmd == "work_stop":
            self.tts.say("작업 멈출게요." if self.worker and self.worker.stop() else "진행 중인 작업이 없어요.")
        elif cmd == "work_undo":
            self.tts.say(self.worker.undo().message if self.worker else "되돌릴 작업이 없어요.")
        elif cmd == "reanalyze":
            self.tts.say("작업을 다시 살펴볼게요.")
            self.reanalyze()

    def _record(self, turn_id: int, question: str, image: str | None, answer: str, tm: dict, result,
                interrupted: bool = False) -> None:
        lat = {
            "trigger_to_beep": ms(tm.get("trigger"), tm.get("beep")),
            "speech_len": ms(tm.get("speech_start"), tm.get("speech_end")),
            "endpoint_wait": ms(tm.get("speech_end"), tm.get("endpoint")),
            "stt": ms(tm.get("endpoint"), tm.get("stt_done")),
            "cli_first_token": ms(tm.get("sent"), tm.get("first_token")),
            "first_sentence_wait": ms(tm.get("first_token"), tm.get("first_say")),
            "tts_wait": ms(tm.get("first_say"), tm.get("first_audio")),
            "speech_end_to_first_audio": ms(tm.get("speech_end"), tm.get("first_audio") or tm.get("first_say")),
        }
        self.log("지연(ms): " + ", ".join(f"{k}={v}" for k, v in lat.items()))
        record = {
            "turn": turn_id, "question": question, "image": image, "answer": answer,
            "interrupted": interrupted, "latency_ms": lat,
            "model": self.cli.model_resolved, "ok": getattr(result, "ok", None),
            "error": getattr(result, "error", None), "usage": getattr(result, "usage", None),
        }
        self.history.append(record)
        self.emit("turn", record)
        self._remember_session()
