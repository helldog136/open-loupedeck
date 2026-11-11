__version__ = "0.2.1"

from .devices.loupedeck.patches import apply_loupedeck_init_patch, apply_loupedeck_serial_reader_patch

apply_loupedeck_init_patch()
apply_loupedeck_serial_reader_patch()
