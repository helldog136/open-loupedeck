"""Gradient generation and idle/press animation math for on-device button text.

Design rule (see project plan): any text shown on a physical key must be previewable and fully
customizable (font/size/color/gradient/background/idle animation/press animation). This covers
the pure-function pieces; rendering itself is covered by the render_tactile_key_image smoke test.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from open_loupedeck.button_render import (
    PRESS_ANIMATION_DURATION_TICKS,
    _apply_whole_key_press_effect,
    _effective_font_size_cap,
    _gradient_spec_from_entry,
    _idle_animation_type,
    _idle_speed,
    _make_gradient_rgba,
    _press_animation_duration_ticks,
    _press_animation_type,
    _resolve_background,
    _resolve_text_fill,
    render_tactile_key_image,
)


def test_make_gradient_rgba_returns_correct_size_and_mode():
    img = _make_gradient_rgba((90, 90), (255, 0, 0, 255), (0, 0, 255, 255), 45)
    assert img.size == (90, 90)
    assert img.mode == "RGBA"


def test_make_gradient_rgba_endpoint_colors_at_0_and_180_degrees():
    # At angle 0 the gradient runs top (black-mapped) to bottom (white-mapped).
    img = _make_gradient_rgba((10, 10), (10, 20, 30, 255), (200, 210, 220, 255), 0)
    top = img.getpixel((5, 0))[:3]
    bottom = img.getpixel((5, 9))[:3]
    assert top != bottom


def test_gradient_spec_from_entry_requires_both_endpoints():
    incomplete = {"text_gradient_from": "#ff0000"}
    keys = ("text_gradient_from", "text_gradient_to", "text_gradient_angle")
    assert _gradient_spec_from_entry(incomplete, *keys) is None
    spec = _gradient_spec_from_entry(
        {"text_gradient_from": "#ff0000", "text_gradient_to": "#0000ff", "text_gradient_angle": "30"},
        "text_gradient_from",
        "text_gradient_to",
        "text_gradient_angle",
    )
    assert spec is not None
    color_from, color_to, angle = spec
    assert color_from == (255, 0, 0, 255)
    assert color_to == (0, 0, 255, 255)
    assert angle == 30.0


def test_idle_animation_type_rejects_unknown_values():
    assert _idle_animation_type({}) == "none"
    assert _idle_animation_type({"idle_animation": "shake"}) == "shake"
    assert _idle_animation_type({"idle_animation": "not-a-real-one"}) == "none"


def test_press_animation_type_rejects_unknown_values():
    assert _press_animation_type({"press_animation": "invert"}) == "invert"
    assert _press_animation_type({"press_animation": "nope"}) == "none"


def test_idle_speed_is_clamped():
    assert _idle_speed({"idle_animation_speed": 0.0}) == 0.1
    assert _idle_speed({"idle_animation_speed": 999}) == 10.0
    assert _idle_speed({}) == 1.0


def test_resolve_text_fill_shake_produces_nonzero_offset_at_some_phase():
    entry = {"idle_animation": "shake", "idle_animation_speed": 3}
    offsets = {_resolve_text_fill(entry, (90, 90), (255, 255, 255, 255), frame, None)[2] for frame in range(20)}
    assert any(o != (0, 0) for o in offsets)


def test_resolve_text_fill_pulse_varies_alpha_scale_over_time():
    entry = {"idle_animation": "pulse"}
    scales = {
        round(_resolve_text_fill(entry, (90, 90), (255, 255, 255, 255), frame, None)[3], 2) for frame in range(20)
    }
    assert len(scales) > 1
    assert all(0.0 <= s <= 1.0 for s in scales)


def test_resolve_text_fill_color_cycle_changes_hue_over_time():
    entry = {"idle_animation": "color_cycle"}
    colors = {_resolve_text_fill(entry, (90, 90), (255, 255, 255, 255), frame, None)[0] for frame in range(0, 60, 10)}
    assert len(colors) > 1


def test_resolve_text_fill_press_takes_priority_over_idle():
    # Idle would shake, but a press animation is active -> idle effect must not apply.
    entry = {"idle_animation": "shake", "press_animation": "none"}
    _, _, offset, alpha_scale = _resolve_text_fill(entry, (90, 90), (255, 255, 255, 255), 5, press_elapsed_frames=1)
    assert offset == (0, 0)
    assert alpha_scale == 1.0


def test_resolve_text_fill_slide_reappear_offsets_negative_then_back():
    entry = {"press_animation": "slide_reappear"}
    duration = _press_animation_duration_ticks("slide_reappear")
    _, _, offset_start, _ = _resolve_text_fill(entry, (100, 100), (255, 255, 255, 255), 0, press_elapsed_frames=0)
    _, _, offset_mid, _ = _resolve_text_fill(
        entry, (100, 100), (255, 255, 255, 255), 0, press_elapsed_frames=duration // 2
    )
    _, _, offset_end, _ = _resolve_text_fill(entry, (100, 100), (255, 255, 255, 255), 0, press_elapsed_frames=duration)
    assert offset_start == (0, 0)  # p=0 -> normal position at the instant of the press
    assert offset_mid == (-100, 0)  # p=0.5 -> fully off-screen (left, the default direction)
    assert offset_end == (0, 0)  # p=1 -> back to normal position


def test_resolve_text_fill_slide_reappear_gets_a_longer_duration_than_other_press_types():
    # It packs two movements (out, back in) into its window, so it should run longer than a
    # single-phase effect like flash/zoom, or it reads as rushed.
    assert _press_animation_duration_ticks("slide_reappear") > PRESS_ANIMATION_DURATION_TICKS


def test_resolve_text_fill_slide_reappear_direction_right_is_positive_offset():
    entry = {"press_animation": "slide_reappear", "press_animation_direction": "right"}
    duration = _press_animation_duration_ticks("slide_reappear")
    _, _, offset_mid, _ = _resolve_text_fill(
        entry, (100, 100), (255, 255, 255, 255), 0, press_elapsed_frames=duration // 2
    )
    assert offset_mid == (100, 0)


def test_resolve_text_fill_slide_reappear_direction_up_and_down_move_vertically():
    duration = _press_animation_duration_ticks("slide_reappear")
    up_entry = {"press_animation": "slide_reappear", "press_animation_direction": "up"}
    down_entry = {"press_animation": "slide_reappear", "press_animation_direction": "down"}
    _, _, up_offset, _ = _resolve_text_fill(
        up_entry, (100, 100), (255, 255, 255, 255), 0, press_elapsed_frames=duration // 2
    )
    _, _, down_offset, _ = _resolve_text_fill(
        down_entry, (100, 100), (255, 255, 255, 255), 0, press_elapsed_frames=duration // 2
    )
    assert up_offset == (0, -100)
    assert down_offset == (0, 100)


def test_effective_font_size_cap_zoom_shrinks_toward_base_over_time():
    entry = {"press_animation": "zoom_text"}
    early = _effective_font_size_cap(20, entry, 0)
    late = _effective_font_size_cap(20, entry, PRESS_ANIMATION_DURATION_TICKS)
    assert early > late
    assert late == 20


def test_effective_font_size_cap_passthrough_without_zoom():
    assert _effective_font_size_cap(20, {}, 2) == 20
    assert _effective_font_size_cap(None, {}, None) is None


def test_resolve_background_solid_when_no_gradient_configured():
    img = _resolve_background({}, (10, 10), (1, 2, 3, 255), None)
    assert img.getpixel((0, 0)) == (1, 2, 3, 255)


def test_resolve_background_gradient_when_configured():
    entry = {"background_gradient_from": "#000000", "background_gradient_to": "#ffffff"}
    img = _resolve_background(entry, (10, 10), (1, 2, 3, 255), None)
    assert img.getpixel((5, 0)) != img.getpixel((5, 9))


def test_apply_whole_key_press_effect_noop_when_not_pressed():
    base = Image.new("RGBA", (10, 10), (10, 20, 30, 255))
    out = _apply_whole_key_press_effect(base, {"press_animation": "flash"}, None)
    assert out is base


def test_apply_whole_key_press_effect_flash_brightens_at_press_start():
    base = Image.new("RGBA", (10, 10), (10, 20, 30, 255))
    out = _apply_whole_key_press_effect(base, {"press_animation": "flash"}, 0)
    r, g, b, _a = out.getpixel((5, 5))
    assert r > 10 and g > 20 and b > 30


def test_apply_whole_key_press_effect_flash_color_is_customizable():
    base = Image.new("RGBA", (10, 10), (0, 0, 0, 255))
    out = _apply_whole_key_press_effect(base, {"press_animation": "flash", "press_flash_color": "#ff0000"}, 0)
    r, g, b, _a = out.getpixel((5, 5))
    # A red flash over black should push red up without also pushing green/blue up.
    assert r > g and r > b


def test_apply_whole_key_press_effect_invert_is_a_hard_toggle_not_a_fade():
    # invert deliberately snaps (fully inverted, then fully normal) rather than blending, so it
    # reads as a visually distinct "flicker" next to flash's smooth glow.
    base = Image.new("RGBA", (10, 10), (10, 20, 30, 255))
    duration = _press_animation_duration_ticks("invert")
    just_pressed = _apply_whole_key_press_effect(base, {"press_animation": "invert"}, 0)
    about_to_end = _apply_whole_key_press_effect(base, {"press_animation": "invert"}, duration - 1)
    normal_pixel = base.getpixel((5, 5))
    assert just_pressed.getpixel((5, 5)) != normal_pixel
    assert about_to_end.getpixel((5, 5)) == normal_pixel


def test_render_tactile_key_image_with_gradients_and_animations_does_not_crash(tmp_path: Path):
    cases = [
        {"text": "Grad", "text_gradient_from": "#ff0000", "text_gradient_to": "#0000ff"},
        {"text": "BG", "background_gradient_from": "#222", "background_gradient_to": "#8844ff"},
        {"text": "Shake", "idle_animation": "shake"},
        {"text": "Pulse", "idle_animation": "pulse"},
        {"text": "Cycle", "idle_animation": "color_cycle"},
        {"text": "Rot", "text_gradient_from": "#0f0", "text_gradient_to": "#f0f", "idle_animation": "gradient_rotate"},
    ]
    for entry in cases:
        img = render_tactile_key_image(entry, tmp_path, animation_frame=3)
        assert img is not None
        assert img.size == (90, 90)

    press_cases = ["flash", "invert", "zoom_text", "slide_reappear"]
    for press_type in press_cases:
        img = render_tactile_key_image(
            {"text": "Press", "press_animation": press_type},
            tmp_path,
            animation_frame=0,
            press_elapsed_frames=1,
        )
        assert img is not None
        assert img.size == (90, 90)


def test_render_tactile_key_image_background_gradient_alone_is_not_dropped(tmp_path: Path):
    # No text, no image, no plain `background` -- only a background gradient. This must still
    # render (matches the plain-`background`-only case), not be treated as "nothing to draw".
    entry = {"background_gradient_from": "#000000", "background_gradient_to": "#ffffff"}
    img = render_tactile_key_image(entry, tmp_path)
    assert img is not None
    assert img.size == (90, 90)
