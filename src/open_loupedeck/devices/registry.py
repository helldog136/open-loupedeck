"""Backend registry: which device families exist, discovery, and opening per ``device:`` config.

Built-in backends are registered lazily on first use (so importing this module does not import
any driver). Tests (or a future plugin) can build a :class:`DeviceRegistry` with their own
factories, or :func:`register_backend` one on the default registry.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..events import ControlEvent
from .base import BackendFactory, DeviceBackend, DiscoveredDevice
from .model import DeviceModel

if TYPE_CHECKING:
    from ..config import Settings

logger = logging.getLogger(__name__)


def _builtin_models() -> tuple[DeviceModel, ...]:
    # Pure data, no driver import.
    from .loupedeck.models import LOUPEDECK_MODELS

    from .virtual.models import VIRTUAL_MODELS

    return LOUPEDECK_MODELS + VIRTUAL_MODELS


def _builtin_factories() -> list[BackendFactory]:
    from .loupedeck.backend import LoupedeckBackendFactory

    from .virtual.backend import VirtualBackendFactory

    return [LoupedeckBackendFactory(), VirtualBackendFactory()]


class DeviceRegistry:
    def __init__(self, factories: list[BackendFactory] | None = None) -> None:
        # None = the built-in backends, loaded on first use.
        self._factories: list[BackendFactory] | None = list(factories) if factories is not None else None
        self._forced_model: str | None = None

    def force_model(self, name: str | None) -> None:
        """Open this model (a ``--virtual`` run) whatever ``device.model`` says; ``None`` clears it."""

        self._forced_model = name

    @property
    def forced_model(self) -> str | None:
        return self._forced_model

    def factories(self) -> list[BackendFactory]:
        if self._factories is None:
            self._factories = _builtin_factories()
        return list(self._factories)

    def register(self, factory: BackendFactory) -> None:
        """Add (or replace, by family) a backend; registration order is the auto-detect order."""

        current = [f for f in self.factories() if f.family != factory.family]
        current.append(factory)
        self._factories = current

    def models(self) -> list[DeviceModel]:
        if self._factories is None:
            return list(_builtin_models())
        return [m for f in self._factories for m in f.models]

    def model_by_name(self, name: str | None) -> DeviceModel | None:
        """Model whose id or ``device.model`` config name is ``name`` (``auto`` -> ``None``)."""

        for m in self.models():
            if m.matches_name(name):
                return m
        return None

    def discover_devices(self) -> list[DiscoveredDevice]:
        out: list[DiscoveredDevice] = []
        for f in self.factories():
            try:
                out.extend(f.discover())
            except Exception:
                logger.debug("Device discovery failed for backend %s", f.family, exc_info=True)
        return out

    def open_backend(self, settings: Settings) -> DeviceBackend:
        """Open the configured device (``device.path`` / ``model`` / ``baudrate``).

        A ``device.model`` naming a known model goes straight to that model's backend; ``auto``
        (or an unknown value) tries every backend in registration order. The error of the last
        backend tried is raised unchanged (one backend = exactly its own message).
        """

        forced = self.model_by_name(self._forced_model) if self._forced_model else None
        if forced is not None:
            for f in self.factories():
                if f.family == forced.family and hasattr(f, "open_model"):
                    return f.open_model(forced)
        wanted = self.model_by_name(settings.device.model)
        factories = self.factories()
        if wanted is not None:
            factories = [f for f in factories if f.family == wanted.family] or factories
        else:
            # ``auto``: a backend that is only chosen by name (the virtual device) never competes
            # with real hardware.
            factories = [f for f in factories if getattr(f, "auto_detect", True)]
        if not factories:
            raise RuntimeError("No device backend available.")
        last: Exception | None = None
        for f in factories:
            try:
                return f.open(settings)
            except Exception as e:
                logger.debug("Backend %s: %s", f.family, e)
                last = e
        assert last is not None
        raise last

    def normalize_message(self, msg: dict[str, Any], model: DeviceModel | None = None) -> ControlEvent | None:
        """First backend that understands a driver-native message dict (synthetic presses)."""

        for f in self.factories():
            ev = f.normalize_message(msg, model)
            if ev is not None:
                return ev
        return None


_default = DeviceRegistry()


def default_registry() -> DeviceRegistry:
    return _default


def register_backend(factory: BackendFactory) -> None:
    _default.register(factory)


def known_models() -> list[DeviceModel]:
    return _default.models()


def model_by_name(name: str | None) -> DeviceModel | None:
    return _default.model_by_name(name)


def force_model(name: str | None) -> None:
    _default.force_model(name)


def discover_devices() -> list[DiscoveredDevice]:
    return _default.discover_devices()


def open_backend(settings: Settings) -> DeviceBackend:
    return _default.open_backend(settings)


def normalize_native_message(msg: dict[str, Any], model: DeviceModel | None = None) -> ControlEvent | None:
    return _default.normalize_message(msg, model)


def default_model() -> DeviceModel:
    """Model assumed for ``device.model: auto`` without a connected device (the Live S)."""

    from .loupedeck.models import DEFAULT_MODEL

    return DEFAULT_MODEL


def resolve_model(configured: str | None, device: Any = None) -> DeviceModel:
    """The model the agent works with: the connected device's, else ``device.model`` from the
    config, else (``auto``) :func:`default_model`."""

    from .base import device_model_of

    dm = device_model_of(device)
    if dm is not None:
        return dm
    return model_by_name(configured) or default_model()


def config_model(configured: str | None) -> DeviceModel:
    """The model a config is written for: ``device.model``, ``auto`` -> :func:`default_model`."""

    return model_by_name(configured) or default_model()
