"""Local Korean TTS through Windows SAPI (FR-40, FR-41), interruptible for barge-in (FR-42)."""

from __future__ import annotations

import queue
import threading
import time

from xml.sax.saxutils import escape

_ASYNC, _PURGE, _IS_XML, _NOT_XML = 1, 2, 8, 16
_SPEAKING = 2  # SpeechRunState.SRSEIsSpeaking
_ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"


class SapiTts:
    """All SAPI calls happen on one COM thread; public methods only enqueue."""

    def __init__(self, voice_hint: str = "Heami", prefer_onecore: bool = True, rate: int = 1,
                 volume: int = 100, output_hint: str | None = None, pitch: int = 0) -> None:
        self.voice_hint, self.prefer_onecore = voice_hint, prefer_onecore
        self.rate, self.volume, self.output_hint, self.pitch = rate, volume, output_hint, pitch
        self.voice_name: str | None = None
        self.error: str | None = None
        self._q: queue.Queue = queue.Queue()
        self._pending = 0
        self._speaking = False
        self._lock = threading.Lock()
        self._ready = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="sapi-tts").start()
        if not self._ready.wait(15):
            self.error = "TTS 초기화 시간 초과"
        if self.error:
            raise RuntimeError(self.error)

    # ------------------------------------------------------------- public API
    def say(self, text: str) -> None:
        if self.pitch:  # pitch only exists as SAPI XML markup
            self._put("say_xml", f'<pitch absmiddle="{self.pitch}">{escape(text)}</pitch>')
        else:
            self._put("say", text)

    def stop(self) -> None:
        self._put("stop", None)

    def set_rate(self, rate: int) -> None:
        self.rate = max(-10, min(10, rate))
        self._put("rate", self.rate)

    def set_style(self, rate: int, pitch: int) -> None:
        """Voice for the project's mood (rate and pitch on -10..10)."""
        self.pitch = max(-10, min(10, pitch))
        self.set_rate(rate)

    def busy(self) -> bool:
        with self._lock:
            return self._pending > 0 or self._speaking

    def wait_done(self, cancel: threading.Event | None = None, timeout: float = 120) -> bool:
        deadline = time.monotonic() + timeout
        while self.busy() and time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                return False
            time.sleep(0.05)
        return not self.busy()

    def close(self) -> None:
        self._put("quit", None)

    # --------------------------------------------------------------- internals
    def _put(self, cmd: str, arg) -> None:
        with self._lock:
            self._pending += 1
        self._q.put((cmd, arg))

    def _pick_voice(self, voice):
        import win32com.client

        if self.prefer_onecore:
            try:
                cat = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
                cat.SetId(_ONECORE, False)
                for tok in cat.EnumerateTokens():
                    if self.voice_hint in tok.GetDescription():
                        return tok
            except Exception:  # noqa: BLE001 - OneCore voices are optional
                pass
        for tok in voice.GetVoices():
            if self.voice_hint in tok.GetDescription():
                return tok
        return None

    def _run(self) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            tok = self._pick_voice(voice)
            if tok is not None:
                voice.Voice = tok
            if self.output_hint:
                for out in voice.GetAudioOutputs():
                    if self.output_hint.lower() in out.GetDescription().lower():
                        voice.AudioOutput = out
                        break
            voice.Rate, voice.Volume = self.rate, self.volume
            self.voice_name = voice.Voice.GetDescription()
        except Exception as e:  # noqa: BLE001
            self.error = f"TTS 초기화 실패: {e}"
            self._ready.set()
            return
        self._ready.set()
        while True:
            try:
                cmd, arg = self._q.get(timeout=0.03)
            except queue.Empty:
                speaking = voice.Status.RunningState == _SPEAKING
                with self._lock:
                    self._speaking = speaking
                continue
            try:
                if cmd in ("say", "say_xml"):
                    voice.Speak(arg, _ASYNC | (_IS_XML if cmd == "say_xml" else _NOT_XML))
                    with self._lock:
                        self._speaking = True
                elif cmd == "stop":
                    voice.Speak("", _ASYNC | _PURGE)
                    with self._lock:
                        self._speaking = False
                elif cmd == "rate":
                    voice.Rate = arg
                elif cmd == "quit":
                    voice.Speak("", _ASYNC | _PURGE)
                    return
            finally:
                with self._lock:
                    self._pending -= 1
