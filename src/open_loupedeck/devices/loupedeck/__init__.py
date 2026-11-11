"""Loupedeck backend (Live, Live S): serial driver, upstream patches, USB discovery, descriptors.

Everything that knows about the python-loupedeck-live driver lives in this package. Submodules
are imported on demand (``patches`` is imported by the package root before anything else).
"""
