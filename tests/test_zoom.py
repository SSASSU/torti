import numpy as np
import pytest

from torti.closeup import Zoom
from torti.intent import match_command, match_zoom


@pytest.mark.parametrize("text,expected", [
    ("확대해", ("in", None, None)),
    ("더 확대해 줘", ("in", None, None)),
    ("세 배로 확대", ("in", None, 3.0)),
    ("2배 확대해줘.", ("in", None, 2.0)),
    ("보드 확대해", ("in", "보드", None)),
    ("이 칩 좀 확대해 줄래?", ("in", "칩", None)),
    ("아두이노 핀 헤더 쪽을 확대해 줘", ("in", "아두이노 핀 헤더", None)),
    ("거기 확대", ("in", None, None)),
    ("축소해", ("out", None, None)),
    ("원래대로", ("reset", None, None)),
    ("전체 화면 보여줘", ("reset", None, None)),
    ("확대 풀어", ("reset", None, None)),
])
def test_match_zoom(text, expected):
    assert match_zoom(text) == expected


@pytest.mark.parametrize("text", ["확대하면 잘 보여?", "확대경으로 볼게", "350도로 맞추면 돼?", "소리 크게 해",
                                  "이거 확대해서 보면 납땜이 덜 된 것 같은데 어떻게 고쳐야 할지 알려줘"])
def test_not_zoom(text):
    assert match_zoom(text) is None


def test_zoom_is_checked_before_commands():
    assert match_command("확대 취소") == "cancel"  # so the engine must try match_zoom first
    assert match_zoom("확대 취소") == ("reset", None, None)


def test_zoom_geometry():
    z = Zoom()
    assert not z.active and z.rect() == (0, 0, 1, 1)
    z.zoom_at(2.0)
    assert z.rect() == pytest.approx((0.25, 0.25, 0.75, 0.75))
    z.zoom_at(4.0, 1.0, 1.0)  # the bottom-right corner stays put
    assert z.rect()[2:] == pytest.approx((0.75, 0.75))
    z.pan(10, 10)  # can't leave the frame
    assert z.rect() == pytest.approx((0.75, 0.75, 1.0, 1.0))
    z.to_box((0.40, 0.40, 0.50, 0.45))
    assert z.factor == pytest.approx(4.0) and (z.cx, z.cy) == pytest.approx((0.45, 0.425))
    z.zoom_at(2.0)
    assert z.view_to_full((0.5, 0.5, 1.0, 1.0)) == pytest.approx((z.cx, z.cy, z.rect()[2], z.rect()[3]))
    frame = np.zeros((1080, 1920, 3), np.uint8)
    assert z.crop(frame).shape == (540, 960, 3)
    z.zoom_at(0.3)
    assert not z.active and z.crop(frame).shape == frame.shape


def test_tag_filter_zoom_request():
    from torti.visual import TagFilter

    f = TagFilter()
    out = f.feed('<확대 대상="저') + f.feed('항 R3"/>')
    assert out == "" and f.zoom_target == "저항 R3"
    f = TagFilter()
    assert f.feed("잠깐만요. ") == "잠깐만요. "
    f.feed('<확대 대상="보드"')
    assert f.flush() == "" and f.zoom_target is None  # unfinished tag is dropped, not spoken
    f = TagFilter()
    f.feed('<확대 대상="칩"/>')
    assert f.zoom_target == "칩"


def test_reading_questions_send_a_photo():
    from torti.intent import needs_image

    for q in ("자, 다시 읽어봐라.", "기판에 뭐라고 써 있어?", "칩 모델명 알려줘"):
        assert needs_image(q)
    assert not needs_image("350도로 맞추면 돼?")


def test_look_requests_send_a_photo():
    from torti.intent import needs_image

    for q in ("봐봐.", "봐바.", "아니 어떠냐고.", "이제 어때?", "어떻게 보여?"):
        assert needs_image(q), q


def test_pointing_trigger_ignores_web_search_talk():
    from torti.visual import wants_pointing

    assert not wants_pointing("아니 이 정도면 인터넷에 찾아봐야지.")
    assert wants_pointing("D3 찾아줘") and wants_pointing("J2가 어디야?")


def test_inspector_crops_the_found_part():
    from torti.closeup import Inspector, needs_close_look
    from torti.visual import Mark

    class FakePointer:
        def locate(self, jpeg, size, question):
            return [Mark("사진", (400, 300, 500, 400), "보드")], 0.1

    frame = np.zeros((1080, 1920, 3), np.uint8)
    look = Inspector(FakePointer()).look([frame, frame], "보드에 뭐라고 써 있어?")
    assert look.label == "보드" and look.box == pytest.approx((0.4, 0.3, 0.5, 0.4)) and look.frames == 2
    assert look.factor == pytest.approx(4.0)  # small part: as close as zoom goes
    assert needs_close_look("보드에 뭐라고 써 있어?") and needs_close_look("저항 색띠 읽어줘")
    assert not needs_close_look("350도면 돼?")
