"""The interface every device backend implements (no driver imports here).

The agent (``app.py``), the skin renderer and the web UI only talk to a :class:`DeviceBackend`:
open/close it, draw images and set LEDs by control id, set the brightness, and receive
:class:`~open_loupedeck.events.ControlEvent` objects (``ControlEvent(control_id, type, value)``).
Driver specifics (pixel formats, serial threads, protocol names) stay inside the backend package.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..events import ControlEvent
from .model import DeviceModel

if TYPE_CHECKING:
    from PIL import Image

    from ..config import Settings

EventCallback = Callable[[ControlEvent], None]
"""Called from the backend's own thread for every input event (schedule work, do not block)."""

UnpluggedCallback = Callable[[], None]
"""Called from the backend's own thread once the device is gone (unplug, fatal I/O error)."""


@runtime_checkable
class DeviceBackend(Protocol):
    """One opened device.

    Image and LED calls may block (USB/serial I/O): callers run them off the event loop. The
    backend is a context manager holding its update lock, so a full redraw is not interleaved
    with another thread's draw (``with backend: ...``).
    """

    model: DeviceModel
    path: str | None
    """Where the device was opened (serial port, HID path...), for the status page and logs."""

    @property
    def is_open(self) -> bool:
        """The underlying connection is open (False once unplugged or closed)."""
        ...

    @property
    def unplugged(self) -> bool:
        """The device went away; the reconnect loop opens a fresh backend."""
        ...

    def open(self) -> None:
        """Start I/O (reader threads...). Events are delivered once a callback is set."""
        ...

    def close(self) -> None:
        """Stop I/O; idempotent and safe after an unplug."""
        ...

    def __enter__(self) -> Any: ...

    def __exit__(self, *exc: Any) -> Any: ...

    def set_image(self, control_id: str, image: Image.Image) -> None:
        """Draw ``image`` (sized ``model.image_size(control_id)``) on a control with an image output."""
        ...

    def set_brightness(self, pct: int) -> None:
        """Screen brightness, 0..100."""
        ...

    def set_led(self, control_id: str, rgb: tuple[int, int, int]) -> None:
        """Colour of the LED of ``control_id`` (only controls with an ``led`` output)."""
        ...

    def set_event_callback(self, callback: EventCallback | None) -> None: ...

    def set_unplugged_callback(self, callback: UnpluggedCallback | None) -> None:
        """Register the unplug signal (fires at most once per backend, from any thread)."""
        ...


@dataclass(frozen=True)
class DiscoveredDevice:
    """A device found by :func:`~open_loupedeck.devices.registry.discover_devices`."""

    backend: str
    """Backend family name (``loupedeck``)."""
    path: str
    model: DeviceModel | None
    """``None`` when the backend sees its vendor but cannot tell the model."""

    def to_dict(self) -> dict[str, Any]:
        return {"backend": self.backend, "path": self.path, "model": self.model.id if self.model else None}


class BackendFactory(Protocol):
    """Registered once per backend family; knows its models, finds devices and opens them."""

    family: str
    models: tuple[DeviceModel, ...]

    def discover(self) -> list[DiscoveredDevice]: ...

    def open(self, settings: Settings) -> DeviceBackend:
        """Open a device per ``settings.device`` (path/model/baudrate); raise when none answers."""
        ...

    def normalize_message(self, msg: dict[str, Any], model: DeviceModel | None = None) -> ControlEvent | None:
        """Map a driver-native message dict to an event on ``model`` (synthetic presses, tests)."""
        ...


def device_model_of(device: Any) -> DeviceModel | None:
    """The :class:`DeviceModel` of a backend (``None`` for no device / an object without one)."""

    m = getattr(device, "model", None) if device is not None else None
    return m if isinstance(m, DeviceModel) else None
