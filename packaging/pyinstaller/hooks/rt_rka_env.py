"""Runtime hook — sets bundled-sidecar env defaults before user code runs.

PyInstaller invokes this before the entry-point's first import, so
`os.environ.setdefault` here lands before any `RKAConfig` instantiation.
"""
import os

os.environ.setdefault("RKA_EMBEDDINGS_ENABLED", "true")
