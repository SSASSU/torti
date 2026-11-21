"""Project analysis: a short briefing the assistant talks from, and the mood that sets its tone and voice.

Torti reads the work repo once (Claude CLI with read-only tools) and caches the result in
``.torti/brief.json``. It runs again only when the project's files changed (notes, log, code...).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .claude_cli import cli_env, find_cli

MOODS = ("차분", "진지", "활기", "장난스러움", "친근")
# SAPI (rate, pitch) per mood, both on a -10..10 scale.
MOOD_VOICE = {"차분": (0, -2), "진지": (-1, -3), "활기": (2, 3), "장난스러움": (2, 5), "친근": (1, 1)}

CACHE = Path(".torti") / "brief.json"
BRIEF_VERSION = 2  # bump when SCHEMA changes so old caches are re-analyzed
_SKIP_DIRS = {".git", ".torti", "captures", "node_modules", ".venv", "venv", "__pycache__", "build", "dist"}

_LIST = {"type": "array", "items": {"type": "string"}}
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "작업 이름"},
        "domain": {"type": "string", "description": "작업 분야. 예: 납땜, 3D 프린팅, 목공, 펌웨어 코딩, 재봉, 도색"},
        "assistant_role": {"type": "string", "description": "이 작업에서 토르티의 역할 한 문장"},
        "vocabulary": {**_LIST, "maxItems": 30,
                       "description": "음성 인식이 알아들어야 할 이 작업의 고유 용어, 부품명, 모델명"},
        "summary": {"type": "string", "description": "무엇을 누구를 위해 만드는지 1~2문장"},
        "status": {"type": "string", "description": "지금까지 한 것. 기록이 없으면 '시작 전'"},
        "next_steps": {**_LIST, "maxItems": 5, "description": "다음에 할 일, 순서대로"},
        "key_facts": {**_LIST, "maxItems": 12, "description": "답변에 바로 쓸 사실: 부품 값, 핀, 전압, 배선"},
        "cautions": {**_LIST, "maxItems": 5, "description": "이 작업에서 특히 조심할 것"},
        "mood": {"type": "string", "enum": list(MOODS)},
        "speech_level": {"type": "string", "enum": ["반말", "존댓말"]},
        "tone": {"type": "string", "description": "말투 한 문장. 예: 짧고 담백하게, 잘하면 가볍게 칭찬"},
        "greeting": {"type": "string", "description": "작업을 시작할 때 건넬 첫마디 한 문장. 말투 적용, 다음 단계 포함"},
    },
    "required": ["title", "domain", "assistant_role", "vocabulary", "summary", "status", "next_steps",
                 "key_facts", "cautions", "mood", "speech_level", "tone", "greeting"],
}

ANALYST_SYSTEM = "너는 작업 저장소를 읽고, 음성 비서가 쓸 짧은 브리핑을 만드는 분석가다."

ANALYZE_PROMPT = """\
이 폴더는 사용자가 손으로 진행 중인 작업의 저장소다. 납땜, 3D 프린팅, 목공, 펌웨어 코딩, 수리 등 무엇이든 될 수 있다.
음성 비서 '토르티'는 작업하는 동안 이 브리핑만 보고 대화한다.

- README, NOTES.md, CLAUDE.md, log/의 최근 기록, 도면, 회로도, 코드, 부품이나 재료 목록을 필요한 만큼 읽는다. 파일은 15개 이내로 읽는다.
- datasheets/의 PDF는 파일 이름만 확인하고 열지 않는다.
- 작업 분야와 토르티의 역할은 파일 내용으로 판단한다. 납땜이라고 가정하지 않는다.
- 파일에 근거한 내용만 쓴다. 일반 상식이나 교과서 설명은 넣지 않는다. 모르는 칸은 비운다.
- 진행 상황과 다음 단계는 log/와 NOTES.md의 작업 순서를 기준으로 판단한다.
- 용어 목록에는 부품명, 모델명, 재료, 공구, 함수 이름처럼 음성 인식이 틀리기 쉬운 고유 단어를 넣는다.
- NOTES.md에 말투가 적혀 있으면 그대로 따른다. 없으면 작업의 목적, 대상, 위험도로 분위기와 말투를 정한다.
  선물이나 장난감처럼 즐거운 작업은 밝게, 고전압, 배터리, 날붙이 공구처럼 위험한 작업은 진지하게.
- 모든 문장은 한국어로, 짧게 쓴다.
"""


@dataclass
class Brief:
    title: str = ""
    domain: str = ""
    assistant_role: str = ""
    vocabulary: list[str] = field(default_factory=list)
    summary: str = ""
    status: str = ""
    next_steps: list[str] = field(default_factory=list)
    key_facts: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    mood: str = "차분"
    speech_level: str = "존댓말"
    tone: str = ""
    greeting: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> Brief:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def voice(self) -> tuple[int, int]:
        """(SAPI rate, pitch) for this mood."""
        return MOOD_VOICE.get(self.mood, (0, 0))

    def stt_prompt(self) -> str:
        """Whisper vocabulary hint for this project (FR-26)."""
        return f"{self.domain} 작업 중 질문. 토르티, " + ", ".join(self.vocabulary) + "."

    def to_prompt(self) -> str:
        lines = ["[현재 작업]", f"제목: {self.title}", f"분야: {self.domain}", f"네 역할: {self.assistant_role}",
                 f"요약: {self.summary}", f"진행 상황: {self.status}"]
        for name, items in (("다음 단계", self.next_steps), ("핵심 사실", self.key_facts), ("주의", self.cautions)):
            if items:
                lines.append(f"{name}:")
                lines += [f"- {item}" for item in items]
        lines += ["", "[말투]", f"분위기: {self.mood}, {self.speech_level}. {self.tone}".strip()]
        return "\n".join(lines)


def fingerprint(root: Path) -> str:
    """Changes when project files change; ignores photos and Torti's own cache."""
    h = hashlib.sha1()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts) or not path.is_file():
            continue
        h.update(f"{rel.as_posix()}|{path.stat().st_size}\n".encode())
        if path.suffix.lower() in (".md", ".txt"):  # same-size edits to notes and logs still count
            h.update(path.read_bytes())
    return h.hexdigest()


def load_cached(root: Path) -> Brief | None:
    try:
        data = json.loads((root / CACHE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("version") != BRIEF_VERSION or data.get("fingerprint") != fingerprint(root):
        return None
    return Brief.from_dict(data.get("brief") or {})


def analyze(root: Path, model: str = "sonnet", timeout: float = 300) -> Brief:
    """Read the repo with the Claude CLI (Read/Glob/Grep only) and cache the briefing."""
    exe = find_cli()
    if not exe:
        raise RuntimeError("Claude CLI를 찾을 수 없습니다")
    env, _ = cli_env()
    tools = "Read,Glob,Grep"
    cmd = [
        exe, "-p", "--output-format", "json", "--json-schema", json.dumps(SCHEMA, ensure_ascii=False),
        "--model", model, "--effort", "low", "--tools", tools, "--allowedTools", tools,
        "--strict-mcp-config", "--disable-slash-commands", "--permission-prompts", "none",
        "--no-session-persistence", "--system-prompt", ANALYST_SYSTEM, ANALYZE_PROMPT,
    ]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    t = time.perf_counter()
    r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, timeout=timeout, creationflags=flags)
    try:
        out = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    except ValueError:
        out = {}
    data = out.get("structured_output")
    if not isinstance(data, dict):
        detail = out.get("result") or r.stderr.decode("utf-8", "replace")[-300:]
        raise RuntimeError(f"작업 분석 실패: {detail}")
    brief = Brief.from_dict(data)
    (root / CACHE.parent).mkdir(exist_ok=True)
    (root / CACHE).write_text(json.dumps({
        "version": BRIEF_VERSION,
        "fingerprint": fingerprint(root),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seconds": round(time.perf_counter() - t, 1),
        "model": model,
        "brief": asdict(brief),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return brief


def ensure_brief(root: Path, model: str = "sonnet", force: bool = False) -> tuple[Brief, bool]:
    """Cached briefing if the project is unchanged, else a fresh analysis. Returns (brief, analyzed)."""
    if not force:
        cached = load_cached(root)
        if cached is not None:
            return cached, False
    return analyze(root, model), True
