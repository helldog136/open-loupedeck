"""Icon rasterizing keeps aspect ratio (no cropping) and monochrome icons take the text color."""

from __future__ import annotations

from PIL import Image

from open_loupedeck.button_render import _tint_icon
from open_loupedeck.icon_loader import _svg_to_rgba, icon_is_tintable

SQUARE_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24"/></svg>'


def test_square_icon_in_a_wide_box_is_centered_not_stretched_or_cropped():
    img = _svg_to_rgba(SQUARE_SVG, 60, 30)
    assert img.size == (60, 30)
    left, top, right, bottom = img.getchannel("A").getbbox()
    assert (top, bottom) == (0, 30)  # full height kept -- nothing cut off
    assert right - left == 30  # still square
    assert abs(left - 15) <= 1  # centered horizontally


def test_square_icon_in_a_tall_box_is_scaled_to_the_width():
    img = _svg_to_rgba(SQUARE_SVG, 30, 60)
    left, top, right, bottom = img.getchannel("A").getbbox()
    assert (left, right) == (0, 30)
    assert bottom - top == 30


def test_which_icon_sets_take_the_text_color():
    assert icon_is_tintable("mdi:video-marker")
    assert icon_is_tintable("lucide:play")
    assert icon_is_tintable("heroicons:24/solid/heart")
    assert icon_is_tintable("si:github")
    assert not icon_is_tintable("si:github/ff0000")  # explicit brand color wins
    assert not icon_is_tintable("https://example.com/x.svg")
    assert not icon_is_tintable("library/images/logo.png")


def test_tint_keeps_shape_and_uses_the_given_color():
    src = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    src.putpixel((1, 1), (0, 0, 0, 255))
    out = _tint_icon(src, (255, 136, 0, 255))
    assert out.getpixel((1, 1)) == (255, 136, 0, 255)
    assert out.getpixel((0, 0))[3] == 0
