"""Torti engine: one conversation that voice, typed chat, camera, reference images and the work
project all feed into. UI-agnostic; everything that happens is reported with ``emit(kind, data)``
from worker threads (the console prints it, the GUI turns it into Qt signals).

Events: log, state, cli, project, brief, session, heard, delta, say, turn, command, visual,
reference, sync, ready, error, fatal.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .audio import Recorder, find_device
from .brief import Brief, analyze, load_cached
from .camera import Camera, encode_jpeg, jpeg_size, read_image, resolve_camera
from .claude_cli import BILLING_ENV_VARS, ClaudeCli, check_cli
from .config import Settings
from .history import History
from .intent import match_command, match_note, needs_image
from .paths import data_dir, history_dir, workspace_dir
from .project import Project, gh_available
from .prompts import build_system_prompt
from .sessions import SessionInfo, default_projects_dir, sessions_for
from .sounds import Earcons
from .speech_text import SentenceSplitter, speakable
from .stt import DEFAULT_PROMPT, WhisperStt
from . import tts_neural
from .tts import SapiTts
from .visual import Pointer, TagFilter, wants_pointing

LOADING, IDLE, LISTENING, TRANSCRIBING, THINKING, SPEAKING = (
    "LOADING", "IDLE", "LISTENING", "TRANSCRIBING", "THINKING", "SPEAKING")
HOLD_S = 0.4  # held longer than this = push-to-talk; shorter = tap (VAD finds the end)
NOTICE = "AI 답변은 참고용이에요. 수치는 꼭 계측기나 데이터시트로 확인해 주세요."
CODE_TOOLS = "Read,Glob,Grep"
EDIT_TOOLS = "Edit,Write"

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
        self.reference: dict | None = None  # {"path", "jpeg", "size"} shown instead of the camera
        self.session: SessionInfo | None = None  # a resumed Claude Code session, if any
        self.sync_lock = threading.Lock()
        self._running = False
        self._hooked = False

    def log(self, text: str) -> None:
        self.emit("log", {"text": text})

    def set_state(self, state: str) -> None:
        self.state = state
        self.emit("state", {"state": state})

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
            idx, name = resolve_camera(self.s.camera)
            cam = Camera(idx)
            if cam.open():
                self.camera = cam
                self.log(f"카메라: {name} (index {idx})")
            else:
                self.log(f"카메라 열기 실패: {name} (index {idx}) - 사진 없이 진행")
        self.pointer = Pointer(self.s.pointer_model, cwd=workspace_dir())
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
        self._start_cli()
        self.emit("state", {"state": self.state})  # leave the "analyzing" display

    def _start_cli(self, resume: SessionInfo | None = None, code_tools: bool = False, edits: bool = False) -> None:
        """(Re)start the conversation process: Torti's own voice session, or a resumed one."""
        tools, extra = "", []
        if resume or code_tools:
            tools = CODE_TOOLS + ("," + EDIT_TOOLS if edits else "")
            if edits:
                extra = ["--permission-mode", "acceptEdits"]
        elif self.project and any((self.project.root / "datasheets").glob("*.pdf")):
            tools = "Read"  # FR-52: let the CLI read datasheets; read-only
        if self.cli:
            self.cli.stop()
        self.cli = ClaudeCli(build_system_prompt(self.brief), model=self.s.model, effort=self.s.effort,
                             cwd=self.cwd, tools=tools, extra_args=extra)
        self.session = resume
        if resume:
            self.cli.session_id = resume.id
        self.cli.start(resume=resume.id if resume else None)  # boot now; the first question won't pay for it
        self.last_answer = ""
        self.emit("session", {"id": resume.id if resume else None, "title": resume.title if resume else None,
                              "tools": tools, "edits": edits})

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

    # --------------------------------------------------------------- run loop
    def start(self, hotkeys: bool = True) -> None:
        """Begin listening for triggers (global hotkey/pedal, plus press()/release() from a UI)."""
        if hotkeys:
            import keyboard

            keyboard.on_press_key(self.s.hotkey, lambda _e: self._key_down())
            keyboard.on_release_key(self.s.hotkey, lambda _e: self._key_up())
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
            frame = self.camera.snapshot() if self.camera else None
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
            self._respond(stt.text, frame, tm, turn_id, speak=True)
        except Exception as e:  # noqa: BLE001 - never crash the loop (NFR-06)
            self._fail(e)
        finally:
            self.set_state(IDLE)

    def _text_turn(self, text: str, speak: bool) -> None:
        now = time.perf_counter()
        tm: dict[str, float | None] = {"trigger": now, "speech_end": now}
        try:
            frame = self.camera.snapshot() if self.camera else None
            self.emit("heard", {"text": text, "source": "text", "stt_ms": None})
            self._respond(text, frame, tm, self.history.next_id(), speak=speak)
        except Exception as e:  # noqa: BLE001
            self._fail(e)
        finally:
            self.set_state(IDLE)

    def _fail(self, e: Exception) -> None:
        self.log(f"오류: {e!r}")
        self.emit("error", {"text": str(e)})
        self.earcons.play("error")
        self.tts.say("문제가 생겼어요. 다시 말해 주세요.")

    def _respond(self, text: str, frame, tm: dict, turn_id: int, speak: bool) -> None:
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
        cmd = match_command(text)
        if cmd:
            self.run_command(cmd, text)
            return

        # What the assistant looks at: a reference image the user put on screen, else the camera.
        jpeg, size, source = None, None, None
        if self.reference:
            jpeg, size, source = self.reference["jpeg"], self.reference["size"], Path(self.reference["path"]).name
        elif frame is not None and needs_image(text, self.s.image):
            jpeg = encode_jpeg(frame, self.s.long_edge)
            size, source = jpeg_size(jpeg), "사진"
        image_name = None
        if jpeg and not self.reference:
            image_name = self.project.save_capture(jpeg) if self.project else self.history.save_image(turn_id, jpeg)
        if jpeg and wants_pointing(text) and self.pointer:  # precise model marks the spot in parallel
            threading.Thread(target=self._point, args=(jpeg, size, text, source), daemon=True).start()

        self.set_state(THINKING)
        tags = TagFilter()
        splitter = SentenceSplitter()
        raw: list[str] = []
        result = None
        tm["sent"] = time.perf_counter()
        gen = self.cli.ask(text, jpeg, cancel=self.cancel)
        try:
            for kind, val in gen:
                if self.cancel.is_set():
                    break
                if kind == "text":
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
        answer = "".join(raw).strip()
        if self.cancel.is_set():
            self._record(turn_id, text, image_name, answer, tm, result, interrupted=True)
            return
        rest = tags.flush()
        if rest:
            answer = (answer + rest).strip()
            self.emit("delta", {"text": rest})
        if speak:
            for sentence in splitter.feed(rest) + splitter.flush():
                self._speak(sentence, tm)

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

    def _point(self, jpeg: bytes, size: tuple[int, int], question: str, source: str) -> None:
        try:
            marks, secs = self.pointer.locate(jpeg, size, question)
        except Exception as e:  # noqa: BLE001 - pointing is a bonus; the spoken answer stands alone
            self.log(f"위치 표시 실패: {e}")
            return
        self.log(f"위치 표시 {len(marks)}개 ({secs:.1f}s): {', '.join(m.label for m in marks) or '찾지 못함'}")
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
