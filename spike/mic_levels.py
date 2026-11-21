"""Measure 1 s of signal on every MME input device, to find which one actually carries the mic."""

import sys

import numpy as np
import sounddevice as sd

sys.stdout.reconfigure(encoding="utf-8")
apis = sd.query_hostapis()
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] < 1 or apis[d["hostapi"]]["name"] != "MME":
        continue
    try:
        x = sd.rec(16000, samplerate=16000, channels=1, dtype="float32", device=i)
        sd.wait()
        print(f"{i:>3} rms={float(np.sqrt(np.mean(x ** 2))):.5f} peak={float(np.abs(x).max()):.4f}  {d['name']}")
    except Exception as e:  # noqa: BLE001
        print(f"{i:>3} ERROR {e}  {d['name']}")
print("default input:", sd.query_devices(kind="input")["name"])
