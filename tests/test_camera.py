import time

import numpy as np

from torti.camera import Camera


def test_snapshot_drops_stale_frame():
    cam = Camera("test")
    assert cam.snapshot() is None and not cam.connected
    cam._frame, cam._frame_time = np.zeros((4, 4, 3), np.uint8), time.monotonic()
    assert cam.snapshot() is not None and cam.connected
    cam._frame_time -= Camera.STALE_S + 0.5  # camera unplugged: last frame is old
    assert cam.snapshot() is None and not cam.connected


def test_gui_and_engine_import():  # catches syntax errors in modules the unit tests don't touch
    import torti.engine  # noqa: F401
    import torti.gui  # noqa: F401


def test_average_still_skips_moving_frames():
    import cv2

    from torti.closeup import average_still

    rng = np.random.default_rng(0)
    scene = cv2.resize(rng.integers(60, 200, (54, 96, 3)).astype(np.uint8), (960, 540)).astype(np.float32)
    noisy = [np.clip(scene + rng.normal(0, 8, scene.shape), 0, 255).astype(np.uint8) for _ in range(6)]
    moved = np.roll(noisy[0], 200, axis=1)  # a hand moved through the picture
    out, n = average_still([moved, *noisy])
    assert n == 6  # the moved frame is left out
    assert np.abs(out.astype(np.float32) - scene).mean() < np.abs(noisy[-1].astype(np.float32) - scene).mean() * 0.6
    out, n = average_still([noisy[0]])
    assert n == 1


def test_for_model_enlarges_small_crops():
    import cv2

    from torti.closeup import for_model

    small = np.zeros((180, 320, 3), np.uint8)
    img = cv2.imdecode(np.frombuffer(for_model(small), np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (720, 1280)
    tiny = np.zeros((50, 80, 3), np.uint8)  # at most 4x
    assert cv2.imdecode(np.frombuffer(for_model(tiny), np.uint8), cv2.IMREAD_COLOR).shape[:2] == (200, 320)
