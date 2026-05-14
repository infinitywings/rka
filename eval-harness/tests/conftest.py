"""pytest conftest for eval-harness tests.

Puts the eval-harness directory on sys.path so tests can
`from eval_harness.metrics import …` without installing the package.
"""

from __future__ import annotations

import sys
from pathlib import Path

EVAL_HARNESS_DIR = Path(__file__).resolve().parent.parent
if str(EVAL_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_HARNESS_DIR))
