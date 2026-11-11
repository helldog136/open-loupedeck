"""In-memory :class:`DeviceBackend` for tests (no serial port, no driver)."""

from __future__ import annotations

from typing import Any

from open_loupedeck.devices.base import DiscoveredDevice
from open_loupedeck.devices.loupedeck.models import LOUPEDECK_LIVE_S
from open_loupedeck.devices.model import DeviceModel
from open_loupedeck.events import ControlEvent


class FakeBackend:
    """Records every call; ``emit``/``unplug`` play the device side."""

    def __init__(self, model: DeviceModel = LOUPEDECK_LIVE_S, path: str | None = "/dev/fake0") -> None:
        self.model = model
        self.path = path
        self.images: list[str] = []
        self.last_images: dict[str, Any] = {}
        self.levels: list[int] = []
        self.colors: dict[str, tuple[int, int, int]] = {}
        self.opened = False
        self.closed = False
        self.event_callback: Any = None
        self.unplugged_callback: Any = None
        self._unplugged = False
        self.lock_depth = 0

    # lifecycle
    @property
    def is_open(self) -> bool:
        return self.opened and not self.closed and not self._unplugged

    @property
    def unplugged(self) -> bool:
        return self._unplugged

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeBackend:
        self.lock_depth += 1
        return self

    def __exit__(self, *exc: Any) -> None:
        self.lock_depth -= 1

    # output
    def set_image(self, control_id: str, image: Any) -> None:
        self.images.append(control_id)
        self.last_images[control_id] = image

    def set_brightness(self, pct: int) -> None:
        self.levels.append(pct)

    def set_led(self, control_id: str, rgb: tuple[int, int, int]) -> None:
        self.colors[control_id] = rgb

    # input
    def set_event_callback(self, callback: Any) -> None:
        self.event_callback = callback

    def set_unplugged_callback(self, callback: Any) -> None:
        self.unplugged_callback = callback

    # device side
    def emit(self, ev: ControlEvent) -> None:
        if self.event_callback is not None:
            self.event_callback(ev)

    def press(self, control_id: str) -> None:
        """Press + release of ``control_id``, as the device thread would deliver them."""

        self.emit(ControlEvent(control_id, "press"))
        self.emit(ControlEvent(control_id, "release"))

    def turn(self, control_id: str, steps: int) -> None:
        self.emit(ControlEvent(control_id, "rotate", steps))

    def unplug(self) -> None:
        self._unplugged = True
        if self.unplugged_callback is not None:
            self.unplugged_callback()


class FakeFactory:
    """Backend factory for registry tests."""

    def __init__(self, family: str, models: tuple[DeviceModel, ...], found: list[str] | None = None) -> None:
        self.family = family
        self.models = models
        self.found = found or []
        self.opened: list[Any] = []
        self.fail: Exception | None = None

    def discover(self) -> list[DiscoveredDevice]:
        return [DiscoveredDevice(self.family, p, self.models[0]) for p in self.found]

    def open(self, settings: Any) -> FakeBackend:
        self.opened.append(settings)
        if self.fail is not None:
            raise self.fail
        return FakeBackend(self.models[0])

    def normalize_message(self, msg: dict[str, Any], model: DeviceModel | None = None) -> ControlEvent | None:
        if msg.get("fake") == self.family:
            return ControlEvent(f"key_{int(msg.get('key', 0))}_0", "press", None, msg)
        return None
