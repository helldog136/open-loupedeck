"""Device abstraction layer: model descriptors, the backend protocol and the backend registry.

Kept import-light on purpose (the package root imports :mod:`.loupedeck.patches` at start-up):
import :mod:`.model`, :mod:`.base` or :mod:`.registry` directly. See ``docs/devices.md``.
"""
