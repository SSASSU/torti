"""Show where sound goes: PortAudio/SAPI default outputs, all outputs, and the mic noise floor."""

import sys
import time

import numpy as np
import sounddevice as sd

sys.stdout.reconfigure(encoding="utf-8")
apis = sd.query_hostapis()
print("default output (PortAudio/MME):", sd.query_devices(kind="output")["name"])
try:
    import win32com.client

    v = win32com.client.Dispatch("SAPI.SpVoice")
    print("default output (SAPI):", v.AudioOutput.GetDescription())
    print("SAPI outputs:", [o.GetDescription() for o in v.GetAudioOutputs()])
except Exception as e:  # noqa: BLE001
    print("SAPI:", e)
print("MME outputs:")
for i, d in enumerate(sd.query_devices()):
    if d["max_output_channels"] > 0 and apis[d["hostapi"]]["name"] == "MME":
        print(f"  {i:>3} {d['name']}")

mic = next(i for i, d in enumerate(sd.query_devices())
           if d["max_input_channels"] > 0 and "Wave:3" in d["name"] and apis[d["hostapi"]]["name"] == "MME")
x = sd.rec(int(16000 * 2), samplerate=16000, channels=1, dtype="float32", device=mic)
sd.wait()
frames = x[: len(x) // 480 * 480, 0].reshape(-1, 480)
rms = np.sqrt((frames ** 2).mean(axis=1))
print(f"Wave:3 2s: frame rms median={np.median(rms):.4f} p90={np.percentile(rms, 90):.4f} max={rms.max():.4f}")
