__version__ = "0.2.1"

from .loupedeck_patch import apply_loupedeck_init_patch, apply_loupedeck_serial_reader_patch

apply_loupedeck_init_patch()
apply_loupedeck_serial_reader_patch()
