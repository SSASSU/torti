"""Work projects backed by a GitHub repository (FR-50..FR-57).

One project = one repo = one local folder. The folder is the Claude CLI working directory, so
the CLI loads its CLAUDE.md (which imports NOTES.md) and can read datasheets in it. Torti appends
the Q&A log and voice notes, then commits and pushes so the repo (and anything synced from it,
such as a claude.ai Project) stays current.

Git runs non-interactively with the Git Credential Manager login already on the machine; no
token is stored by Torti. Photos stay local unless ``push_photos`` is set (privacy, repo size).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .paths import data_dir

CLAUDE_MD = """\
# {name}

Torti(납땜·전자 조립 음성 비서)가 이 작업을 도울 때 읽는 지침이다. 자유롭게 고쳐도 된다.

- 작업 목표, 부품 목록, 조립 순서, 주의사항은 NOTES.md에 있다. 질문에 답할 때 참고한다.
- datasheets/ 폴더의 PDF는 핀배치나 정격을 물을 때 읽고 근거로 삼는다.
- log/ 폴더는 지난 질문과 답 기록이다. "지난번에", "아까" 같은 말이 나오면 참고한다.

@NOTES.md
"""

NOTES_MD = """\
# {name} 작업 메모

## 목표

## 부품 목록 (BOM)

## 조립 순서

## 말투
(비워 두면 작업 성격에 맞춰 Torti가 정한다. 예: 반말로 장난스럽게 / 존댓말로 차분하게)

## 메모
"""

GITIGNORE_LINES = ("captures/", ".torti/")  # photos stay local; .torti/ is Torti's derived cache


@dataclass
class GitResult:
    ok: bool
    message: str


def _slug(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", name.strip()).strip("-.")
    return s or time.strftime("work-%Y%m%d-%H%M%S")


def projects_dir() -> Path:
    path = data_dir() / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_projects(base: Path | None = None) -> list[str]:
    base = base or projects_dir()
    return sorted(p.name for p in base.iterdir() if (p / ".git").exists())


def _registry() -> Path:
    return data_dir() / "folders.json"


def external_folders() -> list[str]:
    """Existing work folders opened in place (e.g. where the user already works with Claude Code)."""
    try:
        return [p for p in json.loads(_registry().read_text(encoding="utf-8")) if Path(p).is_dir()]
    except (OSError, ValueError):
        return []


def remember_folder(path: Path) -> None:
    if path.resolve().parent == projects_dir().resolve():
        return  # Torti's own projects are listed already
    folders = [p for p in external_folders() if Path(p).resolve() != path.resolve()]
    _registry().write_text(json.dumps([str(path)] + folders, ensure_ascii=False, indent=2), encoding="utf-8")


def known_projects() -> dict[str, Path]:
    """Display name -> folder, for Torti's own projects and folders opened in place."""
    out = {name: projects_dir() / name for name in list_projects()}
    seen = {p.resolve() for p in out.values()}
    for p in external_folders():
        path = Path(p)
        if path.resolve() in seen:  # a Torti project opened by full path: already listed
            continue
        seen.add(path.resolve())
        out[path.name if path.name not in out else f"{path.name} ({p})"] = path
    return out


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"  # never block the voice loop on a prompt
    env["GCM_INTERACTIVE"] = "never"
    return env


def _run(args: list[str], cwd: Path | None = None, timeout: float = 120) -> GitResult:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        r = subprocess.run(args, cwd=cwd, env=_git_env(), capture_output=True, timeout=timeout, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as e:
        return GitResult(False, str(e))
    out = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    return GitResult(r.returncode == 0, out)


def gh_available() -> bool:
    return shutil.which("gh") is not None and _run(["gh", "auth", "status"]).ok


class Project:
    def __init__(self, root: Path, push_photos: bool = False) -> None:
        self.root = Path(root)
        self.name = self.root.name
        self.push_photos = push_photos

    # ------------------------------------------------------------- lifecycle
    @classmethod
    def create(cls, name: str, remote_url: str | None = None, github: bool = False,
               base: Path | None = None, push_photos: bool = False) -> tuple[Project, GitResult]:
        """New work: scaffold the folder, init git, and connect a remote.

        ``remote_url``: an empty repo the user made on GitHub. ``github=True``: create a private
        repo with the gh CLI instead. With neither, the project stays local until a remote is set.
        """
        root = (base or projects_dir()) / _slug(name)
        if root.exists():
            raise FileExistsError(f"이미 있는 작업입니다: {root.name}")
        (root / "datasheets").mkdir(parents=True)
        (root / "log").mkdir()
        (root / "captures").mkdir()
        (root / "CLAUDE.md").write_text(CLAUDE_MD.format(name=name), encoding="utf-8")
        (root / "NOTES.md").write_text(NOTES_MD.format(name=name), encoding="utf-8")
        (root / "datasheets" / ".gitkeep").write_text("", encoding="utf-8")
        (root / "log" / ".gitkeep").write_text("", encoding="utf-8")
        proj = cls(root, push_photos)
        proj.ensure_layout()
        for args in (["git", "init", "-b", "main"], ["git", "add", "-A"],
                     ["git", "commit", "-m", f"새 작업 시작: {name}"]):
            res = _run(args, cwd=root)
            if not res.ok:
                return proj, res
        if github:
            res = _run(["gh", "repo", "create", root.name, "--private", "--source", str(root), "--push"], cwd=root)
            return proj, res
        if remote_url:
            res = _run(["git", "remote", "add", "origin", remote_url], cwd=root)
            if not res.ok:
                return proj, res
            return proj, _run(["git", "push", "-u", "origin", "main"], cwd=root)
        return proj, GitResult(True, "원격 저장소 없이 로컬에 만들었습니다")

    @classmethod
    def clone(cls, url: str, base: Path | None = None, push_photos: bool = False) -> tuple[Project, GitResult]:
        """Continue existing work from GitHub (e.g. a repo already used as a Claude project)."""
        # https://github.com/u/repo(.git), git@github.com:u/repo.git, or a local path
        name = _slug(re.split(r"[/\\:]", url.rstrip("/\\"))[-1].removesuffix(".git"))
        root = (base or projects_dir()) / name
        if (root / ".git").exists():
            proj = cls(root, push_photos)
            return proj, proj.pull()
        res = _run(["git", "clone", url, str(root)], timeout=300)
        proj = cls(root, push_photos)
        if res.ok:
            proj.ensure_layout()
        return proj, res

    @classmethod
    def open(cls, name: str, base: Path | None = None, push_photos: bool = False) -> tuple[Project, GitResult]:
        """Continue local work; pull first when it has a remote."""
        root = (base or projects_dir()) / name
        if not (root / ".git").exists():
            raise FileNotFoundError(f"작업을 찾을 수 없습니다: {name} (목록: {list_projects(base)})")
        proj = cls(root, push_photos)
        proj.ensure_layout()
        return proj, proj.pull() if proj.has_remote() else GitResult(True, "원격 저장소 없음")

    @classmethod
    def open_folder(cls, path: Path, push_photos: bool = False) -> tuple[Project, GitResult]:
        """Use an existing folder as-is (its CLAUDE.md, files and Claude Code sessions carry over)."""
        root = Path(path).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"폴더가 없습니다: {root}")
        proj = cls(root, push_photos)
        proj.ensure_layout()
        remember_folder(root)
        if not (root / ".git").exists():
            return proj, GitResult(True, "git 저장소가 아닌 폴더 (동기화 없이 사용)")
        return proj, proj.pull() if proj.has_remote() else GitResult(True, "원격 저장소 없음")

    def ensure_layout(self) -> None:
        """Add Torti's folders to a repo that didn't start as a Torti project; leave its files alone."""
        for d in ("log", "captures", "datasheets"):
            (self.root / d).mkdir(exist_ok=True)
        gi = self.root / ".gitignore"
        text = gi.read_text(encoding="utf-8") if gi.exists() else ""
        missing = [line for line in GITIGNORE_LINES
                   if line not in text.splitlines() and not (line == "captures/" and self.push_photos)]
        if missing:
            sep = "" if text.endswith("\n") or not text else "\n"
            gi.write_text(text + sep + "".join(f"{line}\n" for line in missing), encoding="utf-8")

    # ------------------------------------------------------------------ git
    def is_repo(self) -> bool:
        return (self.root / ".git").exists()

    def has_remote(self) -> bool:
        if not self.is_repo():
            return False
        res = _run(["git", "remote"], cwd=self.root)
        return res.ok and bool(res.message.strip())

    def pull(self) -> GitResult:
        return _run(["git", "pull", "--ff-only"], cwd=self.root)

    def sync(self, message: str | None = None) -> GitResult:
        """Commit whatever changed and push. Never force; a rejected push is reported, not resolved."""
        if not self.is_repo():
            return GitResult(True, "git 저장소가 아니라 기록만 저장했습니다")
        res = _run(["git", "add", "-A"], cwd=self.root)
        if not res.ok:
            return res
        if _run(["git", "diff", "--cached", "--quiet"], cwd=self.root).ok:
            changed = False
        else:
            res = _run(["git", "commit", "-m", message or time.strftime("Torti 작업 기록 %Y-%m-%d %H:%M")],
                       cwd=self.root)
            if not res.ok:
                return res
            changed = True
        if not self.has_remote():
            return GitResult(True, "커밋했습니다 (원격 저장소 없음)" if changed else "바뀐 내용 없음")
        res = _run(["git", "push", "-u", "origin", "HEAD"], cwd=self.root)
        if res.ok:
            return GitResult(True, "올렸습니다" if changed else "이미 최신입니다")
        return res

    # --------------------------------------------------------------- content
    def save_capture(self, jpeg: bytes) -> str:
        rel = f"captures/{time.strftime('%Y%m%d-%H%M%S')}.jpg"
        (self.root / rel).write_bytes(jpeg)
        return rel

    def append_log(self, question: str, answer: str, image: str | None = None) -> None:
        path = self.root / "log" / f"{time.strftime('%Y-%m-%d')}.md"
        new = not path.exists()
        lines = [f"# {time.strftime('%Y-%m-%d')} 작업 기록\n"] if new else []
        lines += [f"\n## {time.strftime('%H:%M:%S')}\n", f"- 질문: {question}\n", f"- 답변: {answer}\n"]
        if image:
            lines.append(f"- 사진: {image}\n")
        with path.open("a", encoding="utf-8") as f:
            f.writelines(lines)

    def add_note(self, text: str) -> None:
        """VC-07 "기록해 둬: ..." appends to NOTES.md under a dated bullet."""
        with (self.root / "NOTES.md").open("a", encoding="utf-8") as f:
            f.write(f"\n- {time.strftime('%m-%d %H:%M')} {text}\n")
