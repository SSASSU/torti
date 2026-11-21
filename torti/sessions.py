"""Claude Code sessions recorded for a working folder, so Torti can continue one (voice or text chat).

Claude Code keeps each conversation as ``<projects dir>/<slug>/<session id>.jsonl``, where the slug
is the working folder with every non-alphanumeric character replaced by ``-``. Different Korean
folder names can share a slug, so each file's recorded ``cwd`` is checked too.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class SessionInfo:
    id: str
    title: str
    modified: datetime
    user_turns: int
    path: Path


def default_projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base) / "projects"


def slug(cwd: Path | str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def _same_dir(a: str, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except OSError:
        return False


def _first_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def read_session(path: Path, cwd: Path | None = None) -> SessionInfo | None:
    """Title (first real user message), user turn count; None if it belongs to another folder."""
    title, turns, seen_cwd = "", 0, None
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if seen_cwd is None and rec.get("cwd"):
                    seen_cwd = rec["cwd"]
                if rec.get("type") != "user" or rec.get("isSidechain"):
                    continue
                text = _first_text(rec.get("message") or {}).strip()
                if not text or text.startswith("<"):  # tool results, command echoes, reminders
                    continue
                turns += 1
                if not title:
                    title = " ".join(text.split())[:80]
    except OSError:
        return None
    if cwd is not None and seen_cwd and not _same_dir(seen_cwd, cwd):
        return None
    if turns == 0:
        return None
    return SessionInfo(path.stem, title, datetime.fromtimestamp(path.stat().st_mtime), turns, path)


def sessions_for(cwd: Path, projects_dir: Path | None = None, limit: int = 30) -> list[SessionInfo]:
    """Most recent first."""
    folder = (projects_dir or default_projects_dir()) / slug(cwd)
    if not folder.is_dir():
        return []
    files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files:
        info = read_session(p, cwd)
        if info:
            out.append(info)
            if len(out) >= limit:
                break
    return out
