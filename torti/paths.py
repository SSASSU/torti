"""Where Torti keeps runtime data. Outside the repo so the CLI workspace never picks up dev files."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("TORTI_DATA") or os.path.join(os.environ.get("LOCALAPPDATA") or str(Path.home()), "Torti")
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_dir() -> Path:
    """Working directory for the Claude CLI (project notes, datasheets later)."""
    return data_dir() / "workspace"


def history_dir() -> Path:
    return data_dir() / "history"
