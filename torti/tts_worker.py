"""Chatterbox TTS worker. Runs in the isolated .venv-tts (torch stack) and talks JSON lines on stdio:

    in : {"id": 3, "text": "...", "exaggeration": 0.5, "speed": 1.0}   synthesize (queued, in order)
         {"cancel_upto": 3}                                          drop queued requests with id <= 3
    out: {"ready": true, "sr": 24000, "load_s": 21.3}                once, after loading + warm-up
         {"id": 3, "sr": 24000, "pcm": "<base64 int16 mono>", "synth_s": 0.9, "audio_s": 2.1}
         {"id": 3, "error": "..."}

    .venv-tts\\Scripts\\python -m torti.tts_worker [--steps 10] [--bench]
"""

from __future__ import annotations

import argparse
import base64
import json
import queue
import sys
import threading
import time

import torti  # noqa: F401 - sets HF_HOME/TORCH_HOME/PKUSEG_HOME to the project .cache before imports below

import numpy as np  # noqa: E402
import torch  # noqa: E402

BENCH = ["좋아요, 이제 LED 열여섯 개를 달 차례예요.", "먼저 전원 플러그가 뽑혀 있는지 확인해 주세요.",
         "우퍼 구멍 지름은 백이십팔 밀리미터예요. 트위터 쪽은 기록이 없으니 규격서를 확인해 보세요."]


def speed_patches(model) -> None:
    """Make Chatterbox's token loop fast without changing what it computes.

    Upstream, the alignment analyzer (hallucination guard) needs attention weights of three layers,
    so it switches the *whole* model to eager attention and asks every layer for its weights on
    every token. It also adds a new forward hook on each generate() and never removes the old
    ones, so a long-running process slows down sentence after sentence.

    Here: only the three watched layers run eager (own config copy); while decoding one token at a
    time all other layers use SDPA. The prompt pass stays eager everywhere, as upstream, because
    the eager layers need a causal mask there. Hooks from earlier sentences are removed.
    """
    import copy

    from chatterbox.models.t3.inference import alignment_stream_analyzer as asa
    from chatterbox.models.t3.inference import t3_hf_backend as hb

    tfmr = model.t3.tfmr
    for layer_idx, _head in asa.LLAMA_ALIGNED_HEADS:
        attn = tfmr.layers[layer_idx].self_attn
        attn.config = copy.copy(tfmr.config)
        attn.config._attn_implementation = "eager"

    handles: list[tuple[int, object]] = []

    def add_spy(self, tfmr, buffer_idx, layer_idx, head_idx):
        for owner, h in [x for x in handles if x[0] != id(self)]:  # drop hooks of finished sentences
            h.remove()
            handles.remove((owner, h))

        def hook(_module, _inp, out):
            if isinstance(out, tuple) and len(out) > 1 and out[1] is not None:
                self.last_aligned_attns[buffer_idx] = out[1][0, head_idx].float().cpu()

        handles.append((id(self), tfmr.layers[layer_idx].self_attn.register_forward_hook(hook)))

    asa.AlignmentStreamAnalyzer._add_attention_spy = add_spy
    original_forward = hb.T3HuggingfaceBackend.forward

    def forward(self, inputs_embeds, past_key_values=None, use_cache=True, output_attentions=False,
                output_hidden_states=True, return_dict=True):
        cfg = self.model.config
        cfg._attn_implementation = "eager" if inputs_embeds.size(1) != 1 else "sdpa"
        cfg.output_attentions = False
        return original_forward(self, inputs_embeds, past_key_values, use_cache, False,
                                output_hidden_states, return_dict)

    hb.T3HuggingfaceBackend.forward = forward
    from chatterbox.models.t3 import t3 as t3mod

    def token_loop(it, *_a, **_k):  # replaces the per-token progress bar; lets barge-in stop a sentence
        for i in it:
            if CANCEL.is_set():
                raise Cancelled
            yield i

    t3mod.tqdm = token_loop


class Cancelled(Exception):
    pass


CANCEL = threading.Event()  # set when the sentence being made was cancelled (barge-in)


def load(steps: int, fast: bool = True):
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    if fast:
        speed_patches(model)
    if steps != 10:  # fewer flow-matching steps: faster vocoding, slightly less detail
        orig = model.s3gen.inference
        model.s3gen.inference = lambda *a, **kw: orig(*a, **{**kw, "n_cfm_timesteps": steps})
    return model


def synth(model, text: str, exaggeration: float, speed: float) -> np.ndarray:
    wav = model.generate(text, language_id="ko", exaggeration=exaggeration, cfg_weight=0.5)
    audio = wav.squeeze().detach().cpu().numpy().astype(np.float32)
    if abs(speed - 1.0) > 0.02:
        import librosa

        audio = librosa.effects.time_stretch(audio, rate=speed)
    return audio


def serve(model) -> None:
    out_lock = threading.Lock()

    def send(obj: dict) -> None:
        with out_lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    requests: queue.Queue[dict] = queue.Queue()
    cancel_upto = [-1]
    current = [-1]

    def reader() -> None:  # keeps reading so cancels arrive while a sentence is being made
        for line in sys.stdin:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "cancel_upto" in msg:
                cancel_upto[0] = max(cancel_upto[0], int(msg["cancel_upto"]))
                if current[0] <= cancel_upto[0]:
                    CANCEL.set()
            elif "id" in msg:
                requests.put(msg)
        requests.put({"quit": True})

    threading.Thread(target=reader, daemon=True).start()
    while True:
        msg = requests.get()
        if msg.get("quit"):
            return
        if msg["id"] <= cancel_upto[0]:
            continue
        current[0] = msg["id"]
        CANCEL.clear()
        try:
            t = time.perf_counter()
            audio = synth(model, msg["text"], float(msg.get("exaggeration", 0.5)), float(msg.get("speed", 1.0)))
            pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
            send({"id": msg["id"], "sr": model.sr, "pcm": base64.b64encode(pcm).decode("ascii"),
                  "synth_s": round(time.perf_counter() - t, 3), "audio_s": round(len(audio) / model.sr, 3)})
        except Cancelled:
            send({"id": msg["id"], "error": "cancelled"})
        except Exception as e:  # noqa: BLE001 - report and keep serving
            send({"id": msg["id"], "error": str(e)})
        finally:
            current[0] = -1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=10, help="flow-matching steps (default 10)")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--no-fast", action="store_true", help="upstream behavior (for comparison)")
    ap.add_argument("--save", help="bench: write samples to this folder")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    t = time.perf_counter()
    model = load(args.steps, fast=not args.no_fast)
    synth(model, "준비.", 0.5, 1.0)  # warm-up: CUDA kernels, caches
    load_s = round(time.perf_counter() - t, 1)
    if args.bench:
        print(f"load+warmup {load_s}s, steps={args.steps}, fast={not args.no_fast}, "
              f"gpu={torch.cuda.get_device_name(0)}")
        for rnd in range(2):  # second round shows whether it slows down over time
            for i, text in enumerate(BENCH):
                t = time.perf_counter()
                audio = synth(model, text, 0.5, 1.0)
                secs, dur = time.perf_counter() - t, len(audio) / model.sr
                print(f"  {secs:5.2f}s for {dur:4.2f}s audio  RTF {secs / dur:.2f}  | {text}")
                if args.save and rnd == 0:
                    import wave
                    from pathlib import Path

                    Path(args.save).mkdir(parents=True, exist_ok=True)
                    with wave.open(str(Path(args.save) / f"bench_{'fast' if not args.no_fast else 'orig'}_{i}.wav"),
                                   "wb") as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(model.sr)
                        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        return
    print(json.dumps({"ready": True, "sr": model.sr, "load_s": load_s}), flush=True)
    serve(model)


if __name__ == "__main__":
    main()
