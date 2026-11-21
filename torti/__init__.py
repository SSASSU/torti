"""Torti: hands-free voice + vision assistant for hands-on work (soldering, 3D printing, woodworking...)."""

import os
from pathlib import Path

__version__ = "0.0.1"

# Everything Torti downloads (Whisper/TTS models) stays inside the project folder, not the user profile.
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
os.environ.setdefault("HF_HOME", str(CACHE / "huggingface"))
os.environ.setdefault("TORCH_HOME", str(CACHE / "torch"))
os.environ.setdefault("PKUSEG_HOME", str(CACHE / "pkuseg"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
