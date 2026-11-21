"""Make the pip-installed NVIDIA runtime DLLs (cuBLAS, cuDNN) loadable by CTranslate2 on Windows."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_done = False


def add_nvidia_dll_dirs() -> list[str]:
    """Add every ``nvidia/*/bin`` directory to the DLL search path. Safe to call more than once."""
    global _done
    if _done or sys.platform != "win32":
        return []
    _done = True
    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return []
    added: list[str] = []
    for base in spec.submodule_search_locations:
        for bin_dir in sorted(Path(base).glob("*/bin")):
            os.add_dll_directory(str(bin_dir))
            added.append(str(bin_dir))
    if added:
        # CTranslate2 loads some libraries with plain LoadLibrary, which only consults PATH.
        os.environ["PATH"] = os.pathsep.join(added + [os.environ.get("PATH", "")])
    return added
